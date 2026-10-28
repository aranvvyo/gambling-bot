from decimal import Decimal
import asyncio
import pytest
import pytest_asyncio, time, json
from database.db import Database
from services.game_math import mines_multiplier,tower_multiplier,limbo_multiplier,limbo_roll,crash_point,blackjack_value,blackjack_return,limo_multiplier,payout,safe_index,deck
from services.payments import PaymentService

@pytest_asyncio.fixture
async def db(tmp_path):
 d=await Database(f'sqlite:///{tmp_path}/test.db').open(); yield d; await d.close()

@pytest.mark.asyncio
async def test_wallet_atomic_bets_and_duplicate_settlement(db):
 await db.change_balance(1,1000,'seed','seed:1')
 sid=await db.start_game(1,'mines',100)
 assert await db.balance(1)==900
 assert await db.finish_game(sid,180)
 assert not await db.finish_game(sid,180)
 assert await db.balance(1)==1080
 async def bet():
  try:return await db.start_game(1,'race',700)
  except ValueError:return None
 result=await asyncio.gather(bet(),bet())
 assert sum(x is not None for x in result)==1
 assert await db.balance(1)==380

@pytest.mark.asyncio
async def test_negative_and_zero_rejected_and_rollback(db):
 await db.change_balance(2,30,'seed','seed:2')
 with pytest.raises(ValueError):await db.change_balance(2,-31,'debit')
 with pytest.raises(ValueError):await db.change_balance(2,0,'bad')
 with pytest.raises(ValueError):await db.start_game(2, 'game', 31)
 assert await db.balance(2)==30

class FakeAPI:
 account='acct'
 def __init__(self,status='completed'):self.status=status
 async def create_invoice(self,currency,amount,lifetime,uid,callback):
  return {'invoice':'I123456789012','account':'acct','currency':currency,'amount':1000000,'amount_coin':Decimal('1'),'address':'0x'+'1'*40,'status':'created','expire':(time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(time.time()+3600)))}
 async def private_invoice(self,invoice):
  return {'invoice':invoice,'account':'acct','currency':'usdt@eth','amount':1000000,'address':'0x'+'1'*40,'status':self.status,'history':[{'status':'paid','txid':'a'*64,'amount':1000000}]}

@pytest.mark.asyncio
async def test_deposit_confirm_credit_and_duplicate_is_idempotent(db):
 api=FakeAPI(); service=PaymentService(db,api,{'ltc':Decimal(1),'usdt@bnb':Decimal(1),'usdt@eth':Decimal(100)},Decimal('0.01'),Decimal(1000),rate_updated_at={'usdt@eth':time.time()},rate_sources={'usdt@eth':'mock test fixture'}, live_enabled=True)
 inv=await service.create(3,'usdt@eth',Decimal(1),3600)
 result=await service.reconcile(inv['invoice']); assert result['credited'] and result['amount']==100
 duplicate=await service.reconcile(inv['invoice']); assert duplicate['status']=='completed' and duplicate['already_credited'] and duplicate['paid_amount']=='1' and duplicate['remaining_amount']=='0'
 assert await db.balance(3)==100

@pytest.mark.asyncio
async def test_forged_or_mismatched_deposit_is_never_credited(db):
 api=FakeAPI('paid'); service=PaymentService(db,api,{'ltc':Decimal(1),'usdt@bnb':Decimal(1),'usdt@eth':Decimal(100)},Decimal('0.01'),Decimal(1000),rate_updated_at={'usdt@eth':time.time()},rate_sources={'usdt@eth':'mock test fixture'}, live_enabled=True)
 inv=await service.create(4,'usdt@eth',Decimal(1),3600)
 api.private_invoice=lambda _: None
 with pytest.raises(Exception): await service.reconcile(inv['invoice'])
 assert await db.balance(4)==0

@pytest.mark.asyncio
async def test_partial_and_expired_not_credited(db):
 api=FakeAPI('partpaid'); service=PaymentService(db,api,{'ltc':Decimal(1),'usdt@bnb':Decimal(1),'usdt@eth':Decimal(100)},Decimal('0.01'),Decimal(1000),rate_updated_at={'usdt@eth':time.time()},rate_sources={'usdt@eth':'mock test fixture'}, live_enabled=True)
 inv=await service.create(5,'usdt@eth',Decimal(1),3600)
 out=await service.reconcile(inv['invoice']); assert out['status']=='partpaid' and not out['credited']
 assert await db.balance(5)==0

@pytest.mark.asyncio
async def test_restart_recovers_active_bet(db):
 await db.change_balance(6,100,'seed','seed:6'); sid=await db.start_game(6,'crash',40)
 await db.recover_games(); assert await db.balance(6)==100
 assert not await db.finish_game(sid,90)

