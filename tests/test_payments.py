import pytest, time
from decimal import Decimal
from services.payments import PaymentService

class MockApi:
 account='acct'
 def __init__(self,payload):self.payload=payload
 async def private_invoice(self,_):return self.payload

@pytest.mark.asyncio
async def test_only_confirmed_matching_invoice_credits(tmp_path):
 from database.db import Database
 db=await Database(f"sqlite:///{tmp_path/'pay.sqlite'}").open()
 await db.create_deposit({"invoice":"i1","discord_id":3,"currency":"usdt@eth","requested_amount":"5000000","account":"acct","address":"0x1111111111111111111111111111111111111111","status":"created"})
 p=PaymentService(db,MockApi({"invoice":"i1","currency":"usdt@eth","amount":5000000,"account":"acct","address":"0x1111111111111111111111111111111111111111","status":"paid","history":[{"status":"paid","txid":("a"*64),"amount":5000000}]}),rates={"ltc":Decimal(0),"usdt@bnb":Decimal(0),"usdt@eth":Decimal(1)},rate_updated_at={'usdt@eth':time.time()},rate_sources={'usdt@eth':'mock test fixture'}, live_enabled=True)
 result=await p.reconcile("i1")
 assert not result["credited"] and await db.balance(3)==0
 p.api=MockApi({"invoice":"i1","currency":"usdt@eth","amount":5000000,"account":"acct","address":"0x1111111111111111111111111111111111111111","status":"completed","history":[{"status":"paid","txid":("a"*64),"amount":5000000},{"status":"completed"}]})
 result=await p.reconcile("i1")
 assert result["credited"] and await db.balance(3)==5
 await db.close()

@pytest.mark.asyncio
async def test_invoice_mismatch_is_held(tmp_path):
 from database.db import Database
 db=await Database(f"sqlite:///{tmp_path/'pay.sqlite'}").open()
 await db.create_deposit({"invoice":"i1","discord_id":3,"currency":"usdt@bnb","requested_amount":"5000000000000000000","account":"acct","address":"0x1111111111111111111111111111111111111111","status":"created"})
 p=PaymentService(db,MockApi({"invoice":"i1","currency":"usdt@eth","amount":5,"account":"acct","address":"0x1111111111111111111111111111111111111111","status":"completed","history":[]}), live_enabled=True)
 with pytest.raises(ValueError):await p.reconcile("i1")
 assert await db.balance(3)==0
 await db.close()

@pytest.mark.asyncio
async def test_malformed_history_and_stale_rates_are_held(tmp_path):
 import time
 from database.db import Database
 db=await Database(f"sqlite:///{tmp_path/'malformed.sqlite'}").open()
 await db.create_deposit({'invoice':'safe','discord_id':12,'currency':'usdt@eth','requested_amount':'5000000','address':'0x1111111111111111111111111111111111111111','status':'created'})
 base={'invoice':'safe','currency':'usdt@eth','amount':5000000,'account':'acct','address':'0x1111111111111111111111111111111111111111','status':'completed'}
 bad=PaymentService(db,MockApi({**base,'history':[None]}),rates={'usdt@eth':Decimal(10)},rate_updated_at={'usdt@eth':time.time()},rate_sources={'usdt@eth':'mock test fixture'}, live_enabled=True)
 with pytest.raises(ValueError,match='history'):
  await bad.reconcile('safe')
 good=PaymentService(db,MockApi({**base,'history':[{'status':'paid','txid':'a'*64,'amount':5000000}]}),rates={'usdt@eth':Decimal(10)},rate_updated_at={'usdt@eth':time.time()-7200},rate_sources={'usdt@eth':'mock test fixture'}, live_enabled=True)
 result=await good.reconcile('safe')
 assert not result['credited'] and 'stale' in result['reason'] and await db.balance(12)==0
 await db.close()

@pytest.mark.asyncio
async def test_malformed_invoice_creation_response_is_rejected(tmp_path):
 from database.db import Database
 class CreateApi:
  async def create_invoice(self,*args):
   return {'invoice':'../../unsafe','currency':'usdt@eth','amount':1,'account':'acct','address':'0x1111111111111111111111111111111111111111','status':'created'}
 db=await Database(f"sqlite:///{tmp_path/'bad-create.sqlite'}").open()
 p=PaymentService(db,CreateApi(),rates={'usdt@eth':Decimal(1)},rate_updated_at={'usdt@eth':time.time()},rate_sources={'usdt@eth':'mock test fixture'}, live_enabled=True)
 with pytest.raises(ValueError): await p.create(1,'usdt@eth',Decimal('1'),3600)
 assert await db.balance(1)==0
 await db.close()

@pytest.mark.asyncio
async def test_provider_response_without_a_real_network_address_is_never_persisted(tmp_path):
 from database.db import Database
 class BadProvider:
  account='acct'
  async def create_invoice(self,*args):
   return {'invoice':'invoice123456','account':'acct','currency':'usdt@eth','amount':'1000000','address':'random-placeholder','status':'created','expire':'2099-01-01T00:00:00Z'}
 db=await Database(f"sqlite:///{tmp_path/'bad-address.sqlite'}").open()
 p=PaymentService(db,BadProvider(),rates={'usdt@eth':Decimal(1)},rate_updated_at={'usdt@eth':time.time()},rate_sources={'usdt@eth':'mock test fixture'}, live_enabled=True)
 with pytest.raises(ValueError,match='network address'):
  await p.create(1,'usdt@eth',Decimal('1'),3600)
 assert await db.deposit('invoice123456') is None
 await db.close()


@pytest.mark.asyncio
async def test_new_invoice_creation_requires_a_fresh_sourced_rate_before_provider_call(tmp_path):
 from decimal import Decimal
 from database.db import Database
 class Provider:
  account='acct'
  def __init__(self):self.calls=0
  async def create_invoice(self,*args):self.calls+=1;raise AssertionError('must not contact provider')
 db=await Database(f"sqlite:///{tmp_path/'rate-gate.sqlite'}").open();api=Provider()
 svc=PaymentService(db,api, live_enabled=True)
 with pytest.raises(ValueError,match='conversion rate'):
  await svc.create(1,'usdt@eth',Decimal('1'),3600)
 assert api.calls==0 and await db.deposit_history(1)==[]
 await db.close()

@pytest.mark.asyncio
async def test_live_invoice_creation_is_closed_by_default_even_with_a_fresh_rate(tmp_path):
 from database.db import Database
 class Provider:
  account='acct'
  def __init__(self):self.calls=0
  async def create_invoice(self,*args):self.calls+=1;raise AssertionError('provider must not be contacted')
 db=await Database(f"sqlite:///{tmp_path/'disabled-invoice.sqlite'}").open();api=Provider()
 svc=PaymentService(db,api,rates={'usdt@eth':Decimal(1)},rate_updated_at={'usdt@eth':time.time()},rate_sources={'usdt@eth':'fixture'})
 with pytest.raises(ValueError,match='Live deposits are disabled'):
  await svc.create(1,'usdt@eth',Decimal('1'),3600)
 assert api.calls==0 and await db.deposit_history(1)==[]
 await db.close()
