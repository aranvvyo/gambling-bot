from decimal import Decimal,InvalidOperation
import datetime
import discord
from discord import app_commands
from discord.ext import commands
from services.apirone import SUPPORTED
from services.ui import embed, deposit_status, qr_file, money
from services.emojis import resolve_emoji


def deposit_enabled(bot):
    return bool(bot.settings.deposits_enabled and bot.settings.deposits_live_verified and bot.payments and bot.payments.live_enabled)

class DepositAddressView(discord.ui.View):
 def __init__(self,bot,owner,address,invoice,currency,amount,expires=None):
  super().__init__(timeout=900);self.bot,self.owner,self.address,self.invoice,self.currency,self.amount,self.expires=bot,owner,address,invoice,currency,amount,expires;self.message=None
  for item in self.children:
   if getattr(item,'custom_id',None)=='deposit-copy':item.emoji=resolve_emoji(bot,'note')
   elif getattr(item,'custom_id',None)=='deposit-check':item.emoji=resolve_emoji(bot,'searching')
 @discord.ui.button(label='Copy Address',style=discord.ButtonStyle.secondary,custom_id='deposit-copy')
 async def copy_address(self,it,b):
  if it.user.id!=self.owner:return await it.response.send_message(embed=embed('Private invoice','This invoice belongs to another player.',state='error'),ephemeral=True)
  row=await self.bot.db.deposit(self.invoice)
  if not row or row['discord_id']!=self.owner:return await it.response.send_message(embed=embed('Invoice unavailable','The invoice ownership check failed.',state='error'),ephemeral=True)
  # Raw only, as requested: users can long-press/select on any Discord mobile client.
  await it.response.send_message(self.address,ephemeral=True,allowed_mentions=discord.AllowedMentions.none())
 @discord.ui.button(label='Check Payment',style=discord.ButtonStyle.primary,custom_id='deposit-check')
 async def check_status(self,it,b):
  if it.user.id!=self.owner:return await it.response.send_message(embed=embed('Private invoice','This invoice belongs to another player.',state='error'),ephemeral=True)
  row=await self.bot.db.deposit(self.invoice)
  if not row or row['discord_id']!=it.user.id:return await it.response.send_message(embed=embed('Invoice unavailable','This invoice does not belong to your account.',state='error'),ephemeral=True)
  await it.response.defer()
  try: result=await self.bot.payments.reconcile(self.invoice)
  except Exception as exc:
   self.bot.logger.error('Apirone invoice refresh failed (exception_type=%s)', type(exc).__name__)
   return await it.followup.send(embed=embed('Verification delayed','Apirone could not verify this invoice. Your balance was not changed.'),ephemeral=True)
  title,message,state=deposit_status(result)
  card=deposit_card(self.bot,title,message,state,self.currency,self.amount,self.address,self.invoice,self.expires,result.get("status","unknown"))
  if self.message:
   try: await self.message.edit(embed=card,attachments=[qr_file(self.address)],view=self)
   except discord.HTTPException: await it.followup.send(embed=card,ephemeral=True)
  else: await it.followup.send(embed=card,ephemeral=True)
  if getattr(self.bot,"event_logger",None):
   self.bot.event_logger.emit('deposit','Deposit status checked',user_id=it.user.id,invoice=self.invoice,status=result.get('status'),credited=result.get('credited',False),amount=result.get('amount',0),paid_amount=result.get('paid_amount',''),remaining_amount=result.get('remaining_amount',''),reference=f"deposit:{self.invoice}:{result.get('status')}:{result.get('credited',False)}")
 async def on_error(self,it,error,item):
  self.bot.logger.error('Deposit component failed type=%s',type(error).__name__)
  try:
   card=embed('Invoice action unavailable','Could not refresh this invoice display. Use Check Payment again; any wallet credit still requires provider verification and remains idempotent.',state='error')
   if it.response.is_done():await it.followup.send(embed=card,ephemeral=True)
   else:await it.response.send_message(embed=card,ephemeral=True)
  except discord.HTTPException:pass
 async def on_timeout(self):
  for item in self.children:item.disabled=True
  if self.message:
   try:await self.message.edit(view=self)
   except discord.HTTPException:pass

def deposit_card(bot,title,description,state,currency,amount,address,invoice,expires,invoice_status="created"):
 name,network,_=SUPPORTED[currency]
 symbol={'ltc':'LTC','usdt@bnb':'USDT','usdt@eth':'USDT'}[currency]
 icon={'ltc':'ltc','usdt@bnb':'usdt_bep20','usdt@eth':'usdt_erc20'}[currency]
 e=embed(title,description,state=state)
 e.add_field(name='Asset · Network',value=f'{resolve_emoji(bot,icon)} **{name}**\n{network}',inline=True)
 e.add_field(name='Exact amount',value=f'**{amount} {symbol}**',inline=True)
 e.add_field(name='Minimum deposit',value=f'{bot.settings.min_deposit} {symbol}',inline=True)
 e.add_field(name='Payment address',value=f'`{address}`',inline=False)
 e.add_field(name='Invoice status',value=f'`{invoice_status}`',inline=False)
 if expires:
  if isinstance(expires,str):
   try: expires=datetime.datetime.fromisoformat(expires.replace('Z','+00:00'))
   except ValueError: expires=None
  if isinstance(expires,datetime.datetime):e.add_field(name='Expires',value=f'<t:{int(expires.timestamp())}:R>',inline=True)
 e.add_field(name='Instructions',value=f'Send only **{name} on {network}**. Send the exact amount. Network transfers cannot be reversed.',inline=False)
 e.set_footer(text=f'{bot.settings.casino_name} · Invoice {invoice} · Credits require verified payment')
 return e

