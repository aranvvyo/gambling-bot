"""Deposit settlement edge cases with simulated provider responses only."""
import asyncio
import time
from decimal import Decimal

import pytest

from database.db import Database
from services.payments import PaymentService

ACCOUNT = 'apr-' + 'a' * 32
ADDRESS = '0x' + 'ab' * 20
TX1 = '1' * 64
TX2 = '2' * 64


class FakeProvider:
    account = ACCOUNT
    def __init__(self, response): self.response = response
    async def private_invoice(self, invoice):
        if isinstance(self.response, Exception): raise self.response
        return self.response


def response(invoice_id, status='completed', history=None, **changes):
    payload = {'account':ACCOUNT, 'invoice':invoice_id, 'currency':'usdt@eth',
               'amount':'5000000', 'address':ADDRESS, 'status':status,
               'history':history or []}
    payload.update(changes)
    return payload


def service(db, api):
    return PaymentService(db, api, rates={'usdt@eth':Decimal('2')},
        rate_updated_at={'usdt@eth':time.time()}, rate_sources={'usdt@eth':'mock source'}, live_enabled=True)


async def make_invoice(db, invoice='invoice123456'):
    await db.create_deposit({'invoice':invoice,'discord_id':500,'currency':'usdt@eth',
        'requested_amount':'5000000','address':ADDRESS,'status':'created',
        'expires_at':'2099-01-01T00:00:00+00:00'})
    return invoice


@pytest.mark.asyncio
async def test_documented_historical_partpaid_entries_can_confirm_when_current_invoice_is_completed(tmp_path):
    db=await Database(f'sqlite:///{tmp_path / "history.sqlite"}').open()
    invoice=await make_invoice(db)
    api=FakeProvider(response(invoice, history=[
        {'status':'partpaid','txid':TX1,'amount':'2000000'},
        {'status':'partpaid','txid':TX1,'amount':'2000000'}, # same tx is counted once
        {'status':'paid','txid':TX2,'amount':'3000000'},
        {'status':'completed'},
    ]))
    result=await service(db,api).reconcile(invoice)
    assert result['credited'] and result['amount']==10
    assert await db.balance(500)==10
    await db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('status',['created','paid','partpaid','overpaid','expired'])
async def test_noncompleted_statuses_never_credit_and_expired_invoices_keep_polling(tmp_path,status):
    db=await Database(f'sqlite:///{tmp_path / (status + ".sqlite")}').open()
    invoice=await make_invoice(db)
    api=FakeProvider(response(invoice,status,history=[{'status':'paid','txid':TX1,'amount':'5000000'}]))
    result=await service(db,api).reconcile(invoice)
    assert not result['credited'] and await db.balance(500)==0
    assert invoice in await db.pending_deposits()
    await db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('bad_amount',[True,5.9,'5.9',None])
async def test_malformed_minor_unit_values_never_credit(tmp_path,bad_amount):
    db=await Database(f'sqlite:///{tmp_path / "bad-units.sqlite"}').open()
    invoice=await make_invoice(db)
    api=FakeProvider(response(invoice,amount=bad_amount,history=[{'status':'paid','txid':TX1,'amount':'5000000'}]))
    with pytest.raises(ValueError): await service(db,api).reconcile(invoice)
    assert await db.balance(500)==0
    await db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('history',[None, [{'status':'paid','txid':TX1,'amount':True}],
    [{'status':'paid','txid':'not-a-txid','amount':'5000000'}],
    [{'status':'paid','txid':TX1,'amount':'4000000'}],
    [{'status':'paid','txid':TX1,'amount':'6000000'}]])
async def test_malformed_under_and_overpayment_histories_are_held(tmp_path,history):
    db=await Database(f'sqlite:///{tmp_path / "history-check.sqlite"}').open()
    invoice=await make_invoice(db)
    api=FakeProvider(response(invoice,history=history))
    try:
        result=await service(db,api).reconcile(invoice)
        assert not result['credited']
    except ValueError:
        pass
    assert await db.balance(500)==0
    await db.close()


