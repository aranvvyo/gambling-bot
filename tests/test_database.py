import asyncio
import pytest
from database.db import Database

@pytest.mark.asyncio
async def test_atomic_concurrent_bets_and_no_negative(tmp_path):
 db=await Database(f"sqlite:///{tmp_path/'db.sqlite'}").open()
 await db.change_balance(7,100,"test", "seed")
 async def bet(i):
  try:return await db.change_balance(7,-80,"bet",f"b{i}")
  except ValueError:return "rejected"
 out=await asyncio.gather(bet(1),bet(2))
 assert out.count("rejected")==1
 assert await db.balance(7)==20
 await db.close()

@pytest.mark.asyncio
async def test_deposit_credit_is_idempotent(tmp_path):
 db=await Database(f"sqlite:///{tmp_path/'db.sqlite'}").open()
 await db.create_deposit({"invoice":"inv-1","discord_id":9,"currency":"usdt@eth","requested_amount":"5000000","address":"0xabc","status":"created"})
 await db.update_deposit('inv-1','completed',['tx-1'],5_000_000)
 assert await db.credit_deposit("inv-1",5,"tx-1") is True
 assert await db.credit_deposit("inv-1",5,"tx-1") is False
 assert await db.balance(9)==5
 await db.close()

@pytest.mark.asyncio
async def test_restart_refunds_unsettled_game(tmp_path):
 db=await Database(f"sqlite:///{tmp_path/'db.sqlite'}").open()
 await db.change_balance(2,100,"test","seed")
 await db.start_game(2,"test",30)
 assert await db.balance(2)==70
 await db.recover_games()
 assert await db.balance(2)==100
 await db.close()

@pytest.mark.asyncio
async def test_restart_settles_fairness_round_before_seed_reveal(tmp_path):
 from services.fairness import FairnessService
 db=await Database(f"sqlite:///{tmp_path/'recover-fair.db'}").open()
 await db.change_balance(41,50,'seed','seed:41')
 sid=await db.start_game(41,'chicken-road',10)
 fair=await FairnessService(db,60).allocate(41,'chicken-road')
 await db.attach_fair_round(sid,fair['round_id'])
 await db.conn.execute('UPDATE fair_seeds SET created_at=1'); await db.conn.commit()
 await FairnessService(db,60).ensure_commitment()
 assert await FairnessService(db,60).verify(fair['round_id']) is None
 await db.recover_games()
 verified=await FairnessService(db,60).verify(fair['round_id'])
 assert verified and verified['valid'] and verified['outcome']=='refunded after restart'
 assert await db.balance(41)==50
 await db.close()

@pytest.mark.asyncio
async def test_existing_schema_migrates_without_losing_wallet_data(tmp_path):
 import aiosqlite
 path=tmp_path/'existing.sqlite'
 async with aiosqlite.connect(path) as c:
  await c.executescript("CREATE TABLE users(discord_id INTEGER PRIMARY KEY,balance INTEGER NOT NULL DEFAULT 0 CHECK(balance>=0),created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP); INSERT INTO users(discord_id,balance) VALUES(701,1234); CREATE TABLE deposits(invoice_id TEXT PRIMARY KEY,discord_id INTEGER NOT NULL REFERENCES users(discord_id),currency TEXT NOT NULL,requested_amount TEXT NOT NULL,address TEXT NOT NULL,status TEXT NOT NULL,txids TEXT NOT NULL DEFAULT '[]',credited INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP); INSERT INTO deposits(invoice_id,discord_id,currency,requested_amount,address,status) VALUES('old-invoice',701,'ltc','100000000','L-old','created'); CREATE TABLE game_sessions(id TEXT PRIMARY KEY,discord_id INTEGER NOT NULL REFERENCES users(discord_id),game TEXT NOT NULL,bet INTEGER NOT NULL CHECK(bet>0),state TEXT NOT NULL,settled INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);")
 db=await Database(f'sqlite:///{path}').open()
 assert await db.balance(701)==1234
 dep=await db.deposit('old-invoice')
 assert dep['requested_amount']=='100000000' and dep['address']=='L-old' and dep['verified_amount']==0
 cols=await db.conn.execute('PRAGMA table_info(game_sessions)')
 assert 'fair_round_id' in {r['name'] for r in await cols.fetchall()}
 versions=await db.conn.execute('SELECT version FROM schema_migrations ORDER BY version')
 assert len(await versions.fetchall())==6
 await db.close()

@pytest.mark.asyncio
async def test_financial_and_admin_ledgers_are_append_only(tmp_path):
 db=await Database(f"sqlite:///{tmp_path/'append.db'}").open()
 await db.change_balance(3,10,'seed','seed:3')
 with pytest.raises(Exception,match='append-only'):
  await db.conn.execute("UPDATE transactions SET detail='changed' WHERE reference='seed:3'")
 with pytest.raises(Exception,match='append-only'):
  await db.conn.execute("DELETE FROM transactions WHERE reference='seed:3'")
 await db.conn.rollback(); await db.close()

@pytest.mark.asyncio
async def test_unverified_deposit_cannot_be_credited_directly(tmp_path):
 db=await Database(f"sqlite:///{tmp_path/'unverified.sqlite'}").open()
 await db.create_deposit({"invoice":"unverified","discord_id":9,"currency":"ltc","requested_amount":"100","address":"ltc-address","status":"created"})
 with pytest.raises(ValueError,match='not verified'):
  await db.credit_deposit('unverified',100,'a'*64)
 assert await db.balance(9)==0
 await db.close()

@pytest.mark.asyncio
async def test_ledger_mutations_require_unique_references(tmp_path):
 db=await Database(f"sqlite:///{tmp_path/'refs.sqlite'}").open()
 with pytest.raises(ValueError,match='reference'):
  await db.change_balance(11,20,'seed')
 await db.close()

@pytest.mark.asyncio
async def test_database_file_permissions_are_private(tmp_path):
 import os,stat
 path=tmp_path/'private.sqlite'
 db=await Database(f'sqlite:///{path}').open()
 assert stat.S_IMODE(os.stat(path).st_mode)==0o600
 await db.close()
