"""Adversarial release regression tests using simulated funds and isolated databases."""
import asyncio
import json
from decimal import Decimal

import pytest

from database.db import Database
from games.math import chicken_multiplier, chicken_safe_tile, dice_result, pump_crash_point
from services.fairness import (
    FairnessService, crash_point, derive_deck, derive_int, digest,
    mines_layout, safe_path, verify_game_outcome,
)
from services.game_math import (
    blackjack_return, blackjack_value, limo_multiplier, mines_multiplier,
    payout, tower_multiplier,
)


def test_revealed_digest_verifies_all_game_outcome_records():
    d = '6b' * 32
    # Dice.
    roll, won, mult, _ = dice_result(d, 'under', 50, Decimal('.01'))
    rec = {'algorithm':'casino-v1','direction':'under','target':50,'edge':'.01','roll':roll,'won':won,'bet':20,'cap':10000,'payout':payout(20,mult,10000) if won else 0}
    assert verify_game_outcome('dice',d,json.dumps(rec))
    rec['roll'] = (roll + 1) % 100
    assert not verify_game_outcome('dice',d,json.dumps(rec))

    # Mines, tower, road, pump, Limo, Limbo, and Crash use recorded deterministic parameters.
    layout = mines_layout(d,16,3)
    assert verify_game_outcome('mines',d,json.dumps({'algorithm':'casino-v1','tiles':16,'mines':3,'layout':layout,'opened':[],'payout':0,'title':'timeout','bet':20,'edge':'.01','cap':10000}))
    path = safe_path(d,5,2)
    assert verify_game_outcome('dragon_tower',d,json.dumps({'algorithm':'casino-v1','steps_total':5,'choices':2,'safe_path':path,'chosen_path':[],'steps':0,'payout':0,'title':'timeout','bet':20,'edge':'.01','cap':10000}))
    chicken = [chicken_safe_tile(d,i) for i in range(5)]
    assert verify_game_outcome('chicken-road',d,json.dumps({'algorithm':'casino-v1','steps_total':5,'choices':3,'safe_path':chicken,'chosen_path':[],'steps':0,'payout':0,'reason':'expired without cashout','bet':20,'edge':'.01','cap':10000}))
    point = pump_crash_point(d,Decimal('.01'),Decimal(100))
    mult = Decimal('1.00')
    pump_payout = payout(20,mult,10000) if point > mult else 0
    assert verify_game_outcome('pump',d,json.dumps({'algorithm':'casino-v1','point':str(point),'edge':'.01','cap':'100','payout':pump_payout,'reason':'Cashed out','bet':20,'multiplier':str(mult),'attempted':None}))
    winner = derive_int(d,'limo-car',3)
    limo_pay = payout(20,limo_multiplier(3),10000)
    assert verify_game_outcome('limo',d,json.dumps({'algorithm':'casino-v1','cars':3,'winner':winner,'chosen':winner,'payout':limo_pay,'bet':20,'edge':'.01','cap':10000}))
    u = Decimal(int(d[:13],16))/Decimal(16**13)
    limbo_roll = (Decimal(1)/max(u,Decimal(1)/Decimal(16**13))).quantize(Decimal('.01'))
    target = Decimal('1.50'); limbo_won = limbo_roll >= target
    limbo_pay = payout(20,target*Decimal('.99'),10000) if limbo_won else 0
    assert verify_game_outcome('limbo',d,json.dumps({'algorithm':'casino-v1','roll':str(limbo_roll),'target':str(target),'won':limbo_won,'payout':limbo_pay,'bet':20,'edge':'.01','cap':10000}))
    crash = crash_point(d,.01)
    assert verify_game_outcome('crash',d,json.dumps({'algorithm':'casino-v1','point':crash,'edge':'.01','payout':0,'reason':'crash','multiplier':None,'auto_cashout':None,'bet':20,'cap':10000}))
    deck = derive_deck(d); player, dealer = deck[:2], deck[2:4]
    blackjack_pay = blackjack_return(20,blackjack_value(player),blackjack_value(dealer),len(player)==2 and blackjack_value(player)==21,len(dealer)==2 and blackjack_value(dealer)==21,10000)
    record={'algorithm':'casino-v1','dealt':deck[:4],'player':player,'dealer':dealer,'bet':20,'payout':blackjack_pay,'cap':10000,'reason':'stand'}
    assert verify_game_outcome('blackjack',d,json.dumps(record))
    # Preserve the same cards and payout but forge who received a dealt card.
    forged={**record,'player':[deck[0],deck[2]],'dealer':[deck[1],deck[3]]}
    assert not verify_game_outcome('blackjack',d,json.dumps(forged))


def test_deterministic_nonces_and_seed_commitment():
    one = digest('server', 'client', 1, 'mines')
    two = digest('server', 'client', 2, 'mines')
    assert one == digest('server', 'client', 1, 'mines')
    assert one != two
    assert derive_int(one,'tile',25) != derive_int(two,'tile',25)


@pytest.mark.asyncio
async def test_parallel_nonce_allocation_never_reuses_a_nonce(tmp_path):
    db = await Database(f"sqlite:///{tmp_path/'nonce.sqlite'}").open()
    fairness = FairnessService(db,60)
    rounds = await asyncio.gather(*(fairness.allocate(100+i,'dice',f'client-{i}') for i in range(20)))
    assert len({r['nonce'] for r in rounds}) == 20
    assert {r['nonce'] for r in rounds} == set(range(1,21))
    await db.close()


