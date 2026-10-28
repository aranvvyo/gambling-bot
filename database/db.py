import aiosqlite, json, uuid, asyncio, time, secrets, hashlib, hmac, os
from functools import wraps

def serialized(fn):
    @wraps(fn)
    async def wrapper(self, *args, **kwargs):
        async with self.lock:
            return await fn(self, *args, **kwargs)
    return wrapper
from pathlib import Path

class Database:
    def __init__(self, url, min_bet=1, max_bet=10000, max_payout=1000000, daily_bet_limit=0):
        if not url.startswith('sqlite:///'): raise ValueError('Only SQLite is supported in this release')
        self.path=url.removeprefix('sqlite:///'); self.conn=None; self.lock=asyncio.Lock(); self.min_bet=min_bet; self.max_bet=max_bet; self.max_payout=max_payout; self.daily_bet_limit=daily_bet_limit; self.event_logger=None; self.maintenance_mode=False
    async def open(self):
        if self.path != ':memory:':
            db_path = Path(self.path).expanduser()
            db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.path = str(db_path)
        self.conn=await aiosqlite.connect(self.path); self.conn.row_factory=aiosqlite.Row
        if self.path != ':memory:':
            try: os.chmod(self.path,0o600)
            except OSError: pass
        await self.conn.execute('PRAGMA journal_mode=WAL'); await self.conn.execute('PRAGMA foreign_keys=ON'); await self.conn.execute('PRAGMA busy_timeout=5000')
        await self.conn.executescript(Path(__file__).with_name('schema.sql').read_text()); await self.conn.commit()
        await self.conn.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
        migration=Path(__file__).with_name('migrations')/'001_fairness_audit.sql'
        cur=await self.conn.execute('SELECT 1 FROM schema_migrations WHERE version=?',('001_fairness_audit',))
        if not await cur.fetchone():
            await self.conn.executescript(migration.read_text())
            await self.conn.execute('INSERT OR IGNORE INTO schema_migrations(version) VALUES(?)',('001_fairness_audit',))
        cols=await self.conn.execute('PRAGMA table_info(game_sessions)'); names={r['name'] for r in await cols.fetchall()}
        if 'fair_round_id' not in names: await self.conn.execute('ALTER TABLE game_sessions ADD COLUMN fair_round_id TEXT')
        await self.conn.execute('INSERT OR IGNORE INTO schema_migrations(version) VALUES(?)',('002_game_fair_reference',))
        if 'session_max_payout' not in names:
            await self.conn.execute(f'ALTER TABLE game_sessions ADD COLUMN session_max_payout INTEGER NOT NULL DEFAULT {int(self.max_payout)}')
            await self.conn.execute('UPDATE game_sessions SET session_max_payout=? WHERE settled=0',(self.max_payout,))
        await self.conn.execute('INSERT OR IGNORE INTO schema_migrations(version) VALUES(?)',('003_game_rule_snapshot',))
        seedcols=await self.conn.execute('PRAGMA table_info(fair_seeds)'); seednames={r['name'] for r in await seedcols.fetchall()}
        if 'revealed_published_at' not in seednames: await self.conn.execute('ALTER TABLE fair_seeds ADD COLUMN revealed_published_at INTEGER')
        await self.conn.execute('INSERT OR IGNORE INTO schema_migrations(version) VALUES(?)',('004_public_seed_reveals',))
        sesscols=await self.conn.execute('PRAGMA table_info(game_sessions)'); sessnames={r['name'] for r in await sesscols.fetchall()}
        if 'session_max_bet' not in sessnames:
            await self.conn.execute(f'ALTER TABLE game_sessions ADD COLUMN session_max_bet INTEGER NOT NULL DEFAULT {int(self.max_bet)}')
            await self.conn.execute('UPDATE game_sessions SET session_max_bet=? WHERE settled=0',(self.max_bet,))
        if 'session_daily_limit' not in sessnames:
            await self.conn.execute(f'ALTER TABLE game_sessions ADD COLUMN session_daily_limit INTEGER NOT NULL DEFAULT {int(self.daily_bet_limit)}')
            await self.conn.execute('UPDATE game_sessions SET session_daily_limit=? WHERE settled=0',(self.daily_bet_limit,))
        await self.conn.execute('INSERT OR IGNORE INTO schema_migrations(version) VALUES(?)',('005_session_limits',))
        deposit_migration_version='006_deposit_verification_metadata'
        cur=await self.conn.execute('SELECT 1 FROM schema_migrations WHERE version=?',(deposit_migration_version,))
        if not await cur.fetchone():
            depositcols=await self.conn.execute('PRAGMA table_info(deposits)'); depositnames={r['name'] for r in await depositcols.fetchall()}
            migration=Path(__file__).with_name('migrations')/'002_deposit_verification_metadata.sql'
            for statement in migration.read_text().split(';'):
                statement=statement.strip()
                if not statement or statement.startswith('--'): continue
                column=statement.split('ADD COLUMN ',1)[1].split()[0]
                if column not in depositnames: await self.conn.execute(statement)
            await self.conn.execute('INSERT INTO schema_migrations(version) VALUES(?)',(deposit_migration_version,))
        await self.conn.commit(); return self
    async def close(self):
        if self.conn: await self.conn.close(); self.conn=None
    @serialized
    async def balance(self,uid):
        await self.conn.execute('INSERT OR IGNORE INTO users(discord_id) VALUES(?)',(uid,)); await self.conn.commit()
        cur=await self.conn.execute('SELECT balance FROM users WHERE discord_id=?',(uid,)); return int((await cur.fetchone())['balance'])
    @serialized
    async def change_balance(self,uid,delta,kind,reference=None,detail=''):
        if type(delta) is not int or not delta: raise ValueError('delta must be a nonzero integer')
        if not isinstance(reference,str) or not reference.strip(): raise ValueError('a unique transaction reference is required')
        db=self.conn; await db.execute('BEGIN IMMEDIATE')
        try:
            if self.maintenance_mode: raise ValueError('Casino maintenance is active; wallet adjustments are paused.')
            await db.execute('INSERT OR IGNORE INTO users(discord_id) VALUES(?)',(uid,))
            if reference:
                cur=await db.execute('SELECT discord_id,kind,amount,detail,balance_after FROM transactions WHERE reference=?',(reference,)); old=await cur.fetchone()
                if old:
                    if (int(old['discord_id']), old['kind'], int(old['amount']), old['detail']) != (int(uid), kind, delta, detail):
                        raise ValueError('transaction reference already belongs to a different operation')
                    cur=await db.execute('SELECT balance FROM users WHERE discord_id=?',(uid,)); bal=int((await cur.fetchone())['balance']); await db.rollback(); return bal
            cur=await db.execute('UPDATE users SET balance=balance+? WHERE discord_id=? AND balance+?>=0',(delta,uid,delta))
            if cur.rowcount!=1: raise ValueError('insufficient funds')
            cur=await db.execute('SELECT balance FROM users WHERE discord_id=?',(uid,)); bal=int((await cur.fetchone())['balance'])
            await db.execute('INSERT INTO transactions(discord_id,kind,amount,balance_after,reference,detail) VALUES(?,?,?,?,?,?)',(uid,kind,delta,bal,reference,detail)); await db.commit(); return bal
        except: await db.rollback(); raise
    @serialized
    async def transfer(self,sender,recipient,amount,reference):
        if type(amount) is not int or amount <= 0: raise ValueError('amount must be a positive integer')
        if int(sender) == int(recipient): raise ValueError('self transfer is not allowed')
        if not isinstance(reference,str) or not reference.strip(): raise ValueError('reference required')
        db=self.conn; await db.execute('BEGIN IMMEDIATE')
        try:
            if self.maintenance_mode: raise ValueError('Casino maintenance is active; tips are paused.')
            await db.execute('INSERT OR IGNORE INTO users(discord_id) VALUES(?)',(sender,))
            await db.execute('INSERT OR IGNORE INTO users(discord_id) VALUES(?)',(recipient,))
            cur=await db.execute('UPDATE users SET balance=balance-? WHERE discord_id=? AND balance>=?',(amount,sender,amount))
            if cur.rowcount != 1: raise ValueError('insufficient funds')
            cur=await db.execute('SELECT balance FROM users WHERE discord_id=?',(sender,)); sender_balance=int((await cur.fetchone())['balance'])
            cur=await db.execute('UPDATE users SET balance=balance+? WHERE discord_id=?',(amount,recipient))
            cur=await db.execute('SELECT balance FROM users WHERE discord_id=?',(recipient,)); recipient_balance=int((await cur.fetchone())['balance'])
            await db.execute('INSERT INTO transactions(discord_id,kind,amount,balance_after,reference,detail) VALUES(?,?,?,?,?,?)',(sender,'tip_sent',-amount,sender_balance,reference,f'to {recipient}'))
            await db.execute('INSERT INTO transactions(discord_id,kind,amount,balance_after,reference,detail) VALUES(?,?,?,?,?,?)',(recipient,'tip_received',amount,recipient_balance,reference+':received',f'from {sender}'))
            await db.commit(); return sender_balance,recipient_balance
        except: await db.rollback(); raise
    @serialized
    async def history(self,uid,limit=10):
        cur=await self.conn.execute('SELECT kind,amount,balance_after,detail,created_at FROM transactions WHERE discord_id=? ORDER BY id DESC LIMIT ?',(uid,max(1,min(limit,50)))); return await cur.fetchall()
    @serialized
    async def deposit_history(self,uid,limit=10):
        cur=await self.conn.execute('SELECT invoice_id,currency,requested_amount,status,expires_at,created_at,updated_at FROM deposits WHERE discord_id=? ORDER BY created_at DESC LIMIT ?',(uid,max(1,min(limit,20)))); return await cur.fetchall()
    @serialized
    async def create_deposit(self,inv):
        db=self.conn; await db.execute('BEGIN IMMEDIATE')
        try:
            await db.execute('INSERT OR IGNORE INTO users(discord_id) VALUES(?)',(inv['discord_id'],))
            await db.execute('INSERT INTO deposits(invoice_id,discord_id,currency,requested_amount,address,status,expires_at,invoice_url) VALUES(?,?,?,?,?,?,?,?)',(inv['invoice'],inv['discord_id'],inv['currency'],str(inv['requested_amount']),inv['address'],inv.get('status','created'),inv.get('expires_at'),inv.get('invoice_url','')))
            await db.commit()
        except: await db.rollback(); raise
    @serialized
    async def deposit(self,invoice):
        cur=await self.conn.execute('SELECT * FROM deposits WHERE invoice_id=?',(invoice,)); return await cur.fetchone()
    @serialized
    async def update_deposit(self,invoice,status,txids,verified_amount=0):
        if type(verified_amount) is not int or verified_amount < 0: raise ValueError('verified deposit amount must be nonnegative integer units')
        await self.conn.execute("UPDATE deposits SET status=?,txids=?,verified_amount=?,updated_at=CURRENT_TIMESTAMP WHERE invoice_id=? AND credited=0",(status,json.dumps(txids),verified_amount,invoice)); await self.conn.commit()
    @serialized
    async def credit_deposit(self,invoice,amount,txid,detail=''):
        if type(amount) is not int or amount<=0: raise ValueError('invalid credit amount')
        db=self.conn; await db.execute('BEGIN IMMEDIATE')
        try:
            cur=await db.execute('SELECT discord_id,credited,status,txids,verified_amount,requested_amount FROM deposits WHERE invoice_id=?',(invoice,)); row=await cur.fetchone()
            if not row: raise ValueError('unknown invoice')
            if row['credited']: await db.rollback(); return False
            if (row['status'] != 'completed' or int(row['verified_amount']) != int(row['requested_amount'])
                    or txid not in json.loads(row['txids'])): raise ValueError('deposit is not verified as completed with exact amount')
            if self.maintenance_mode: raise ValueError('maintenance mode blocks wallet credits until service resumes')
            uid=row['discord_id']; await db.execute('UPDATE deposits SET credited=1,status=\'completed\',updated_at=CURRENT_TIMESTAMP WHERE invoice_id=? AND credited=0',(invoice,))
            await db.execute('UPDATE users SET balance=balance+? WHERE discord_id=?',(amount,uid)); cur=await db.execute('SELECT balance FROM users WHERE discord_id=?',(uid,)); bal=int((await cur.fetchone())['balance'])
            await db.execute('INSERT INTO transactions(discord_id,kind,amount,balance_after,reference,detail) VALUES(?,?,?,?,?,?)',(uid,'deposit',amount,bal,'deposit:'+invoice,(detail or 'Verified Apirone tx '+txid[:32])[:500])); await db.commit(); return True
        except: await db.rollback(); raise
    @serialized
    async def start_game(self,uid,game,bet,daily_limit=0):
        if type(bet) is not int or bet < self.min_bet or (self.max_bet and bet > self.max_bet): raise ValueError(f'Bet must be at least {self.min_bet:,} VC' + (f' and at most {self.max_bet:,} VC.' if self.max_bet else '.'))
        sid=str(uuid.uuid4()); db=self.conn; await db.execute('BEGIN IMMEDIATE')
        try:
            if self.maintenance_mode: raise ValueError('Casino maintenance is active; new wagers are paused.')
            await db.execute('INSERT OR IGNORE INTO users(discord_id) VALUES(?)',(uid,))
            control=await db.execute('SELECT daily_limit,excluded_until FROM player_controls WHERE discord_id=?',(uid,)); ctl=await control.fetchone()
            if ctl and ctl['excluded_until'] and int(ctl['excluded_until'])>int(__import__('time').time()): raise ValueError('You are currently self-excluded from play.')
            cap=daily_limit
            if ctl and ctl['daily_limit'] is not None: cap=min(cap,ctl['daily_limit']) if cap else ctl['daily_limit']
            if cap:
                total=await db.execute("SELECT COALESCE(SUM(-amount),0) AS wagered FROM transactions WHERE discord_id=? AND kind='game_bet' AND date(created_at)=date('now')",(uid,)); wagered=int((await total.fetchone())['wagered'])
                if wagered+bet>cap: raise ValueError(f'Daily wager limit reached ({cap:,} VC).')
            active=await db.execute('SELECT 1 FROM game_sessions WHERE discord_id=? AND settled=0 LIMIT 1',(uid,))
            if await active.fetchone(): raise ValueError('an active game session already exists')
            cur=await db.execute('UPDATE users SET balance=balance-? WHERE discord_id=? AND balance>=?',(bet,uid,bet))
            if cur.rowcount!=1: raise ValueError('insufficient funds')
            cur=await db.execute('SELECT balance FROM users WHERE discord_id=?',(uid,)); bal=int((await cur.fetchone())['balance'])
            await db.execute('INSERT INTO game_sessions(id,discord_id,game,bet,state,session_max_payout,session_max_bet,session_daily_limit) VALUES(?,?,?,?,?,?,?,?)',(sid,uid,game,bet,'active',self.max_payout,self.max_bet,daily_limit or self.daily_bet_limit))
            await db.execute('INSERT INTO transactions(discord_id,kind,amount,balance_after,reference,detail) VALUES(?,?,?,?,?,?)',(uid,'game_bet',-bet,bal,'bet:'+sid,game)); await db.commit()
            if self.event_logger:self.event_logger.emit('bet','Wager placed',user_id=uid,game=game,round_id=sid,amount=bet,reference='bet:'+sid)
            return sid
        except: await db.rollback(); raise
    @serialized
    async def finish_game(self,sid,payout,outcome=None):
        if type(payout) is not int or payout<0: raise ValueError('payout must be a nonnegative integer')
        db=self.conn; await db.execute('BEGIN IMMEDIATE')
        try:
            cur=await db.execute('SELECT discord_id,settled,fair_round_id,session_max_payout,bet,game FROM game_sessions WHERE id=?',(sid,)); row=await cur.fetchone()
            if not row: raise ValueError('unknown game session')
            if row['settled']: await db.rollback(); return False
            if payout>int(row['session_max_payout'] or self.max_payout): raise ValueError('payout exceeds this round’s configured cap')
            await db.execute("UPDATE game_sessions SET settled=1,state='settled' WHERE id=? AND settled=0",(sid,))
            if row['fair_round_id']:
                cur=await db.execute('UPDATE fair_rounds SET settled=1,outcome=? WHERE id=? AND settled=0',(str(outcome or 'settled')[:10000],row['fair_round_id']))
                if cur.rowcount != 1: raise ValueError('linked fairness round is missing or already settled')
                await db.execute('UPDATE fair_seeds SET revealed_at=? WHERE retired_at IS NOT NULL AND revealed_at IS NULL AND NOT EXISTS (SELECT 1 FROM fair_rounds WHERE seed_id=fair_seeds.id AND settled=0)',(int(time.time()),))
            if payout:
                await db.execute('UPDATE users SET balance=balance+? WHERE discord_id=?',(payout,row['discord_id'])); cur=await db.execute('SELECT balance FROM users WHERE discord_id=?',(row['discord_id'],)); bal=int((await cur.fetchone())['balance'])
                await db.execute('INSERT INTO transactions(discord_id,kind,amount,balance_after,reference,detail) VALUES(?,?,?,?,?,?)',(row['discord_id'],'game_payout',payout,bal,'payout:'+sid,'game'))
            await db.commit()
            if self.event_logger:self.event_logger.emit('bet','Wager settled',user_id=row['discord_id'],game=row['game'],round_id=sid,bet=row['bet'],payout=payout,reference='settle:'+sid)
            if payout>int(row['bet']) and self.event_logger:self.event_logger.emit('wins','Verified game payout',user_id=row['discord_id'],game=row['game'],round_id=sid,bet=row['bet'],payout=payout,reference='win:'+sid)
            elif payout<int(row['bet']) and self.event_logger:self.event_logger.emit('loss','Game loss settled',user_id=row['discord_id'],game=row['game'],round_id=sid,bet=row['bet'],payout=payout,reference='loss:'+sid)
            return True
        except: await db.rollback(); raise
    @serialized
    async def refund_game(self,sid,reason='refunded before play'):
        """Return an unsettled setup wager exactly once with a ledger reference."""
        db=self.conn; await db.execute('BEGIN IMMEDIATE')
        try:
            cur=await db.execute('SELECT discord_id,bet,settled,fair_round_id,game FROM game_sessions WHERE id=?',(sid,)); row=await cur.fetchone()
            if not row: raise ValueError('unknown game session')
            if row['settled']: await db.rollback(); return False
            await db.execute("UPDATE game_sessions SET settled=1,state='refunded' WHERE id=? AND settled=0",(sid,))
            await db.execute('UPDATE users SET balance=balance+? WHERE discord_id=?',(row['bet'],row['discord_id']))
            cur=await db.execute('SELECT balance FROM users WHERE discord_id=?',(row['discord_id'],)); bal=int((await cur.fetchone())['balance'])
            await db.execute('INSERT INTO transactions(discord_id,kind,amount,balance_after,reference,detail) VALUES(?,?,?,?,?,?)',(row['discord_id'],'game_refund',row['bet'],bal,'refund:'+sid,str(reason)[:180]))
            if row['fair_round_id']:
                cur=await db.execute('UPDATE fair_rounds SET settled=1,outcome=? WHERE id=? AND settled=0',(reason,row['fair_round_id']))
                if cur.rowcount != 1: raise ValueError('linked fairness round is missing or already settled')
                await db.execute('UPDATE fair_seeds SET revealed_at=? WHERE retired_at IS NOT NULL AND revealed_at IS NULL AND NOT EXISTS (SELECT 1 FROM fair_rounds WHERE seed_id=fair_seeds.id AND settled=0)',(int(time.time()),))
            await db.commit()
            if self.event_logger:self.event_logger.emit('bet','Wager refunded',user_id=row['discord_id'],game=row['game'],round_id=sid,amount=row['bet'],reason=reason,reference='refund:'+sid)
            return True
        except: await db.rollback(); raise

    @serialized
    async def recover_games(self):
        db=self.conn; await db.execute('BEGIN IMMEDIATE')
        try:
            cur=await db.execute('SELECT id,discord_id,bet,game,fair_round_id FROM game_sessions WHERE settled=0'); rows=await cur.fetchall()
            for r in rows:
                await db.execute('UPDATE users SET balance=balance+? WHERE discord_id=?',(r['bet'],r['discord_id'])); cur=await db.execute('SELECT balance FROM users WHERE discord_id=?',(r['discord_id'],)); bal=int((await cur.fetchone())['balance'])
                await db.execute('INSERT OR IGNORE INTO transactions(discord_id,kind,amount,balance_after,reference,detail) VALUES(?,?,?,?,?,?)',(r['discord_id'],'game_refund',r['bet'],bal,'refund:'+r['id'],'Refund after restart'))
                await db.execute("UPDATE game_sessions SET settled=1,state='recovered' WHERE id=?",(r['id'],))
                if r['fair_round_id']:
                    await db.execute("UPDATE fair_rounds SET settled=1,outcome='refunded after restart' WHERE id=? AND settled=0",(r['fair_round_id'],))
            # A round allocated before its game session was attached never took a wager.
            # Close it as a pre-play refund so it cannot pin an old seed indefinitely.
            await db.execute("UPDATE fair_rounds SET settled=1,outcome='refunded before play' WHERE settled=0 AND NOT EXISTS (SELECT 1 FROM game_sessions WHERE game_sessions.fair_round_id=fair_rounds.id AND game_sessions.settled=0)")
            await db.execute('UPDATE fair_seeds SET revealed_at=? WHERE retired_at IS NOT NULL AND revealed_at IS NULL AND NOT EXISTS (SELECT 1 FROM fair_rounds WHERE seed_id=fair_seeds.id AND settled=0)',(int(time.time()),))
            await db.commit()
            return [dict(r) for r in rows]
        except: await db.rollback(); raise
    @serialized
    async def pending_deposits(self,limit=30):
        cur=await self.conn.execute("SELECT invoice_id FROM deposits WHERE credited=0 AND status!='failed' ORDER BY updated_at LIMIT ?",(limit,)); return [r['invoice_id'] for r in await cur.fetchall()]

    @serialized
    async def start_extra_bet(self,sid,uid,amount,daily_limit=0):
        if type(amount) is not int or amount<self.min_bet: raise ValueError('invalid additional wager')
        db=self.conn; await db.execute('BEGIN IMMEDIATE')
        try:
            if self.maintenance_mode: raise ValueError('Casino maintenance is active; additional wagers are paused.')
            sess=await db.execute('SELECT bet,session_max_bet,session_daily_limit FROM game_sessions WHERE id=? AND discord_id=? AND settled=0',(sid,uid)); active=await sess.fetchone()
            if not active: raise ValueError('game session is no longer active')
            round_cap=int(active['session_max_bet'])
            if round_cap and int(active['bet'])+amount>round_cap: raise ValueError('Double down would exceed the per-round wager limit.')
            control=await db.execute('SELECT daily_limit,excluded_until FROM player_controls WHERE discord_id=?',(uid,)); ctl=await control.fetchone()
            if ctl and ctl['excluded_until'] and int(ctl['excluded_until'])>int(__import__('time').time()): raise ValueError('You are currently self-excluded from play.')
            round_daily=int(active['session_daily_limit'] or daily_limit)
            cap=min(round_daily,ctl['daily_limit']) if ctl and ctl['daily_limit'] is not None else round_daily
            total=await db.execute("SELECT COALESCE(SUM(-amount),0) AS wagered FROM transactions WHERE discord_id=? AND kind='game_bet' AND date(created_at)=date('now')",(uid,)); wagered=int((await total.fetchone())['wagered'])
            if cap and wagered+amount>cap: raise ValueError('Daily wager limit reached.')
            cur=await db.execute('UPDATE users SET balance=balance-? WHERE discord_id=? AND balance>=?',(amount,uid,amount))
            if cur.rowcount!=1: raise ValueError('insufficient funds')
            cur=await db.execute('SELECT balance FROM users WHERE discord_id=?',(uid,)); bal=int((await cur.fetchone())['balance'])
            cur=await db.execute('UPDATE game_sessions SET bet=bet+? WHERE id=? AND discord_id=? AND settled=0',(amount,sid,uid))
            if cur.rowcount!=1: raise ValueError('game session is no longer active')
            await db.execute('INSERT INTO transactions(discord_id,kind,amount,balance_after,reference,detail) VALUES(?,?,?,?,?,?)',(uid,'game_bet',-amount,bal,'double:'+sid,'blackjack double'))
            await db.commit()
            if self.event_logger:self.event_logger.emit('bet','Additional wager placed',user_id=uid,game='blackjack',round_id=sid,amount=amount,reference='double:'+sid)
        except: await db.rollback(); raise

    @serialized
    async def set_daily_limit(self,uid,limit):
        await self.conn.execute('INSERT OR IGNORE INTO users(discord_id) VALUES(?)',(uid,))
        await self.conn.execute('INSERT INTO player_controls(discord_id,daily_limit) VALUES(?,?) ON CONFLICT(discord_id) DO UPDATE SET daily_limit=excluded.daily_limit',(uid,limit)); await self.conn.commit()
    @serialized
    async def self_exclude(self,uid,days):
        if not 1<=days<=365: raise ValueError('self-exclusion must be 1 to 365 days')
        import time
        await self.conn.execute('INSERT OR IGNORE INTO users(discord_id) VALUES(?)',(uid,))
        until=int(time.time())+days*86400
        await self.conn.execute('INSERT INTO player_controls(discord_id,excluded_until) VALUES(?,?) ON CONFLICT(discord_id) DO UPDATE SET excluded_until=MAX(COALESCE(player_controls.excluded_until,0),excluded.excluded_until)',(uid,until)); await self.conn.commit(); cur=await self.conn.execute('SELECT excluded_until FROM player_controls WHERE discord_id=?',(uid,)); return int((await cur.fetchone())['excluded_until'])
    @serialized
    async def daily_claim(self,uid,amount,now=None):
        if type(amount) is not int or amount<=0: raise ValueError('Daily reward is disabled or invalid.')
        now=int(time.time()) if now is None else int(now)
        db=self.conn; await db.execute('BEGIN IMMEDIATE')
        try:
            if self.maintenance_mode: raise ValueError('Casino maintenance is active; daily rewards are paused.')
            await db.execute('INSERT OR IGNORE INTO users(discord_id) VALUES(?)',(uid,))
            cur=await db.execute('SELECT claimed_at FROM daily_claims WHERE discord_id=?',(uid,)); previous=await cur.fetchone()
            if previous and now-int(previous['claimed_at'])<86400:
                remaining=86400-max(0,now-int(previous['claimed_at']))
                raise ValueError(f'Daily reward is on cooldown; try again in {remaining} seconds.')
            await db.execute('INSERT INTO daily_claims(discord_id,claimed_at,amount) VALUES(?,?,?) ON CONFLICT(discord_id) DO UPDATE SET claimed_at=excluded.claimed_at,amount=excluded.amount',(uid,now,amount))
            await db.execute('UPDATE users SET balance=balance+? WHERE discord_id=?',(amount,uid))
            cur=await db.execute('SELECT balance FROM users WHERE discord_id=?',(uid,)); balance=int((await cur.fetchone())['balance'])
            await db.execute('INSERT INTO transactions(discord_id,kind,amount,balance_after,reference,detail) VALUES(?,?,?,?,?,?)',(uid,'daily_reward',amount,balance,f'daily:{uid}:{now}','24-hour claim'))
            await db.commit()
            if self.event_logger:self.event_logger.emit('wallet','Daily reward claimed',user_id=uid,amount=amount,reference=f'daily:{uid}:{now}')
            return {'amount':amount,'balance':balance,'next_claim_at':now+86400}
        except: await db.rollback(); raise

    @serialized
    async def daily_claim_status(self,uid,now=None):
        now=int(time.time()) if now is None else int(now)
        cur=await self.conn.execute('SELECT claimed_at FROM daily_claims WHERE discord_id=?',(uid,)); row=await cur.fetchone()
        if not row or now-int(row['claimed_at'])>=86400:return 0
        return max(0,86400-(now-int(row['claimed_at'])))

    @serialized
    async def player_game_stats(self,uid):
        sql="""SELECT COUNT(*) AS rounds,
          COALESCE(SUM(CASE WHEN COALESCE((SELECT amount FROM transactions WHERE reference='payout:'||gs.id),0)>gs.bet THEN 1 ELSE 0 END),0) AS wins,
          COALESCE(SUM(COALESCE((SELECT amount FROM transactions WHERE reference='payout:'||gs.id),0)-gs.bet),0) AS net
          FROM game_sessions gs WHERE gs.discord_id=? AND gs.settled=1 AND gs.state='settled'"""
        cur=await self.conn.execute(sql,(uid,));return await cur.fetchone()

    @serialized
    async def leaderboard(self,limit=10):
        sql="""SELECT gs.discord_id,
          SUM(COALESCE((SELECT amount FROM transactions WHERE reference='payout:'||gs.id),0)-gs.bet) AS net,
          SUM(CASE WHEN COALESCE((SELECT amount FROM transactions WHERE reference='payout:'||gs.id),0)>gs.bet THEN 1 ELSE 0 END) AS wins,
          COUNT(*) AS rounds
          FROM game_sessions gs WHERE gs.settled=1 AND gs.state='settled'
          GROUP BY gs.discord_id ORDER BY net DESC, wins DESC, rounds DESC LIMIT ?"""
        cur=await self.conn.execute(sql,(max(1,min(int(limit),25)),))
        return await cur.fetchall()

    @serialized
    async def play_controls(self,uid):
        cur=await self.conn.execute('SELECT daily_limit,excluded_until FROM player_controls WHERE discord_id=?',(uid,)); return await cur.fetchone()

    @serialized
    async def daily_wagered(self,uid):
        cur=await self.conn.execute("SELECT COALESCE(SUM(-amount),0) AS wagered FROM transactions WHERE discord_id=? AND kind='game_bet' AND date(created_at)=date('now')",(uid,)); return int((await cur.fetchone())['wagered'])

    @serialized
    async def reconcile_balances(self):
        """Return ledger discrepancies without mutating balances."""
        cur=await self.conn.execute('''SELECT u.discord_id,u.balance,COALESCE(SUM(t.amount),0) AS ledger
          FROM users u LEFT JOIN transactions t ON t.discord_id=u.discord_id
          GROUP BY u.discord_id HAVING u.balance != COALESCE(SUM(t.amount),0)''')
        return await cur.fetchall()

    @serialized
    async def allocate_fair_round(self,uid,game,client_seed,rotation_seconds):
        now=int(time.time()); db=self.conn; await db.execute('BEGIN IMMEDIATE')
        try:
            await db.execute('INSERT OR IGNORE INTO users(discord_id) VALUES(?)',(uid,))
            cur=await db.execute('SELECT * FROM fair_seeds WHERE retired_at IS NULL ORDER BY id DESC LIMIT 1'); seed=await cur.fetchone()
            if seed is None:
                raw=secrets.token_hex(32); commitment=hashlib.sha256(raw.encode()).hexdigest()
                await db.execute('INSERT INTO fair_seeds(commitment,server_seed,created_at) VALUES(?,?,?)',(commitment,raw,now))
                cur=await db.execute('SELECT * FROM fair_seeds WHERE commitment=?',(commitment,)); seed=await cur.fetchone()
            cur=await db.execute('SELECT COALESCE(MAX(nonce),0)+1 AS n FROM fair_rounds WHERE seed_id=?',(seed['id'],)); nonce=int((await cur.fetchone())['n'])
            round_id=str(uuid.uuid4()); msg=f'{client_seed}:{nonce}:{game}'.encode(); result=hmac.new(seed['server_seed'].encode(),msg,hashlib.sha256).hexdigest()
            await db.execute('INSERT INTO fair_rounds(id,seed_id,discord_id,game,client_seed,nonce,result_digest,created_at) VALUES(?,?,?,?,?,?,?,?)',(round_id,seed['id'],uid,game,client_seed,nonce,result,now))
            await db.execute('INSERT OR IGNORE INTO users(discord_id) VALUES(?)',(uid,))
            await db.execute('UPDATE fair_seeds SET revealed_at=? WHERE retired_at IS NOT NULL AND revealed_at IS NULL AND NOT EXISTS (SELECT 1 FROM fair_rounds WHERE seed_id=fair_seeds.id AND settled=0)',(now,))
            await db.commit(); return {'round_id':round_id,'seed_id':seed['id'],'commitment':seed['commitment'],'nonce':nonce,'digest':result,'client_seed':client_seed}
        except: await db.rollback(); raise

    @serialized
    async def settle_fair_round(self,round_id,outcome):
        db=self.conn; await db.execute('BEGIN IMMEDIATE')
        try:
            cur=await db.execute('UPDATE fair_rounds SET settled=1,outcome=? WHERE id=? AND settled=0',(str(outcome)[:10000],round_id))
            if cur.rowcount != 1: raise ValueError('fairness round missing or already settled')
            await db.execute('UPDATE fair_seeds SET revealed_at=? WHERE retired_at IS NOT NULL AND revealed_at IS NULL AND NOT EXISTS (SELECT 1 FROM fair_rounds WHERE seed_id=fair_seeds.id AND settled=0)',(int(time.time()),))
            await db.commit()
        except: await db.rollback(); raise

    @serialized
    async def fair_round(self,round_id):
        cur=await self.conn.execute('SELECT r.*,s.commitment,s.server_seed AS revealed_seed,s.revealed_at FROM fair_rounds r JOIN fair_seeds s ON s.id=r.seed_id WHERE r.id=? AND s.revealed_at IS NOT NULL',(round_id,)); return await cur.fetchone()

    @serialized
    async def pending_fair_reveals(self):
        cur=await self.conn.execute('SELECT id,commitment,server_seed,revealed_at FROM fair_seeds WHERE revealed_at IS NOT NULL AND revealed_published_at IS NULL ORDER BY id')
        return await cur.fetchall()

    @serialized
    async def mark_fair_reveal_published(self,seed_id):
        await self.conn.execute('UPDATE fair_seeds SET revealed_published_at=? WHERE id=? AND revealed_at IS NOT NULL AND revealed_published_at IS NULL',(int(time.time()),seed_id))
        await self.conn.commit()

    @serialized
    async def audit_admin(self,admin_id,action,details):
        await self.conn.execute('INSERT INTO admin_audit(admin_id,action,details) VALUES(?,?,?)',(admin_id,action,str(details)[:1000])); await self.conn.commit()

    @serialized
    async def set_config(self,key,value,admin_id):
        await self.conn.execute('INSERT INTO app_config(key,value,updated_by) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_by=excluded.updated_by,updated_at=CURRENT_TIMESTAMP',(key,str(value),admin_id))
        await self.conn.execute('INSERT INTO admin_audit(admin_id,action,details) VALUES(?,?,?)',(admin_id,'config:'+key,str(value)[:500])); await self.conn.commit()

    @serialized
    async def set_configs(self,values,admin_id,action='configuration_update'):
        if not isinstance(values,dict) or not values: raise ValueError('configuration values must be a nonempty mapping')
        db=self.conn; await db.execute('BEGIN IMMEDIATE')
        try:
            for key,value in values.items():
                await db.execute('INSERT INTO app_config(key,value,updated_by) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_by=excluded.updated_by,updated_at=CURRENT_TIMESTAMP',(str(key),str(value),admin_id))
            keys=','.join(sorted(str(key) for key in values))[:500]
            await db.execute('INSERT INTO admin_audit(admin_id,action,details) VALUES(?,?,?)',(admin_id,action,'keys='+keys))
            await db.commit()
        except: await db.rollback(); raise

    @serialized
    async def get_config(self,key,default=None):
        cur=await self.conn.execute('SELECT value FROM app_config WHERE key=?',(key,)); row=await cur.fetchone(); return row['value'] if row else default

    @serialized
    async def attach_fair_round(self,sid,round_id):
        db=self.conn; await db.execute('BEGIN IMMEDIATE')
        try:
            sess=await db.execute('SELECT discord_id,game,fair_round_id,settled FROM game_sessions WHERE id=?',(sid,)); session=await sess.fetchone()
            fair=await db.execute('SELECT discord_id,game,settled FROM fair_rounds WHERE id=?',(round_id,)); record=await fair.fetchone()
            if not session or not record or session['settled'] or session['fair_round_id'] or record['settled'] or int(session['discord_id'])!=int(record['discord_id']) or session['game']!=record['game']:
                raise ValueError('fairness record does not match this active game session')
            await db.execute('UPDATE game_sessions SET fair_round_id=? WHERE id=? AND settled=0',(round_id,sid))
            await db.commit()
        except: await db.rollback(); raise

    @serialized
    async def rotate_fair_seed(self,rotation_seconds,force=False):
        now=int(time.time()); db=self.conn; await db.execute('BEGIN IMMEDIATE')
        try:
            cur=await db.execute('SELECT * FROM fair_seeds WHERE retired_at IS NULL ORDER BY id DESC LIMIT 1'); active=await cur.fetchone()
            if active and not force and now-int(active['created_at'])<rotation_seconds:
                await db.rollback(); return {'commitment':active['commitment'],'created':False}
            if active: await db.execute('UPDATE fair_seeds SET retired_at=? WHERE id=?',(now,active['id']))
            raw=secrets.token_hex(32); comm=hashlib.sha256(raw.encode()).hexdigest()
            await db.execute('INSERT INTO fair_seeds(commitment,server_seed,created_at) VALUES(?,?,?)',(comm,raw,now))
            await db.execute('UPDATE fair_seeds SET revealed_at=? WHERE retired_at IS NOT NULL AND revealed_at IS NULL AND NOT EXISTS (SELECT 1 FROM fair_rounds WHERE seed_id=fair_seeds.id AND settled=0)',(now,))
            await db.commit(); return {'commitment':comm,'created':True}
        except: await db.rollback(); raise
