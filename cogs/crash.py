import asyncio,time,discord,json
from decimal import Decimal
from discord import app_commands
from discord.ext import commands
from services.game_math import payout
from services.fairness import crash_point
from services.ui import embed,money,check_bet,game_is_enabled,ephemeral_send
from services.result_ui import game_result
from config import settings
class CrashView(discord.ui.View):
 def __init__(self,bot,uid,bet,sid,point,fair,edge,cap,auto_cashout=None):
  super().__init__(timeout=3600); self.bot,self.uid,self.bet,self.sid,self.point=bot,uid,bet,sid,point; self.fair=fair; self.edge=edge; self.cap=cap; self.started=time.monotonic(); self.done=False; self.lock=asyncio.Lock(); self.message=None; self.driver=None; self.auto_cashout=Decimal(str(auto_cashout)) if auto_cashout else None
 def outcome(self,payout_amount,reason,multiplier=None): return json.dumps({'algorithm':'casino-v1','point':str(self.point),'edge':str(getattr(self,'edge',self.bot.settings.house_edge)),'payout':payout_amount,'reason':reason,'auto_cashout':str(self.auto_cashout) if self.auto_cashout else None,'multiplier':str(multiplier) if multiplier is not None else None,'bet':self.bet,'cap':getattr(self,'cap',settings.max_payout)})
 def current(self): return (Decimal(1)+Decimal(str(time.monotonic()-self.started))*Decimal('0.35')).quantize(Decimal('.01'))
 async def result_card(self,amount,reason,multiplier=None):
  e,f=await game_result(self.bot,self.uid,"crash",outcome=reason,bet=self.bet,payout=amount,data={"point":float(self.point),"result":float(multiplier or self.point),"multiplier":str(multiplier or self.point)},game_id=self.sid,fair=self.fair,won=amount>0)
  return e,f
 def card(self,mult):return embed('📈 Crash',f'Bet **{money(self.bet)}**\nLive multiplier **{mult:.2f}×**\nCash out before the curve crashes.',color=0x35D07F)
 @discord.ui.button(label='Cash out',style=discord.ButtonStyle.success,emoji='💰')
 async def cash(self,it,b):
  if it.user.id!=self.uid:return await ephemeral_send(it,'This is not your round.')
  async with self.lock:
   if self.done:return await ephemeral_send(it,'This round has ended.')
   now=self.current()
   if now>=self.point: await self.settle(it,0,True); return
   self.done=True; amount=payout(self.bet,now,getattr(self,'cap',settings.max_payout)); await self.bot.db.finish_game(self.sid,amount,self.outcome(amount,'cashout',now)); self.bot.active_users.discard(self.uid); self.stop()
   if self.driver:self.driver.cancel()
   for c in self.children:c.disabled=True
   e,f=await self.result_card(amount,f'Cashed out at {now:.2f}x',now); await it.response.edit_message(embed=e,view=self,attachments=[f])
 async def settle(self,it,amount,crashed=False):
  self.done=True; await self.bot.db.finish_game(self.sid,amount,self.outcome(amount,'cashout',self.auto_cashout)); self.bot.active_users.discard(self.uid); self.stop()
  if self.driver:self.driver.cancel()
  for c in self.children:c.disabled=True
  msg=f'Crash at **{self.point:.2f}×**. Lost **{money(self.bet)}**.' if crashed else f'Return **{money(amount)}**'
  e,f=await self.result_card(amount,msg,self.auto_cashout); await it.response.edit_message(embed=e,view=self,attachments=[f])
 async def run(self):
  try:
   while not self.done:
    await asyncio.sleep(.75)
    async with self.lock:
     if self.done: return
     current=self.current()
     if self.auto_cashout and self.auto_cashout < self.point and current >= self.auto_cashout:
      self.done=True
      amount=payout(self.bet,self.auto_cashout,self.cap)
      await self.bot.db.finish_game(self.sid,amount,self.outcome(amount,'cashout',self.auto_cashout))
      self.bot.active_users.discard(self.uid); self.stop()
      for child in self.children: child.disabled=True
      try:
       e,f=await self.result_card(amount,f'Automatic cash out at {self.auto_cashout:.2f}x',self.auto_cashout); await self.message.edit(embed=e,view=self,attachments=[f])
      except discord.HTTPException: self.bot.logger.warning('Crash auto-cashout UI update failed session=%s',self.sid)
      return
     if current >= self.point:
      self.done=True
      await self.bot.db.finish_game(self.sid,0,self.outcome(0,'crash'))
      self.bot.active_users.discard(self.uid); self.stop()
      for child in self.children: child.disabled=True
      try:
       e,f=await self.result_card(0,f'Crashed at {self.point:.2f}x',self.point); await self.message.edit(embed=e,view=self,attachments=[f])
      except discord.HTTPException: self.bot.logger.warning('Crash result UI update failed session=%s',self.sid)
      return
     try: await self.message.edit(embed=self.card(current),view=self)
     except discord.HTTPException: self.bot.logger.warning('Crash live UI update failed session=%s',self.sid)
  except asyncio.CancelledError:
   return
  except Exception:
   self.bot.logger.exception('Crash engine failed session=%s',self.sid)
   if not self.done:
    self.done=True
    try: await self.bot.db.refund_game(self.sid,'refunded after engine error')
    except Exception: self.bot.logger.exception('Crash engine refund failed session=%s',self.sid)
    self.bot.active_users.discard(self.uid); self.stop()
 async def on_timeout(self):
     async with self.lock:
      if not self.done:
       self.done=True; await self.bot.db.finish_game(self.sid,0,self.outcome(0,'timeout')); self.bot.active_users.discard(self.uid)
       if self.driver:self.driver.cancel()
       for item in self.children:item.disabled=True
       if getattr(self,'message',None):
        try:
         e,f=await self.result_card(0,'Timed out · bet lost',self.point); await self.message.edit(embed=e,view=self,attachments=[f])
        except discord.HTTPException: pass
