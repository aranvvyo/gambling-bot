"""Validate Apirone invoices and perform idempotent wallet crediting."""
from decimal import Decimal, ROUND_DOWN
import re
import time

from services.apirone import (
    SUPPORTED,
    INVOICE_STATUSES,
    ApironeError,
    parse_minor_units,
    parse_expiration,
    valid_address,
)


class PaymentService:
    def __init__(self, db, apirone, rates=None, min_amount=Decimal('0.00000001'),
                 max_amount=Decimal('1000000000'), max_credit=1_000_000,
                 rate_updated_at=None, rate_max_age_seconds=3600, rate_sources=None, live_enabled=False):
        self.db = db
        self.api = apirone
        self.rates = rates if rates is not None else {k: Decimal(0) for k in SUPPORTED}
        self.minimum, self.maximum, self.max_credit = min_amount, max_amount, max_credit
        self.rate_updated_at = rate_updated_at or {}
        self.rate_max_age_seconds = rate_max_age_seconds
        self.rate_sources = rate_sources or {}
        self.live_enabled = bool(live_enabled)

    def rate_readiness(self, currency, now=None):
        now=time.time() if now is None else now
        rate=self.rates.get(currency,Decimal(0));updated=self.rate_updated_at.get(currency);source=self.rate_sources.get(currency,'')
        if not updated or type(updated) not in (int,float) or not isinstance(source,str) or not source.strip():
            return 'A current conversion rate with source and timestamp is required before a new invoice can be created.'
        if now-updated>self.rate_max_age_seconds or updated>now+60:
            return 'The conversion rate is stale or future-dated; no invoice can be created.'
        if not isinstance(rate,Decimal) or not rate.is_finite() or rate<=0:
            return 'Automatic conversion is disabled for this asset; new invoices are unavailable.'
        return ''

    async def create(self, uid, currency, amount, lifetime, callback_url=''):
        if self.db.maintenance_mode: raise ValueError('Casino maintenance is active; deposit invoices are paused.')
        if not self.live_enabled: raise ValueError('Live deposits are disabled until credentials, rates, and provider verification are reviewed.')
        if self.db.maintenance_mode: raise ValueError('Casino maintenance is active; deposit invoices are paused.')
        if currency not in SUPPORTED:
            raise ValueError('Unsupported coin/network')
        if not isinstance(amount, Decimal) or not amount.is_finite() or amount < self.minimum or amount > self.maximum:
            raise ValueError(f'Deposit must be between {self.minimum} and {self.maximum} of the selected asset.')
        scale = Decimal(10) ** SUPPORTED[currency][2]
        units = amount * scale
        if units != units.to_integral_value():
            raise ValueError('Amount has too many decimal places for the selected network')
        reason=self.rate_readiness(currency)
        if reason: raise ValueError(reason)
        credit=int((amount*self.rates[currency]).to_integral_value(rounding=ROUND_DOWN))
        if credit<=0 or credit>self.max_credit:
            raise ValueError('This invoice amount is outside the configured wallet-credit limits.')

        remote = await self.api.create_invoice(currency, amount, lifetime, uid, callback_url)
        required = ('invoice', 'account', 'address', 'currency', 'amount', 'status', 'expire')
        if not isinstance(remote, dict) or any(key not in remote for key in required):
            raise ValueError('Apirone returned an incomplete invoice response')
        invoice = remote['invoice']
        if (not isinstance(invoice, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', invoice)
                or remote['currency'] != currency or remote['status'] != 'created'
                or not valid_address(currency, remote['address'])):
            raise ValueError('Apirone returned an invalid invoice identity or network address')
        expected_account = getattr(self.api, 'account', None)
        if not expected_account or remote['account'] != expected_account:
            raise ValueError('Apirone returned an invoice for a different account')
        try:
            remote_units = parse_minor_units(remote['amount'], 'invoice amount')
            expires_at = parse_expiration(remote['expire'])
        except ApironeError as exc:
            raise ValueError(str(exc)) from None
        if remote_units != int(units):
            raise ValueError('Apirone returned an invoice for a different amount')

        remote['expire'] = expires_at
        remote['amount_coin'] = Decimal(remote_units) / scale
        await self.db.create_deposit({
            'invoice': invoice,
            'discord_id': uid,
            'currency': currency,
            'requested_amount': str(remote_units),
            'address': remote['address'],
            'status': remote['status'],
            'expires_at': expires_at,
            'invoice_url': remote.get('invoice-url', ''),
        })
        return remote

    async def reconcile(self, invoice):
        local = await self.db.deposit(invoice)
        if not local:
            raise ValueError('unknown invoice')
        if local['credited']:
            scale=Decimal(10)**SUPPORTED[local['currency']][2]
            paid=Decimal(int(local['verified_amount'] or 0))/scale
            requested=Decimal(local['requested_amount'])/scale
            return {'status':local['status'],'credited':False,'already_credited':True,'reason':'','currency':local['currency'],'invoice_amount':str(requested),'paid_amount':str(paid),'remaining_amount':str(max(Decimal(0),requested-paid))}

        remote = await self.api.private_invoice(invoice)
        if local['currency'] not in SUPPORTED:
            raise ValueError('Stored deposit has an unsupported asset/network')
        scale = Decimal(10) ** SUPPORTED[local['currency']][2]
        if not isinstance(remote, dict):
            raise ValueError('Malformed Apirone invoice response')
        expected_account = getattr(self.api, 'account', None)
        if not expected_account or remote.get('account') != expected_account:
            raise ValueError('Apirone invoice account mismatch; deposit held')
        try:
            remote_units = parse_minor_units(remote.get('amount'), 'invoice amount')
        except ApironeError as exc:
            raise ValueError(str(exc)) from None

        if (remote.get('invoice') != invoice
                or remote.get('currency') != local['currency']
                or remote_units != int(local['requested_amount'])
                or remote.get('address') != local['address']
                or not valid_address(local['currency'], remote.get('address'))):
            raise ValueError('Apirone invoice identity mismatch; deposit held')
        status = remote.get('status')
        if status == 'failed':
            # The current published Apirone invoice status list has no failed state;
            # if a provider/adapter reports one, safely mark it terminal without credit.
            await self.db.update_deposit(invoice, status, [], 0)
            return {'status': status, 'credited': False, 'reason': 'Provider reported a failed invoice; no balance credit was made.'}
        if status not in INVOICE_STATUSES:
            raise ValueError('Unknown Apirone invoice status')

        history = remote.get('history')
        if history is None:
            history = []
        if not isinstance(history, list):
            raise ValueError('Malformed Apirone transaction history')
        txids, paid_units, seen = [], 0, {}
        for item in history:
            if not isinstance(item, dict):
                raise ValueError('Malformed Apirone transaction history entry')
            txid = item.get('txid')
            if not txid:
                continue
            # History status is an invoice snapshot (including partpaid), not a
            # confirmation counter. The authenticated current `completed` state
            # is Apirone's confirmation signal for the invoice.
            if item.get('status') not in INVOICE_STATUSES:
                raise ValueError('Invalid transaction history status')
            if (not isinstance(txid, str)
                    or not (len(txid) == 64 or (len(txid) == 66 and txid.startswith('0x')))
                    or any(c not in '0123456789abcdefABCDEF' for c in txid.removeprefix('0x'))):
                raise ValueError('Invalid transaction identifier in verified history')
            try:
                amount_units = parse_minor_units(item.get('amount'), 'transaction amount')
            except ApironeError as exc:
                raise ValueError(str(exc)) from None
            if amount_units <= 0:
                raise ValueError('Invalid verified transaction amount')
            if txid in seen and seen[txid] != amount_units:
                raise ValueError('Conflicting duplicate transaction entries in Apirone history')
            if txid not in seen:
                seen[txid] = amount_units
                txids.append(txid)
                paid_units += amount_units

        await self.db.update_deposit(invoice, status, txids, paid_units)
        requested=int(local['requested_amount']); coin_requested=Decimal(requested)/scale; coin_paid=Decimal(paid_units)/scale
        payment_fields={'currency':local['currency'],'invoice_amount':str(coin_requested),'paid_amount':str(coin_paid),'remaining_amount':str(max(Decimal(0),coin_requested-coin_paid))}
        if status != 'completed':
            reason = 'Partial or excess payments require review.' if status in ('partpaid', 'overpaid') else ''
            return {'status': status, 'credited': False, 'reason': reason, **payment_fields}

        requested = int(local['requested_amount'])
        if not txids or paid_units != requested:
            return {'status': status, 'credited': False,
                    'reason': 'Confirmed payment total differs from the invoice; held for manual review.', **payment_fields}
        if self.db.maintenance_mode:
            return {'status':status,'credited':False,'reason':'Payment is verified, but credits are held while maintenance is active.',**payment_fields}
        rate = self.rates.get(local['currency'], Decimal(0))
        updated = self.rate_updated_at.get(local['currency'])
        source = self.rate_sources.get(local['currency'], '')
        rate_problem=self.rate_readiness(local['currency'])
        if rate_problem:
            return {'status': status, 'credited': False, 'reason': rate_problem, **payment_fields}

        coin_amount = Decimal(local['requested_amount']) / scale
        credit = int((coin_amount * rate).to_integral_value(rounding=ROUND_DOWN))
        if credit <= 0:
            return {'status': status, 'credited': False,
                    'reason': 'Configured conversion produced no wallet units; administrator review required.', **payment_fields}
        if credit > self.max_credit:
            return {'status': status, 'credited': False,
                    'reason': 'Configured conversion exceeds the per-invoice wallet credit ceiling; administrator review required.', **payment_fields}
        detail = (f"Apirone {local['currency']} amount={coin_amount} rate={rate} "
                  f"rate_updated_at={int(updated)} rate_source={source[:100]}")
        credited = await self.db.credit_deposit(invoice, credit, txids[-1], detail)
        return {'status': status, 'credited': credited, 'amount': credit,
                'already_credited': not credited, **payment_fields}
