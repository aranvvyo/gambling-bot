import discord,time
from discord import app_commands
from discord.ext import commands
from services.ui import embed
class ExclusionConfirm(discord.ui.View):
 def __init__(self,bot,uid,days):super().__init__(timeout=60);self.bot,self.uid,self.days=bot,uid,days;self.message=None
 @discord.ui.button(label='Confirm self-exclusion',style=discord.ButtonStyle.danger)
 async def confirm(self,it,b):
  if it.user.id!=self.uid:return await it.response.send_message(embed=embed('Private confirmation','This confirmation belongs to another player.',color=0xB94C52),ephemeral=True)
  until=await self.bot.db.self_exclude(self.uid,self.days)
  for c in self.children:c.disabled=True
  await it.response.edit_message(embed=embed('Self-exclusion activated',f'Play is disabled until <t:{until}:F>. This setting cannot be removed early through the bot.'),view=self)
 @discord.ui.button(label='Cancel',style=discord.ButtonStyle.secondary)
 async def cancel(self,it,b):
  if it.user.id!=self.uid:return await it.response.send_message(embed=embed('Private confirmation','This confirmation belongs to another player.',color=0xB94C52),ephemeral=True)
  for c in self.children:c.disabled=True
  await it.response.edit_message(embed=embed('Cancelled','No account restriction was changed.'),view=self)
 async def on_timeout(self):
  for item in self.children:item.disabled=True
  if self.message:
   try:await self.message.edit(view=self)
   except discord.HTTPException:pass
class Responsible(commands.Cog):
 def __init__(self,bot):self.bot=bot
 @app_commands.command(name='play-limit',description='Set a personal maximum daily wager (VC)')
 async def play_limit(self,it:discord.Interaction,amount:app_commands.Range[int,1,1000000000]):
  if amount>self.bot.settings.daily_bet_limit:return await it.response.send_message(embed=embed('Limit too high',f'Your personal cap must not exceed the configured limit of {self.bot.settings.daily_bet_limit:,} VC.'),ephemeral=True)
  await self.bot.db.set_daily_limit(it.user.id,amount)
  await it.response.send_message(embed=embed('Daily limit saved',f'Your total wagers are capped at **{amount:,} VC per UTC day**. This can only lower the configured casino limit.'),ephemeral=True)
 @app_commands.command(name='self-exclude',description='Pause your play for 1 to 365 days')
 async def self_exclude(self,it:discord.Interaction,days:app_commands.Range[int,1,365]):
  view=ExclusionConfirm(self.bot,it.user.id,days)
  await it.response.send_message(embed=embed('Confirm self-exclusion',f'Confirm to disable games and wagers for **{days} days**. This cannot be undone early through the bot.',state='pending'),view=view,ephemeral=True)
  view.message=await it.original_response()
 @app_commands.command(name='play-status',description='View your daily wager cap and exclusion status')
 async def play_status(self,it:discord.Interaction):
  ctl=await self.bot.db.play_controls(it.user.id); cap=min(self.bot.settings.daily_bet_limit,ctl['daily_limit']) if ctl and ctl['daily_limit'] else self.bot.settings.daily_bet_limit
  excluded=ctl and ctl['excluded_until'] and ctl['excluded_until']>int(time.time())
  await it.response.send_message(embed=embed('Your play limits',f'Daily wager cap: **{cap:,} VC**\nSelf-excluded: **{"Yes until <t:"+str(ctl["excluded_until"])+":F>" if excluded else "No"}**'),ephemeral=True)
async def setup(bot):await bot.add_cog(Responsible(bot))