class Crash(commands.Cog):
 def __init__(self,bot):self.bot=bot
 @app_commands.command(name='crash',description='Open a server-controlled Crash round')
 async def crash(self,it,bet:app_commands.Range[int,1,1000000],auto_cashout:float=0.0):
  try:await check_bet(self.bot.db,it.user.id,bet,"crash")
  except ValueError as e:return await ephemeral_send(it,embed=embed('Bet rejected',str(e)))
  if auto_cashout and not 1.1<=auto_cashout<=1000:return await ephemeral_send(it,embed=embed('Invalid auto cash-out','Choose a multiplier from 1.1× to 1000×.'))
  if not await game_is_enabled(self.bot.db,'crash'):return await ephemeral_send(it,embed=embed('Game disabled','Crash is currently unavailable.'))
  if self.bot.settings.maintenance:return await ephemeral_send(it,embed=embed('Maintenance','Games are paused.'))
  if it.user.id in self.bot.active_users:return await ephemeral_send(it,embed=embed('Game in progress','Finish your current game first.'))
  self.bot.active_users.add(it.user.id)
  try:
   await it.response.defer(ephemeral=True,thinking=True)
   edge=self.bot.settings.house_edge; cap=self.bot.settings.max_payout
   sid=await self.bot.db.start_game(it.user.id,'crash',bet,self.bot.settings.daily_bet_limit); fair=await self.bot.fairness.allocate(it.user.id,'crash'); await self.bot.db.attach_fair_round(sid,fair['round_id']); view=CrashView(self.bot,it.user.id,bet,sid,crash_point(fair['digest'],float(edge)),fair,edge,cap,auto_cashout or None)
   await it.edit_original_response(embed=view.card(Decimal('1.00')),view=view)
   view.message=await it.original_response(); view.driver=asyncio.create_task(view.run())
  except ValueError as e:
   self.bot.active_users.discard(it.user.id); return await it.edit_original_response(embed=embed('Play limit',str(e)))
  except Exception:
   if 'sid' in locals(): await self.bot.db.refund_game(sid)
   self.bot.active_users.discard(it.user.id);raise
async def setup(bot):await bot.add_cog(Crash(bot))