@pytest.mark.asyncio
async def test_concurrent_repeated_polls_credit_exactly_once(tmp_path):
    db=await Database(f'sqlite:///{tmp_path / "race.sqlite"}').open()
    invoice=await make_invoice(db)
    api=FakeProvider(response(invoice,history=[{'status':'paid','txid':TX1,'amount':'5000000'}]))
    svc=service(db,api)
    results=await asyncio.gather(*(svc.reconcile(invoice) for _ in range(12)))
    assert sum(bool(x.get('credited')) for x in results)==1
    assert await db.balance(500)==10
    assert await db.reconcile_balances()==[]
    await db.close()


@pytest.mark.asyncio
async def test_provider_identity_network_and_address_mismatch_are_rejected(tmp_path):
    db=await Database(f'sqlite:///{tmp_path / "identity.sqlite"}').open()
    invoice=await make_invoice(db)
    for changes in ({'account':'other'}, {'currency':'usdt@bnb'}, {'address':'fake-address'}, {'invoice':'otherinvoice'}):
        api=FakeProvider(response(invoice,history=[{'status':'paid','txid':TX1,'amount':'5000000'}],**changes))
        with pytest.raises(ValueError,match='mismatch'):
            await service(db,api).reconcile(invoice)
        assert await db.balance(500)==0
    await db.close()


@pytest.mark.asyncio
async def test_database_credit_requires_verified_exact_minor_unit_total(tmp_path):
    db=await Database(f'sqlite:///{tmp_path / "credit-guard.sqlite"}').open()
    invoice=await make_invoice(db)
    await db.update_deposit(invoice,'completed',[TX1],4_999_999)
    with pytest.raises(ValueError,match='exact amount'):
        await db.credit_deposit(invoice,10,TX1)
    assert await db.balance(500)==0
    await db.close()


@pytest.mark.asyncio
async def test_duplicate_invoice_insert_rolls_back_created_user(tmp_path):
    db=await Database(f'sqlite:///{tmp_path / "duplicate.sqlite"}').open()
    await make_invoice(db)
    with pytest.raises(Exception):
        await db.create_deposit({'invoice':'invoice123456','discord_id':501,
            'currency':'usdt@eth','requested_amount':'5000000','address':ADDRESS,'status':'created'})
    cur=await db.conn.execute('SELECT 1 FROM users WHERE discord_id=501')
    assert await cur.fetchone() is None
    await db.close()


@pytest.mark.asyncio
async def test_provider_failed_status_is_recorded_without_credit(tmp_path):
    db=await Database(f'sqlite:///{tmp_path / "failed.sqlite"}').open()
    invoice=await make_invoice(db)
    result=await service(db,FakeProvider(response(invoice,'failed'))).reconcile(invoice)
    assert result['status']=='failed' and not result['credited']
    assert invoice not in await db.pending_deposits()
    assert await db.balance(500)==0
    await db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(('currency','decimals','address'),[
    ('ltc',8,'LKKG9A9a8n7CeHK8Nk7RdNZiCuHZW2U789'),
    ('usdt@bnb',18,'0x'+'23'*20),
    ('usdt@eth',6,'0x'+'34'*20),
])
async def test_each_supported_network_credits_only_exact_confirmed_minor_units(tmp_path,currency,decimals,address):
    db=await Database(f'sqlite:///{tmp_path / (currency.replace("@","-") + ".sqlite")}').open()
    amount=Decimal('0.1'); units=int(amount*(Decimal(10)**decimals)); invoice='coin-'+currency.replace('@','-')
    await db.create_deposit({'invoice':invoice,'discord_id':700,'currency':currency,
        'requested_amount':str(units),'address':address,'status':'created'})
    api=FakeProvider({'account':ACCOUNT,'invoice':invoice,'currency':currency,
        'amount':str(units),'address':address,'status':'completed',
        'history':[{'status':'paid','txid':TX1,'amount':str(units)}]})
    svc=PaymentService(db,api,rates={currency:Decimal('1000')},
        rate_updated_at={currency:time.time()},rate_sources={currency:'mock source'}, live_enabled=True)
    result=await svc.reconcile(invoice)
    assert result['credited'] and result['amount']==100
    assert await db.balance(700)==100
    assert await db.reconcile_balances()==[]
    await db.close()
