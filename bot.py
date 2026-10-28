import asyncio, logging, os, sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands, tasks
from config import settings
from database.db import Database
from services.apirone import ApironeClient
from services.payments import PaymentService
from services.fairness import FairnessService
from services.event_logging import EventLogger
from services.process_lock import DatabaseProcessLock, ProcessAlreadyRunning
from services.ui import embed as ui_embed, bind_bot
from services.emojis import DEFAULT_EMOJIS
import json, re

MAINTENANCE_ALLOWLIST={'admin-dashboard','admin-config','admin-status','admin-maintenance','admin-maintenance-panel','admin-emoji','admin-prefix','admin-logs','admin-deposits','admin-branding','admin-economy','deposit-status','help','casino','home','balance','profile','transactions','deposit-history','limits','leaderboard','play-status','fairness','fair-verify'}

async def active_command_prefix(bot,message):
 return [bot.active_prefix,*bot.prefix_aliases]

class MaintenanceModeError(commands.CheckFailure): pass

class CasinoBot(commands.Bot):
 def __init__(self):
  intents=discord.Intents.default(); intents.message_content=True; super().__init__(command_prefix=active_command_prefix,intents=intents,help_command=None)
  self.active_prefix='.'; self.prefix_aliases=[]; self.maintenance_notice='The casino is temporarily paused for maintenance.'; self.emoji_map=DEFAULT_EMOJIS.copy(); self.started_at=__import__('time').time()
  self.check(self.maintenance_prefix_check); self.tree.interaction_check=self.maintenance_interaction_check
  self.settings=settings; self.process_lock=None; self.db=None; self.apirone=None; self.payments=None; self.fairness=None; self.event_logger=None; self.active_users=set()
  self.logger=logging.getLogger('casino')
  self.tree.on_error=self.handle_app_error
 async def on_ready(self):
  if self.event_logger and not getattr(self,'_general_event_sent',False):
   self._general_event_sent=True; self.event_logger.emit('general','Casino bot ready',bot_id=self.user.id if self.user else None,reference='bot-ready')
 async def maintenance_prefix_check(self,ctx):
  if not self.settings.maintenance or (ctx.command and ctx.command.name in MAINTENANCE_ALLOWLIST): return True
  raise MaintenanceModeError(self.maintenance_notice)
 async def maintenance_interaction_check(self,interaction):
  command=getattr(interaction,'command',None); name=getattr(command,'name','')
  if not self.settings.maintenance or name in MAINTENANCE_ALLOWLIST: return True
  interaction._casino_maintenance_handled=True
  try: await interaction.response.send_message(embed=ui_embed('Maintenance',self.maintenance_notice,state='pending'),ephemeral=True)
  except discord.HTTPException: pass
  return False
 async def on_command_error(self,ctx,error):
  if isinstance(error,commands.CommandNotFound): return
  if isinstance(error,MaintenanceModeError): message=self.maintenance_notice
  elif isinstance(error,commands.MissingRequiredArgument): message=f'Missing argument: `{error.param.name}`.'
  elif isinstance(error,commands.BadArgument): message='I could not read that user or amount. Check the command format and try again.'
  elif isinstance(error,commands.CommandOnCooldown): message=f'Please wait {error.retry_after:.1f}s before using that again.'
  elif isinstance(error,commands.CheckFailure): message='Access denied.'
  else:
   self.logger.error('Prefix command failed type=%s',type(error).__name__)
   if self.event_logger:self.event_logger.emit('error','Prefix command failed',user_id=ctx.author.id,command=ctx.command.name if ctx.command else 'unknown',error=type(error).__name__,reference=f'prefix-error:{ctx.message.id}')
   message='The command failed safely. Please try again later.'
  try: await ctx.reply(embed=__import__('services.ui',fromlist=['embed']).embed('Command unavailable',message),mention_author=False)
  except discord.HTTPException: pass
 async def handle_app_error(self,interaction,error):
  if isinstance(error,app_commands.CheckFailure):
   self.logger.warning('SECURITY_CHECK_REJECT user=%s command=%s',interaction.user.id,interaction.command.name if interaction.command else 'unknown')
   if self.event_logger:self.event_logger.emit('security','Rejected slash command',user_id=interaction.user.id,command=interaction.command.name if interaction.command else 'unknown',reference=f'check:{interaction.id}')
   message='Access denied.'
  else:
   self.logger.error('Slash command failed command=%s user=%s error_type=%s',interaction.command.name if interaction.command else 'unknown',interaction.user.id,type(error).__name__)
   if self.event_logger:self.event_logger.emit('error','Slash command failed',user_id=interaction.user.id,command=interaction.command.name if interaction.command else 'unknown',error=type(error).__name__,reference=f'error:{interaction.id}')
   message='The command failed safely. Please try again later.'
  card=ui_embed('Access denied' if isinstance(error,app_commands.CheckFailure) else 'Command unavailable',message,state='error')
  if getattr(interaction,'_casino_maintenance_handled',False): return
  try:
   if interaction.response.is_done(): await interaction.followup.send(embed=card,ephemeral=True)
   else: await interaction.response.send_message(embed=card,ephemeral=True)
  except discord.HTTPException: pass
 async def setup_hook(self):
  self.process_lock=DatabaseProcessLock(settings.database_url); self.process_lock.acquire()
  self.logger.info("Opening configured SQLite casino database; credentials are not logged.")
  self.db=await Database(settings.database_url,settings.min_bet,settings.max_bet,settings.max_payout,settings.daily_bet_limit).open(); recovered=await self.db.recover_games()
  settings.maintenance=(await self.db.get_config("maintenance",str(settings.maintenance))).lower()=="true"
  settings.casino_name=await self.db.get_config("casino_name",settings.casino_name)
  settings.currency_symbol=await self.db.get_config("currency_symbol",settings.currency_symbol)
  try: settings.daily_reward=int(await self.db.get_config("daily_reward",str(settings.daily_reward)))
  except (TypeError,ValueError): settings.daily_reward=0
  if settings.daily_reward < 0 or settings.daily_reward > settings.max_payout:
   self.logger.error("Invalid persisted daily reward; disabling the reward safely."); settings.daily_reward=0
  if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,9}",settings.currency_symbol):
   self.logger.error("Invalid persisted currency label; using VC safely."); settings.currency_symbol="VC"
  try: settings.brand_color=int(await self.db.get_config("brand_color",str(settings.brand_color)))
  except (TypeError,ValueError): pass
  self.db.maintenance_mode=settings.maintenance
  self.maintenance_notice=await self.db.get_config("maintenance_notice",self.maintenance_notice)
  prefix=await self.db.get_config("command_prefix","")
  if isinstance(prefix,str) and 1<=len(prefix)<=5 and not re.search(r'[\s@`]',prefix): self.active_prefix=prefix
  aliases=await self.db.get_config("command_prefix_aliases","[]")
  try: self.prefix_aliases=[x for x in json.loads(aliases) if isinstance(x,str) and 1<=len(x)<=5 and not re.search(r'[\s@`]',x) and x!=self.active_prefix][:5]
  except (TypeError,ValueError): self.prefix_aliases=[]
  for key,default in DEFAULT_EMOJIS.items():
   value=await self.db.get_config("emoji:"+key)
   if value is not None: self.emoji_map[key]=value
  enabled_override=await self.db.get_config("deposits_enabled")
  if enabled_override is not None: settings.deposits_enabled=(enabled_override.lower()=="true")
  if not settings.deposits_live_verified: settings.deposits_enabled=False
  color_override=await self.db.get_config("brand_color")
  bind_bot(self,int(color_override) if color_override is not None else None)
  for category in settings.log_channels:
   value=await self.db.get_config('log_channel:'+category)
   if value: settings.log_channels[category]=int(value)
  deposit_limits=await self.db.get_config('deposit_limits')
  if deposit_limits:
   try:
    from decimal import Decimal
    minimum,maximum=(Decimal(x) for x in deposit_limits.split(',',1))
    if minimum.is_finite() and maximum.is_finite() and minimum>0 and maximum>=minimum:
     settings.min_deposit=minimum;settings.max_deposit=maximum
    else: raise ValueError('invalid persisted deposit limits')
   except (ValueError,ArithmeticError):
    settings.deposits_enabled=False
    self.logger.error('Invalid persisted deposit limits; deposits disabled safely.')
  for asset,attr,ts_attr,source_attr in (
   ('ltc','rate_ltc','rate_timestamp_ltc','rate_source_ltc'),
   ('usdt@bnb','rate_bnb','rate_timestamp_bnb','rate_source_bnb'),
   ('usdt@eth','rate_eth','rate_timestamp_eth','rate_source_eth')):
   persisted=await self.db.get_config('rate:'+asset)
   if persisted is not None: setattr(settings,attr,__import__('decimal').Decimal(persisted))
   persisted_time=await self.db.get_config('rate_timestamp:'+asset)
   if persisted_time is not None: setattr(settings,ts_attr,int(persisted_time))
   persisted_source=await self.db.get_config('rate_source:'+asset)
   if persisted_source is not None: setattr(settings,source_attr,persisted_source)
  limits=await self.db.get_config('limits')
  if limits:
   settings.min_bet,settings.max_bet,settings.daily_bet_limit,settings.max_payout=map(int,limits.split(','))
   self.db.min_bet=settings.min_bet; self.db.max_bet=settings.max_bet; self.db.daily_bet_limit=settings.daily_bet_limit; self.db.max_payout=settings.max_payout
  if settings.daily_reward > settings.max_payout:
   self.logger.error("Persisted daily reward exceeds payout cap; disabling the reward safely."); settings.daily_reward=0
  edge=await self.db.get_config('house_edge')
  if edge:
   from decimal import Decimal
   settings.house_edge=Decimal(edge)
   if not Decimal(0)<=settings.house_edge<=Decimal('0.25'): raise ValueError('persisted HOUSE_EDGE is outside 0..0.25')
  self.event_logger=EventLogger(self,settings.log_channels); self.event_logger.start(); self.db.event_logger=self.event_logger
  for session in recovered:
   self.event_logger.emit('bet','Unfinished wager refunded after restart',user_id=session['discord_id'],game=session['game'],round_id=session['id'],amount=session['bet'],reference='refund:'+session['id'])
  self.fairness=FairnessService(self.db,settings.fairness_rotation_seconds,self.event_logger.publish_fairness_commitment,self.event_logger.publish_fairness_reveal)
  fair=await self.fairness.ensure_commitment(); await self.fairness.publish_commitment(fair['commitment']); await self.fairness.publish_retired_reveals()
  if settings.apirone_account and settings.apirone_key:
   self.apirone=ApironeClient(settings.apirone_account,settings.apirone_key)
   self.payments=PaymentService(self.db,self.apirone,{'ltc':settings.rate_ltc,'usdt@bnb':settings.rate_bnb,'usdt@eth':settings.rate_eth},settings.min_deposit,settings.max_deposit,settings.max_deposit_credit,{'ltc':settings.rate_timestamp_ltc,'usdt@bnb':settings.rate_timestamp_bnb,'usdt@eth':settings.rate_timestamp_eth},settings.rate_max_age_seconds,{'ltc':settings.rate_source_ltc,'usdt@bnb':settings.rate_source_bnb,'usdt@eth':settings.rate_source_eth},settings.deposits_enabled and settings.deposits_live_verified)
   self.deposit_poll.start()
  for name in ('wallet','deposits','mines','dragon_tower','blackjack','crash','limbo','limo','admin','responsible','casino','new_games','dashboard','prefix','prefix_bridge'):
   await self.load_extension(f'cogs.{name}')
  self.fairness_rotation.start()
  if settings.guild_id:
   guild=discord.Object(id=settings.guild_id); self.tree.copy_global_to(guild=guild); await self.tree.sync(guild=guild)
  else: await self.tree.sync()
 @tasks.loop(seconds=30)
 async def fairness_rotation(self):
  try:
   result=await self.fairness.ensure_commitment()
   await self.fairness.publish_commitment(result['commitment'])
   await self.fairness.publish_retired_reveals()
  except Exception: self.logger.exception('Fairness publication retry failed')
 @fairness_rotation.before_loop
 async def before_fairness_rotation(self): await self.wait_until_ready()
 @tasks.loop(seconds=max(15,settings.poll_interval))
 async def deposit_poll(self):
  for invoice in await self.db.pending_deposits():
   try:
    result=await self.payments.reconcile(invoice)
    self.event_logger.emit('deposit','Deposit status reconciled',invoice=invoice,status=result.get('status'),credited=result.get('credited',False),amount=result.get('amount',0),reason=result.get('reason',''),reference=f"deposit:{invoice}:{result.get('status')}:{result.get('credited',False)}")
   except Exception as exc: self.logger.error('Deposit poll verification failed (exception_type=%s)', type(exc).__name__)
 @deposit_poll.before_loop
 async def before_poll(self): await self.wait_until_ready()
 async def close(self):
  for loop in (self.deposit_poll,self.fairness_rotation):
   if loop.is_running():
    loop.cancel(); task=loop.get_task()
    if task:
     try: await task
     except asyncio.CancelledError: pass
  if self.apirone: await self.apirone.close()
  if self.event_logger: await self.event_logger.close()
  if self.db: await self.db.close()
  if self.process_lock: self.process_lock.release()
  await super().close()

Path('logs').mkdir(mode=0o700,exist_ok=True)
os.chmod('logs',0o700)
logging.basicConfig(level=getattr(logging,settings.log_level.upper(),logging.INFO),format='%(asctime)s %(levelname)s %(name)s %(message)s')
file_handler=RotatingFileHandler('logs/casino.log',maxBytes=2_000_000,backupCount=3,encoding='utf-8')
file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
logging.getLogger().addHandler(file_handler)
os.chmod('logs/casino.log',0o600)
async def main():
 bot=CasinoBot()
 async with bot: await bot.start(settings.token)
if __name__=='__main__':
 try:
  settings.validate()
 except ValueError as exc:
  print(f'Configuration error: {exc}',file=sys.stderr)
  raise SystemExit(2)
 try:
  asyncio.run(main())
 except ProcessAlreadyRunning:
  logging.getLogger("casino").error("Startup refused: another bot process owns this SQLite database.")
  raise SystemExit(2)
