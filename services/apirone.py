from decimal import Decimal
from datetime import datetime, timezone
import httpx, re
SUPPORTED={
 'ltc':('Litecoin','LTC',8),
 'usdt@bnb':('Tether USD','USDT · BEP20 / BNB Smart Chain',18),
 'usdt@eth':('Tether USD','USDT · ERC20 / Ethereum',6),
}
class ApironeError(RuntimeError): pass

INVOICE_STATUSES = frozenset({'created', 'paid', 'partpaid', 'overpaid', 'completed', 'expired'})


def parse_minor_units(value, field='amount'):
 if isinstance(value, bool): raise ApironeError(f'Apirone {field} is malformed')
 if isinstance(value, int): return value
 if isinstance(value, str) and re.fullmatch(r'-?\d+', value): return int(value)
 raise ApironeError(f'Apirone {field} must be integer minor units')


def _valid_ltc_bech32(address):
 if not 8 <= len(address) <= 90 or (address.lower() != address and address.upper() != address): return False
 value=address.lower()
 if not value.startswith('ltc1'): return False
 alphabet='qpzry9x8gf2tvdw0s3jn54khce6mua7l'
 data=value[4:]
 if len(data)<7 or any(c not in alphabet for c in data): return False
 values=[alphabet.index(c) for c in data]
 hrp=[ord(c)>>5 for c in 'ltc']+[0]+[ord(c)&31 for c in 'ltc']
 generators=(0x3b6a57b2,0x26508e6d,0x1ea119fa,0x3d4233dd,0x2a1462b3)
 check=1
 for item in hrp+values:
  top=check>>25; check=((check&0x1ffffff)<<5)^item
  for i,generator in enumerate(generators):
   if (top>>i)&1: check^=generator
 return check in (1,0x2bc830a3)  # Bech32 and Bech32m


def _valid_ltc_base58(address):
 alphabet='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
 if not 26 <= len(address) <= 35 or any(c not in alphabet for c in address): return False
 number=0
 for char in address: number=number*58+alphabet.index(char)
 raw=number.to_bytes((number.bit_length()+7)//8,'big') if number else b''
 raw=b'\0'*(len(address)-len(address.lstrip('1')))+raw
 if len(raw)!=25 or raw[0] not in (0x30,0x32,0x05): return False
 import hashlib
 return hashlib.sha256(hashlib.sha256(raw[:-4]).digest()).digest()[:4]==raw[-4:]


def valid_address(currency, address):
 if not isinstance(address, str): return False
 if currency == 'ltc':
  # Apirone documents Litecoin legacy and SegWit address types.
  return _valid_ltc_bech32(address) or _valid_ltc_base58(address)
 if currency in ('usdt@bnb', 'usdt@eth'):
  # These token deposits use EVM addresses; invoice currency identifies the chain.
  return bool(re.fullmatch(r'0x[0-9a-fA-F]{40}', address))
 return False


def parse_expiration(value):
 if not isinstance(value, str) or not value.strip(): raise ApironeError('Apirone invoice expiration is missing')
 try:
  parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
 except ValueError as exc:
  raise ApironeError('Apirone invoice expiration is malformed') from exc
 if parsed.tzinfo is None: parsed = parsed.replace(tzinfo=timezone.utc)
 parsed = parsed.astimezone(timezone.utc)
 if parsed.timestamp() <= datetime.now(timezone.utc).timestamp(): raise ApironeError('Apirone returned an expired invoice')
 return parsed.isoformat()


class ApironeClient:
 BASE='https://apirone.com/api/v2'
 def __init__(self,account,key,timeout=15,transport=None): self.account,self.key=account,key; self.client=httpx.AsyncClient(timeout=timeout,transport=transport)
 async def close(self): await self.client.aclose()
 async def create_invoice(self,currency,amount,lifetime,user_id,callback_url=''):
  if currency not in SUPPORTED: raise ValueError('Unsupported asset/network')
  precision=SUPPORTED[currency][2]; scale=Decimal(10)**precision; units=amount*scale
  if amount<=0 or units!=units.to_integral_value(): raise ValueError('Amount has too many decimal places for this network')
  if type(lifetime) is not int or lifetime < 1: raise ValueError('Invoice lifetime must be a positive integer')
  payload={'currency':currency,'amount':str(int(units)),'lifetime':lifetime,'user-data':{'title':'Casino balance deposit','merchant':'Velvet Vault','extras':[{'name':'Discord user','price':str(user_id)}]}}
  if callback_url: payload['callback-url']=callback_url
  try: r=await self.client.post(f'{self.BASE}/accounts/{self.account}/invoices',json=payload)
  except httpx.HTTPError as e: raise ApironeError('Apirone invoice request failed') from None
  if r.status_code!=200: raise ApironeError(f'Apirone invoice endpoint returned HTTP {r.status_code}')
  try: data=r.json()
  except (ValueError,TypeError) as e: raise ApironeError('Apirone returned malformed invoice JSON') from e
  if not isinstance(data,dict): raise ApironeError('Apirone invoice response must be an object')
  for k in ('invoice','account','currency','amount','address','status','expire'):
   if k not in data: raise ApironeError(f'Invoice response missing {k}')
  if not isinstance(data['invoice'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}',data['invoice']) or data['account']!=self.account or not valid_address(currency,data['address']): raise ApironeError('Invoice identifier, account, or network address is invalid')
  remote_amount=parse_minor_units(data['amount'])
  try: expiration=parse_expiration(data['expire'])
  except ApironeError: raise
  if data['currency']!=currency or remote_amount!=int(units) or data['status']!='created': raise ApironeError('Invoice currency, amount, or initial status mismatch')
  data['expire']=expiration
  data['amount_coin']=Decimal(remote_amount)/scale
  return data
 async def private_invoice(self,invoice):
  if not isinstance(invoice,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}',invoice): raise ValueError('Invalid Apirone invoice identifier')
  try: r=await self.client.get(f'{self.BASE}/accounts/{self.account}/invoices/{invoice}',params={'transfer-key':self.key})
  except httpx.HTTPError as e: raise ApironeError('Apirone verification request failed') from None
  if r.status_code!=200: raise ApironeError(f'Apirone private invoice endpoint returned HTTP {r.status_code}')
  try: data=r.json()
  except (ValueError,TypeError) as e: raise ApironeError('Apirone returned malformed invoice JSON') from e
  if not isinstance(data,dict): raise ApironeError('Apirone invoice response must be an object')
  return data