def test_game_math_bounds_and_payouts():
 assert mines_multiplier(3,1)>Decimal(1)
 assert tower_multiplier(2,2)==Decimal('3.96')
 assert limbo_multiplier(Decimal('2'))==Decimal('1.98')
 assert Decimal(1)<=crash_point()<=Decimal(1000)
 assert blackjack_value([1,13,9])==20
 assert blackjack_value([1,1,9])==21
 assert len(deck())==52 and 0<=safe_index(5)<5
 assert payout(100,Decimal('2.5'),1000)==250
 assert blackjack_return(100,21,20,natural=True)==250
 assert blackjack_return(100,19,18)==200
 assert blackjack_return(100,18,18)==100
 assert blackjack_return(100,22,18)==0
 assert limo_multiplier(3)==Decimal('2.97')
 with pytest.raises(ValueError): limo_multiplier(1)
 for bad in [0,25]:
  with pytest.raises(ValueError):mines_multiplier(bad,0)
 with pytest.raises(ValueError):limbo_multiplier(Decimal('1'))

@pytest.mark.asyncio
async def test_daily_limit_and_self_exclusion_are_transactional(db):
 await db.change_balance(9,1000,'seed','seed:9')
 await db.start_game(9,'mines',60,100)
 with pytest.raises(ValueError,match='Daily wager limit'):
  await db.start_game(9,'crash',50,100)
 await db.set_daily_limit(9,80)
 with pytest.raises(ValueError,match='Daily wager limit'):
  await db.start_game(9,'limo',30,100)
 until=await db.self_exclude(9,1)
 assert until>0
 with pytest.raises(ValueError,match='self-excluded'):
  await db.start_game(9,'blackjack',10,100)

@pytest.mark.asyncio
async def test_deposit_amount_limits_and_network_validation(db):
 api=FakeAPI(); service=PaymentService(db,api,{'ltc':Decimal(1),'usdt@bnb':Decimal(1),'usdt@eth':Decimal(100)},Decimal('0.01'),Decimal(10), live_enabled=True)
 for currency,amount in [('bad',Decimal(1)),('usdt@eth',Decimal(0)),('usdt@eth',Decimal(11)),('usdt@eth',Decimal('NaN'))]:
  with pytest.raises(ValueError):await service.create(20,currency,amount,3600)

@pytest.mark.asyncio
async def test_repeated_txid_does_not_double_count_payment(db):
 api=FakeAPI(); service=PaymentService(db,api,{'ltc':Decimal(1),'usdt@bnb':Decimal(1),'usdt@eth':Decimal(100)},Decimal('0.01'),Decimal(1000),rate_updated_at={'usdt@eth':time.time()},rate_sources={'usdt@eth':'mock test fixture'}, live_enabled=True)
 inv=await service.create(21,'usdt@eth',Decimal(1),3600)
 async def duplicate(_):
  return {'invoice':inv['invoice'],'account':'acct','currency':'usdt@eth','amount':1000000,'address':'0x'+'1'*40,'status':'completed','history':[{'status':'paid','txid':'b'*64,'amount':600000},{'status':'paid','txid':'b'*64,'amount':600000}]}
 api.private_invoice=duplicate
 out=await service.reconcile(inv['invoice'])
 assert not out['credited'] and 'held' in out['reason']
 assert await db.balance(21)==0

@pytest.mark.asyncio
async def test_maintenance_holds_verified_apirone_credit_until_resume(db):
 api=FakeAPI('completed')
 service=PaymentService(db,api,{'ltc':Decimal(1),'usdt@bnb':Decimal(1),'usdt@eth':Decimal(100)},Decimal('0.01'),Decimal(1000),rate_updated_at={'usdt@eth':time.time()},rate_sources={'usdt@eth':'mock fixture'},live_enabled=True)
 inv=await service.create(901,'usdt@eth',Decimal(1),3600)
 db.maintenance_mode=True
 result=await service.reconcile(inv['invoice'])
 assert result['status']=='completed' and not result['credited'] and 'maintenance' in result['reason'].lower()
 assert await db.balance(901)==0
 db.maintenance_mode=False
 result=await service.reconcile(inv['invoice'])
 assert result['credited'] and await db.balance(901)==100

@pytest.mark.asyncio
async def test_maintenance_blocks_new_wagers_and_tips_at_database_boundary(db):
 await db.change_balance(902,100,'seed','maintenance-seed')
 db.maintenance_mode=True
 with pytest.raises(ValueError,match='maintenance'): await db.start_game(902,'dice',10,100)
 with pytest.raises(ValueError,match='maintenance'): await db.transfer(902,903,1,'maintenance-tip')
 assert await db.balance(902)==100 and await db.balance(903)==0