@pytest.mark.asyncio
async def test_restart_refunds_only_the_linked_round_and_reveals_seed_after_all_settle(tmp_path):
    db = await Database(f"sqlite:///{tmp_path/'linked-recovery.sqlite'}").open()
    await db.change_balance(7,100,'test-credit','test:7')
    sid = await db.start_game(7,'mines',20)
    fair = FairnessService(db,60)
    linked = await fair.allocate(7,'mines')
    orphan = await fair.allocate(7,'limo')
    await db.attach_fair_round(sid,linked['round_id'])
    await db.conn.execute('UPDATE fair_seeds SET created_at=1'); await db.conn.commit()
    await fair.ensure_commitment()
    await db.recover_games()
    verified = await fair.verify(linked['round_id'])
    assert verified and verified['valid'] and verified['outcome']=='refunded after restart'
    pending = await db.conn.execute('SELECT settled FROM fair_rounds WHERE id=?',(orphan['round_id'],))
    assert (await pending.fetchone())['settled'] == 1
    assert (await fair.verify(orphan['round_id']))['valid']
    assert (await fair.verify(orphan['round_id']))['outcome'] == 'refunded before play'
    assert await db.balance(7)==100
    await db.close()


@pytest.mark.asyncio
async def test_parallel_settlement_credits_once_and_ledger_reconciles(tmp_path):
    db = await Database(f"sqlite:///{tmp_path/'settle.sqlite'}").open()
    await db.change_balance(44,100,'test-credit','test:44')
    sid = await db.start_game(44,'dice',30)
    results = await asyncio.gather(*(db.finish_game(sid,60,'test settlement') for _ in range(12)))
    assert results.count(True)==1
    assert await db.balance(44)==130
    assert await db.reconcile_balances()==[]
    await db.close()

@pytest.mark.asyncio
async def test_game_view_timeout_settles_once_and_old_interactions_cannot_be_replayed(tmp_path):
 from cogs.mines import MinesView
 class Bot:
  def __init__(self,db): self.db=db; self.active_users={88}; self.settings=type('S',(),{'house_edge':Decimal('.01'),'max_payout':1000})(); self.logger=__import__('logging').getLogger('test')
 db=await Database(f"sqlite:///{tmp_path/'view-timeout.sqlite'}").open()
 await db.change_balance(88,100,'test-credit','credit:88')
 sid=await db.start_game(88,'mines',10)
 fair=await FairnessService(db,60).allocate(88,'mines')
 await db.attach_fair_round(sid,fair['round_id'])
 view=MinesView(Bot(db),88,10,2,sid,16,fair,Decimal('.01'),1000)
 await view.on_timeout(); await view.on_timeout()
 assert await db.balance(88)==90
 session=await db.conn.execute('SELECT settled FROM game_sessions WHERE id=?',(sid,))
 assert (await session.fetchone())['settled']==1
 assert await db.reconcile_balances()==[]
 await db.close()

@pytest.mark.asyncio
async def test_active_game_uses_payout_cap_snapshotted_at_wager_time(tmp_path):
 db=await Database(f"sqlite:///{tmp_path/'cap-snapshot.sqlite'}",max_payout=100).open()
 await db.change_balance(55,100,'seed','seed:55')
 sid=await db.start_game(55,'dice',10)
 db.max_payout=10  # models a later audited admin limit change
 assert await db.finish_game(sid,80,'settled under original cap')
 assert await db.balance(55)==170
 assert await db.reconcile_balances()==[]
 await db.close()

@pytest.mark.asyncio
async def test_retired_seed_reveal_waits_until_every_round_settles(tmp_path):
 db=await Database(f"sqlite:///{tmp_path/'reveal.sqlite'}").open()
 fair=FairnessService(db,60)
 a=await fair.allocate(101,'dice'); b=await fair.allocate(102,'limo')
 await db.conn.execute('UPDATE fair_seeds SET created_at=1'); await db.conn.commit()
 await fair.ensure_commitment()
 assert await db.pending_fair_reveals()==[]
 await fair.settle(a['round_id'],'refunded before play')
 assert await db.pending_fair_reveals()==[]
 await fair.settle(b['round_id'],'refunded before play')
 rows=await db.pending_fair_reveals()
 assert len(rows)==1 and rows[0]['commitment']==a['commitment']
 await db.mark_fair_reveal_published(rows[0]['id'])
 assert await db.pending_fair_reveals()==[]
 await db.close()

@pytest.mark.asyncio
async def test_fair_round_cannot_be_attached_to_another_user_or_game(tmp_path):
 db=await Database(f"sqlite:///{tmp_path/'attach.sqlite'}").open()
 await db.change_balance(1,30,'seed','seed:1')
 sid=await db.start_game(1,'mines',10)
 fair=await FairnessService(db,60).allocate(2,'limo')
 with pytest.raises(ValueError,match='does not match'):
  await db.attach_fair_round(sid,fair['round_id'])
 await db.refund_game(sid)
 await db.close()
