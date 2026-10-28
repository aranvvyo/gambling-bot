"""Apirone API contract tests with HTTPX MockTransport; no live requests."""
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest

from services.apirone import ApironeClient, ApironeError, SUPPORTED, valid_address

import hashlib

ACCOUNT = 'apr-' + 'a' * 32
EVM = '0x' + '12' * 20

def ltc_fixture():
    alphabet='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    payload=b'\x30'+b'\x01'*20
    raw=payload+hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    n=int.from_bytes(raw,'big'); out=''
    while n:
        n,rem=divmod(n,58); out=alphabet[rem]+out
    return '1'*(len(raw)-len(raw.lstrip(b'\0')))+out

LTC = ltc_fixture()


@pytest.mark.parametrize(('currency', 'amount', 'units', 'address'), [
    ('ltc', Decimal('0.1'), '10000000', LTC),
    ('usdt@bnb', Decimal('0.1'), '100000000000000000', EVM),
    ('usdt@eth', Decimal('0.1'), '100000', EVM),
])
@pytest.mark.asyncio
async def test_invoice_creation_uses_documented_route_minor_units_and_verified_response(currency, amount, units, address):
    expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

    def handler(request):
        assert request.method == 'POST'
        assert request.url.path == f'/api/v2/accounts/{ACCOUNT}/invoices'
        body = json.loads(request.content)
        assert body['currency'] == currency
        assert body['amount'] == units  # API accepts integer/string; string preserves 18-place precision.
        assert body['lifetime'] == 3600
        return httpx.Response(200, json={
            'invoice': 'invoice123456', 'account': ACCOUNT, 'currency': currency,
            'amount': units, 'address': address, 'status': 'created', 'expire': expires,
            'invoice-url': 'https://apirone.com/invoice?id=invoice123456',
        })

    client = ApironeClient(ACCOUNT, 'test-transfer-key', transport=httpx.MockTransport(handler))
    try:
        result = await client.create_invoice(currency, amount, 3600, 123)
        assert result['account'] == ACCOUNT
        assert result['currency'] == currency
        assert result['amount_coin'] == amount
        assert result['address'] == address
        assert result['status'] == 'created'
        assert result['expire'] > datetime.now(timezone.utc).isoformat()
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('bad', [
    {'account': 'other'}, {'currency': 'usdt@eth'}, {'amount': 1.5},
    {'address': 'fake-address'}, {'status': 'paid'}, {'expire': 'not-a-date'},
])
async def test_invoice_creation_rejects_malformed_or_mismatched_provider_response(bad):
    expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    payload = {'invoice':'invoice123456','account':ACCOUNT,'currency':'usdt@bnb',
               'amount':'100000000000000000','address':EVM,'status':'created','expire':expires}
    payload.update(bad)
    client = ApironeClient(ACCOUNT, 'test-key', transport=httpx.MockTransport(lambda req:httpx.Response(200,json=payload)))
    try:
        with pytest.raises(ApironeError):
            await client.create_invoice('usdt@bnb', Decimal('0.1'), 3600, 5)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_private_invoice_uses_authenticated_documented_endpoint_and_suppresses_secret_errors():
    def handler(request):
        assert request.method == 'GET'
        assert request.url.path == f'/api/v2/accounts/{ACCOUNT}/invoices/invoice123456'
        assert request.url.params.get('transfer-key') == 'private-key'
        return httpx.Response(200,json={'invoice':'invoice123456','status':'completed'})
    client=ApironeClient(ACCOUNT,'private-key',transport=httpx.MockTransport(handler))
    try:
        assert (await client.private_invoice('invoice123456'))['status']=='completed'
    finally: await client.close()

    def timeout(_): raise httpx.ReadTimeout('sensitive request metadata')
    client=ApironeClient(ACCOUNT,'private-key',transport=httpx.MockTransport(timeout))
    try:
        with pytest.raises(ApironeError,match='verification request failed') as error:
            await client.private_invoice('invoice123456')
        assert 'private-key' not in str(error.value)
    finally: await client.close()


@pytest.mark.parametrize(('currency','address','expected'),[
    ('ltc',LTC,True),('ltc','L-address',False),('usdt@bnb',EVM,True),
    ('usdt@eth',EVM,True),('usdt@bnb','ltc1fake',False),('usdt@eth','0x1234',False),
])
def test_address_shape_is_checked_against_invoice_network(currency,address,expected):
    assert valid_address(currency,address) is expected


@pytest.mark.asyncio
async def test_provider_http_errors_and_invalid_json_fail_closed():
    async def unavailable(_): return httpx.Response(503,text='internal provider body')
    client=ApironeClient(ACCOUNT,'secret-key',transport=httpx.MockTransport(unavailable))
    try:
        with pytest.raises(ApironeError,match='HTTP 503') as err:
            await client.create_invoice('usdt@bnb',Decimal('0.1'),3600,1)
        assert 'internal provider body' not in str(err.value)
    finally: await client.close()

    async def invalid_json(_): return httpx.Response(200,content=b'not json')
    client=ApironeClient(ACCOUNT,'secret-key',transport=httpx.MockTransport(invalid_json))
    try:
        with pytest.raises(ApironeError,match='malformed invoice JSON'):
            await client.create_invoice('usdt@bnb',Decimal('0.1'),3600,1)
    finally: await client.close()
