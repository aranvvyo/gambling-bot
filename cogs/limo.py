import asyncio,discord,json
from discord import app_commands
from discord.ext import commands
from services.game_math import payout,limo_multiplier
from services.fairness import derive_int
from services.ui import embed,money,check_bet,game_is_enabled,ephemeral_send
from services.result_ui import game_result
from config import settings
class LimoView(discord.ui.View):
 def __init__(self,bot,uid,bet,sid,picks,fair):
  super().__init__(timeout=45); self.bot,self.uid,self.bet,self.sid,self.picks=bot,uid,bet,sid,picks; self.fair=fair; self.edge=settings.house_edge; self.cap=settings.max_payout; self.safe=derive_int(fair['digest'],'limo-car',picks); self.done=False; self.lock=asyncio.Lock()
  for n in range(picks):
   b=discord.ui.Button(label=f'Car {n+1}',style=discord.ButtonStyle.secondary); b.callback=self.choose(n); self.add_item(b)
 def choose(self,n):
  async def cb(it):
   async with self.lock:
    return await self._choose(it,n)
  return cb
 async def _choose(self,it,n):
   if it.user.id!=self.uid:return await ephemeral_send(it,'This is not your game.')
   if self.done:return await it.response.defer()
   self.done=True; won=n==self.safe; amount=payout(self.bet,limo_multiplier(self.picks,self.edge),self.cap) if won else 0
   await self.bot.db.finish_game(self.sid,amount,self.outcome(amount,n)); self.bot.active_users.discard(self.uid); self.stop()
   for i,b in enumerate(self.children): b.disabled=True; b.label='🚘' if i==self.safe else '🚖'
   e,f=await game_result(self.bot,self.uid,'limo',outcome=f'Selected car {n+1} · limousine at car {self.safe+1}',bet=self.bet,payout=amount,data={'cols':self.picks,'rows':1,'winner':self.safe,'chosen':n},game_id=self.sid,fair=self.fair,won=won)
   await it.response.edit_message(embed=e,view=self,attachments=[f])
 def outcome(self,amount,chosen): return json.dumps({'algorithm':'casino-v1','cars':self.picks,'winner':self.safe,'chosen':chosen,'payout':amount,'bet':self.bet,'edge':str(self.edge),'cap':self.cap})
 async def on_timeout(self):
     async with self.lock:
      if not self.done:
       self.done=True; await self.bot.db.finish_game(self.sid,0,self.outcome(0,-1)); self.bot.active_users.discard(self.uid)
       for item in self.children:item.disabled=True
       if getattr(self,'message',None):
        try:
         e,f=await game_result(self.bot,self.uid,'limo',outcome='Timed out · bet lost',bet=self.bet,payout=0,data={'cols':self.picks,'rows':1,'winner':self.safe},game_id=self.sid,fair=self.fair,won=False)
         await self.message.edit(embed=e,view=self,attachments=[f])
        except discord.HTTPException: pass
class Limo(commands.Cog):
 def __init__(self,bot):self.bot=bot
 @app_commands.command(name='limo',description='Pick the limousine from a row of cars')
 async def limo(self,it,bet:app_commands.Range[int,1,1000000],cars:app_commands.Range[int,2,5]=3):
  try:await check_bet(self.bot.db,it.user.id,bet,"limo")
  except ValueError as e:return await ephemeral_send(it,embed=embed('Bet rejected',str(e)))
  if not await game_is_enabled(self.bot.db,'limo'):return await ephemeral_send(it,embed=embed('Game disabled','Limo is currently unavailable.'))
  if self.bot.settings.maintenance:return await ephemeral_send(it,embed=embed('Maintenance','Games are paused.'))
  if it.user.id in self.bot.active_users:return await ephemeral_send(it,embed=embed('Game in progress','Finish your active game first.'))
  self.bot.active_users.add(it.user.id)
  try:
   await it.response.defer(ephemeral=True,thinking=True)
   edge=self.bot.settings.house_edge; cap=self.bot.settings.max_payout
   sid=await self.bot.db.start_game(it.user.id,'limo',bet,self.bot.settings.daily_bet_limit); fair=await self.bot.fairness.allocate(it.user.id,'limo'); await self.bot.db.attach_fair_round(sid,fair['round_id']); v=LimoView(self.bot,it.user.id,bet,sid,cars,fair); v.edge=edge; v.cap=cap
   await it.edit_original_response(embed=embed('🚘 Limo',f'Choose 1 of **{cars}** cars. One is the limousine.\nWin chance: **{100/cars:.1f}%** · Return multiplier: **{limo_multiplier(cars,edge):.2f}×** · Bet {money(bet)}'),view=v); v.message=await it.original_response()
  except ValueError as e:
   self.bot.active_users.discard(it.user.id); return await it.edit_original_response(embed=embed('Play limit',str(e)))
  except Exception:
   if 'sid' in locals(): await self.bot.db.refund_game(sid)
   self.bot.active_users.discard(it.user.id);raise
async def setup(bot):await bot.add_cog(Limo(bot))
