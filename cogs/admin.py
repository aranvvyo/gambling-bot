import discord
from discord import app_commands
from discord.ext import commands
from services.ui import embed

class Admin(commands.Cog):
 def __init__(self,bot): self.bot=bot
 async def authorized(self,it,owner=False):
  s=self.bot.settings
  configured_owner=it.user.id in s.owners
  configured_admin=it.user.id in s.admins
  guild_admin=bool(it.guild and getattr(getattr(it.user,"guild_permissions",None),"administrator",False))
  ok=configured_owner if owner else (configured_owner or configured_admin or guild_admin)
  if owner and not configured_owner: ok=False
  if s.admin_channel_id and getattr(it.channel,'id',None)!=s.admin_channel_id: ok=False
  if not ok:
   self.bot.logger.warning('SECURITY_REJECT user=%s command=%s channel=%s',it.user.id,it.command.name if it.command else 'unknown',getattr(it.channel,'id',0))
   if self.bot.event_logger:self.bot.event_logger.emit('security','Rejected admin command',user_id=it.user.id,command=it.command.name if it.command else 'unknown',channel_id=getattr(it.channel,'id',0),reference=f'reject:{it.id}')
   if not it.response.is_done(): await it.response.send_message(embed=embed('Access denied','This private administrative action is unavailable here.'),ephemeral=True)
  return ok
 @app_commands.command(name='admin-credit',description='Record an audited wallet correction')
 async def credit(self,it:discord.Interaction,user:discord.User,amount:int,reason:str):
  if not await self.authorized(it):return
  if amount==0 or abs(amount)>self.bot.settings.max_payout:return await it.response.send_message(embed=embed('Invalid adjustment','Amount outside the allowed range.'),ephemeral=True)
  try: bal=await self.bot.db.change_balance(user.id,amount,'admin_adjustment',f'admin:{it.id}',f'by {it.user.id}: {reason[:180]}')
  except ValueError as e:return await it.response.send_message(embed=embed('Adjustment rejected',str(e)),ephemeral=True)
  await self.bot.db.audit_admin(it.user.id,'wallet_adjustment',f'target={user.id},amount={amount},reason={reason[:180]}')
  if self.bot.event_logger:self.bot.event_logger.emit('admin','Wallet adjustment',admin_id=it.user.id,target_user_id=user.id,amount=amount,reason=reason[:120],reference=f'admin:{it.id}')
  self.bot.logger.warning('ADMIN_ADJUSTMENT admin=%s target=%s amount=%s',it.user.id,user.id,amount)
  await it.response.send_message(embed=embed('Adjustment recorded',f'{user.mention}: {amount:+,} VC\nNew balance: **{bal:,} VC**'),ephemeral=True)
 @app_commands.command(name='admin-status',description='View bot maintenance and payment readiness')
 async def status(self,it):
  if not await self.authorized(it):return
  s=self.bot.settings
  issues=await self.bot.db.reconcile_balances()
  await it.response.send_message(embed=embed('Casino diagnostics',f"Maintenance: **{s.maintenance}**\nApirone configured: **{bool(self.bot.payments)}**\nWithdrawals enabled: **{s.withdrawals_enabled}**\nLedger discrepancies: **{len(issues)}**\nFair rotation: **{s.fairness_rotation_seconds}s**"),ephemeral=True)
 @app_commands.command(name='admin-maintenance',description='Pause or resume casino games and deposits')
 async def maintenance(self,it:discord.Interaction,enabled:bool):
  if not await self.authorized(it):return
  from cogs.dashboard import MaintenanceConfirmView,send_view
  await send_view(it,embed('Confirm maintenance change',f"Set maintenance to **{'ON' if enabled else 'OFF'}**? Active game rounds can still settle."),MaintenanceConfirmView(self.bot,it.user.id,enabled))
 @app_commands.command(name='admin-limits',description='Update runtime wager and payout limits')
 async def limits(self,it:discord.Interaction,min_bet:app_commands.Range[int,1,1000000],max_bet:app_commands.Range[int,0,1000000],daily_limit:app_commands.Range[int,1,100000000],max_payout:app_commands.Range[int,1,1000000000]):
  if not await self.authorized(it):return
  if (max_bet and max_bet<min_bet) or daily_limit<min_bet or self.bot.settings.daily_reward>max_payout or (max_bet and (daily_limit<max_bet or max_payout<max_bet)):return await it.response.send_message(embed=embed('Invalid limits','Require min bet ≤ any configured per-bet cap, daily limit, and payout cap; current daily reward must also fit the payout cap.'),ephemeral=True)
  await self.bot.db.set_config('limits',f'{min_bet},{max_bet},{daily_limit},{max_payout}',it.user.id)
  s=self.bot.settings;s.min_bet=min_bet;s.max_bet=max_bet;s.daily_bet_limit=daily_limit;s.max_payout=max_payout
  self.bot.db.min_bet=min_bet;self.bot.db.max_bet=max_bet;self.bot.db.daily_bet_limit=daily_limit;self.bot.db.max_payout=max_payout
  if self.bot.event_logger:self.bot.event_logger.emit('admin','Wager limits changed',admin_id=it.user.id,min_bet=min_bet,max_bet=max_bet,daily_limit=daily_limit,max_payout=max_payout,reference=f'limits:{it.id}')
  self.bot.logger.warning('ADMIN_LIMITS admin=%s min=%s max=%s daily=%s payout=%s',it.user.id,min_bet,max_bet,daily_limit,max_payout)
  cap=f'{max_bet:,} VC' if max_bet else 'none'
  await it.response.send_message(embed=embed('Limits updated',f'Bet: minimum {min_bet:,} VC · per-bet cap: {cap} · daily: {daily_limit:,} VC · payout cap: {max_payout:,} VC.'),ephemeral=True)
 @app_commands.command(name='admin-withdrawals',description='Keep withdrawals disabled or inspect activation guard')
 async def withdrawals(self,it:discord.Interaction,enabled:bool):
  if not await self.authorized(it,owner=True):return
  if enabled:return await it.response.send_message(embed=embed('Withdrawals unavailable','Withdrawals are locked off: no verified execution provider and reconciliation adapter is configured.'),ephemeral=True)
  await self.bot.db.set_config('withdrawals_enabled','false',it.user.id)
  self.bot.settings.withdrawals_enabled=False
  await it.response.send_message(embed=embed('Withdrawals disabled','The audited configuration remains disabled.'),ephemeral=True)
 @app_commands.command(name='admin-game',description='Enable or disable a named game')
 @app_commands.choices(game=[app_commands.Choice(name=x.replace('_',' ').title(),value=x) for x in ('mines','blackjack','dragon_tower','crash','limo','limbo','dice','chicken-road','pump')])
 async def game_toggle(self,it:discord.Interaction,game:app_commands.Choice[str],enabled:bool):
  if not await self.authorized(it):return
  await self.bot.db.set_config('game_enabled:'+game.value,str(enabled).lower(),it.user.id)
  if self.bot.event_logger:self.bot.event_logger.emit('admin','Game availability changed',admin_id=it.user.id,game=game.value,enabled=enabled,reference=f'game:{it.id}')
  await it.response.send_message(embed=embed('Game availability updated',f'**{game.name}** is now **{"enabled" if enabled else "disabled"}**. Active rounds continue under their original rules.'),ephemeral=True)
 @app_commands.command(name='admin-house-edge',description='Set disclosed global house edge (0–25 percent)')
 async def house_edge(self,it:discord.Interaction,percent:app_commands.Range[float,0.0,25.0]):
  if not await self.authorized(it):return
  from decimal import Decimal
  edge=Decimal(str(percent))/100
  await self.bot.db.set_config('house_edge',str(edge),it.user.id)
  self.bot.settings.house_edge=edge
  if self.bot.event_logger:self.bot.event_logger.emit('admin','Disclosed house edge changed',admin_id=it.user.id,percent=percent,reference=f'edge:{it.id}')
  await it.response.send_message(embed=embed('Disclosed house edge updated',f'Global edge is now **{percent:.2f}%**. It is shown in game rules and applies to new rounds.'),ephemeral=True)
 @app_commands.command(name='admin-log-channel',description='Route an audit event type to a private Discord channel')
 @app_commands.choices(category=[app_commands.Choice(name=x.title(),value=x) for x in ('general','withdrawal','wins','loss','deposit','bet','admin','security','error','fairness')])
 async def log_channel(self,it:discord.Interaction,category:app_commands.Choice[str],channel:discord.TextChannel):
  if not await self.authorized(it,owner=True):return
  await self.bot.db.set_config('log_channel:'+category.value,str(channel.id),it.user.id)
  self.bot.settings.log_channels[category.value]=channel.id
  self.bot.event_logger.channels=self.bot.settings.log_channels
  if category.value=='fairness':
   current=await self.bot.fairness.ensure_commitment()
   await self.bot.fairness.publish_commitment(current['commitment'],force=True)
  if self.bot.event_logger:self.bot.event_logger.emit('admin','Audit channel changed',admin_id=it.user.id,category=category.value,channel_id=channel.id,reference=f'logroute:{it.id}')
  await it.response.send_message(embed=embed('Audit route updated',f'{category.name} events now route to {channel.mention}. Database audit recorded.'),ephemeral=True)
 @app_commands.command(name='admin-rate',description='Set a disclosed VC conversion rate with source and timestamp')
 @app_commands.choices(asset=[app_commands.Choice(name='Litecoin (LTC)',value='ltc'),app_commands.Choice(name='USDT · BEP20 / BNB Smart Chain',value='usdt@bnb'),app_commands.Choice(name='USDT · ERC20 / Ethereum',value='usdt@eth')])
 async def rate(self,it:discord.Interaction,asset:app_commands.Choice[str],vc_per_coin:app_commands.Range[float,0.0,1000000000000.0],source:str):
  if not await self.authorized(it,owner=True):return
  source=source.strip()[:100]
  if not source:return await it.response.send_message(embed=embed('Invalid rate','Provide a short rate source or policy reference.'),ephemeral=True)
  import time
  from decimal import Decimal
  key=asset.value; value=Decimal(str(vc_per_coin)); now=int(time.time())
  names={'ltc':('rate_ltc','rate_timestamp_ltc','rate_source_ltc'),'usdt@bnb':('rate_bnb','rate_timestamp_bnb','rate_source_bnb'),'usdt@eth':('rate_eth','rate_timestamp_eth','rate_source_eth')}
  rate_attr,time_attr,source_attr=names[key]
  await self.bot.db.set_configs({'rate:'+key:str(value),'rate_timestamp:'+key:str(now),'rate_source:'+key:source},it.user.id,'deposit_rate_update')
  setattr(self.bot.settings,rate_attr,value); setattr(self.bot.settings,time_attr,now); setattr(self.bot.settings,source_attr,source)
  if self.bot.payments:
   self.bot.payments.rates[key]=value; self.bot.payments.rate_updated_at[key]=now; self.bot.payments.rate_sources[key]=source
  if self.bot.event_logger:self.bot.event_logger.emit('admin','Deposit conversion rate changed',admin_id=it.user.id,asset=key,vc_per_coin=str(value),source_configured=bool(source),updated_at=now,reference=f'rate:{it.id}')
  await it.response.send_message(embed=embed('Conversion rate updated',f'**{key}**: {value} VC per coin\nSource: {source}\nTimestamp: <t:{now}:R> · freshness window {self.bot.settings.rate_max_age_seconds}s.'),ephemeral=True)
 @app_commands.command(name='admin-config',description='Open the private casino configuration dashboard')
 async def config_panel(self,it):
  if not await self.authorized(it):return
  from cogs.dashboard import DashboardView,overview_embed,send_view
  await send_view(it,overview_embed(self.bot),DashboardView(self.bot,it.user.id))
async def setup(bot): await bot.add_cog(Admin(bot))