class Deposits(commands.Cog):
 def __init__(self,bot):self.bot=bot
 @app_commands.command(name='deposit',description='Create a verified crypto invoice')
 @app_commands.choices(currency=[app_commands.Choice(name='Litecoin (LTC)',value='ltc'),app_commands.Choice(name='USDT · BNB Smart Chain (BEP20)',value='usdt@bnb'),app_commands.Choice(name='USDT · Ethereum (ERC20)',value='usdt@eth')])
 async def deposit(self,it:discord.Interaction,currency:app_commands.Choice[str],amount:str):
  if self.bot.settings.maintenance:return await it.response.send_message(embed=embed('Maintenance',self.bot.maintenance_notice,state='pending'),ephemeral=True)
  if not deposit_enabled(self.bot):return await it.response.send_message(embed=embed('Deposits unavailable','New invoices remain disabled until Apirone credentials, fresh rates, and live verification review are configured. No address was generated.',state='pending'),ephemeral=True)
  await it.response.defer(ephemeral=True,thinking=True)
  try:
   value=Decimal(amount)
   if not value.is_finite() or value<=0:raise ValueError('Enter a positive amount.')
   item=SUPPORTED[currency.value];inv=await self.bot.payments.create(it.user.id,currency.value,value,self.bot.settings.invoice_lifetime)
   qr=qr_file(inv['address'])
  except (ValueError,InvalidOperation) as e:return await it.followup.send(embed=embed('Deposit rejected',str(e),state='error'),ephemeral=True)
  except Exception as exc:
   self.bot.logger.error('Apirone invoice creation failed (exception_type=%s)', type(exc).__name__)
   return await it.followup.send(embed=embed('Invoice unavailable','Apirone could not create an invoice. No funds were credited.'),ephemeral=True)
  expires=inv.get('expire')
  title=f'{resolve_emoji(self.bot,{"ltc":"ltc","usdt@bnb":"usdt_bep20","usdt@eth":"usdt_erc20"}[currency.value])} {item[0]} deposit invoice'
  e=deposit_card(self.bot,title,'Use the exact asset, network, and amount below. Payment is verified directly with Apirone.', 'pending',currency.value,str(inv['amount_coin']),inv['address'],inv['invoice'],expires,inv.get('status','created'))
  if inv.get('invoice-url'):
   from urllib.parse import urlparse
   u=urlparse(inv['invoice-url'])
   if u.scheme=='https' and u.hostname=='apirone.com' and u.path=='/invoice':e.add_field(name='Provider invoice',value=f"[View invoice]({inv['invoice-url']})",inline=False)
  e.set_thumbnail(url='attachment://deposit-qr.png')
  view=DepositAddressView(self.bot,it.user.id,inv['address'],inv['invoice'],currency.value,str(inv['amount_coin']),expires)
  view.message=await it.followup.send(embed=e,file=qr,view=view,ephemeral=True,wait=True)
  if self.bot.event_logger:self.bot.event_logger.emit('deposit','Deposit invoice created',user_id=it.user.id,invoice=inv['invoice'],asset=currency.value,amount=str(inv['amount_coin']),status=inv['status'],reference='invoice:'+inv['invoice'])
 @app_commands.command(name='deposit-status',description='Refresh an invoice with Apirone')
 async def status(self,it,invoice_id:str):
  row=await self.bot.db.deposit(invoice_id)
  if not row or row['discord_id']!=it.user.id:return await it.response.send_message(embed=embed('Invoice not found','That invoice does not belong to your account.',state='error'),ephemeral=True)
  if not self.bot.payments:return await it.response.send_message(embed=embed('Verification unavailable','Apirone is not configured.'),ephemeral=True)
  await it.response.defer(ephemeral=True)
  try:result=await self.bot.payments.reconcile(invoice_id)
  except Exception as exc:
   self.bot.logger.error('Apirone invoice verification failed (exception_type=%s)', type(exc).__name__)
   return await it.followup.send(embed=embed('Verification delayed','Apirone verification failed; your balance was not changed.'),ephemeral=True)
  title,msg,state=deposit_status(result)
  if self.bot.event_logger:self.bot.event_logger.emit('deposit','Deposit status checked',user_id=it.user.id,invoice=invoice_id,status=result.get('status'),credited=result.get('credited',False),amount=result.get('amount',0),reference=f"deposit:{invoice_id}:{result['status']}:{result.get('credited',False)}")
  await it.followup.send(embed=embed(title,msg,state=state),ephemeral=True)
 @app_commands.command(name='deposit-history',description='Show your latest deposit invoices')
 async def history(self,it):
  rows=await self.bot.db.deposit_history(it.user.id)
  text='\n'.join(f"`{r['invoice_id']}` · **{r['currency']}** · {r['requested_amount']} · `{r['status']}`"+(f" · expires {r['expires_at']}" if r['expires_at'] else '') for r in rows) or f"No deposits yet. Use `{self.bot.active_prefix}depo` to open the deposit menu."
  await it.response.send_message(embed=embed('Deposit history',text),ephemeral=True)
async def setup(bot):await bot.add_cog(Deposits(bot))
