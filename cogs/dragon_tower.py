import asyncio,discord,json
from discord import app_commands
from discord.ext import commands
from services.game_math import tower_multiplier,payout
from services.fairness import safe_path
from services.ui import embed,money,check_bet,game_is_enabled,ephemeral_send
from services.result_ui import game_result
from config import settings

class TowerView(discord.ui.View):
 def __init__(self,bot,uid,bet,floors,choices,sid,fair):
  super().__init__(timeout=180); self.bot,self.uid,self.bet,self.floors,self.choices,self.sid=bot,uid,bet,floors,choices,sid; self.edge=settings.house_edge; self.cap=settings.max_payout; self.floor=0; self.done=False; self.fair=fair; self.path=safe_path(fair['digest'],floors,choices); self.chosen=[]; self.safe=self.path[0]; self.lock=asyncio.Lock()
  for i in range(choices):
   b=discord.ui.Button(label=f"Path {i+1}",style=discord.ButtonStyle.primary,row=0); b.callback=self.pick(i); self.add_item(b)
  c=discord.ui.Button(label="Cash out",style=discord.ButtonStyle.success,row=1); c.callback=self.cash; self.add_item(c)
 def pick(self,index):
  async def cb(it):
   async with self.lock:
    return await self._pick(it,index)
  return cb
 async def _pick(self,it,index):
   if it.user.id!=self.uid or self.done: return await ephemeral_send(it,"This is not your game.")
   self.chosen.append(index)
   if index!=self.safe:
    self.done=True; await self.settle(0,"🐉 The tower claimed your bet.",it); return
   self.floor+=1
   if self.floor>=self.floors:
    self.done=True; await self.settle(payout(self.bet,tower_multiplier(self.floor,self.choices,self.edge),self.cap),"🏆 Tower conquered!",it); return
   self.safe=self.path[self.floor]
   mult=tower_multiplier(self.floor,self.choices,self.edge)
   await it.response.edit_message(embed=embed("🐉 Dragon Tower",f"Safe floor: **{self.floor}/{self.floors}**\nCurrent multiplier: **{mult}×**\nPotential return: **{money(payout(self.bet,mult,self.cap))}**"),view=self)
 async def cash(self,it):
  async with self.lock:
   return await self._cash(it)
 async def _cash(self,it):
  if it.user.id!=self.uid or self.done: return await ephemeral_send(it,"This is not your game.")
  if self.floor<1:return await ephemeral_send(it,"Climb at least one floor before cashing out.")
  self.done=True; await self.settle(payout(self.bet,tower_multiplier(self.floor,self.choices,self.edge),self.cap),"💰 Cashed out",it)
 def outcome(self,amount,title): return json.dumps({'algorithm':'casino-v1','steps_total':self.floors,'choices':self.choices,'safe_path':self.path,'chosen_path':self.chosen,'steps':self.floor,'payout':amount,'title':title,'bet':self.bet,'edge':str(self.edge),'cap':self.cap})
 async def settle(self,amount,title,it):
  await self.bot.db.finish_game(self.sid,amount,self.outcome(amount,title)); self.bot.active_users.discard(self.uid); self.stop()
  data={"cols":self.choices,"rows":self.floors,"safe_path":self.path,"chosen_path":self.chosen,"steps":self.floor,"multiplier":str(tower_multiplier(self.floor,self.choices,self.edge)) if amount else "0"}
  e,f=await game_result(self.bot,self.uid,"dragon-tower",outcome=title,bet=self.bet,payout=amount,data=data,game_id=self.sid,fair=self.fair,won=amount>0)
  await it.response.edit_message(embed=e,view=None,attachments=[f])
 async def on_timeout(self):
     async with self.lock:
      if not self.done:
       self.done=True; await self.bot.db.finish_game(self.sid,0,self.outcome(0,'timeout')); self.bot.active_users.discard(self.uid)
       for item in self.children:item.disabled=True
       if getattr(self,'message',None):
        try:
         e,f=await game_result(self.bot,self.uid,'dragon-tower',outcome='Timed out · bet lost',bet=self.bet,payout=0,data={'cols':self.choices,'rows':self.floors,'safe_path':self.path,'chosen_path':self.chosen,'steps':self.floor,'multiplier':'0'},game_id=self.sid,fair=self.fair,won=False)
         await self.message.edit(embed=e,view=self,attachments=[f])
        except discord.HTTPException: pass
class DragonTower(commands.Cog):
 def __init__(self,bot):self.bot=bot
 @app_commands.command(name="dragon-tower",description="Climb the Dragon Tower")
 @app_commands.choices(difficulty=[app_commands.Choice(name="Easy · 2 paths",value=2),app_commands.Choice(name="Hard · 3 paths",value=3)])
 async def dragon_tower(self,it:discord.Interaction,bet:int,difficulty:app_commands.Choice[int],floors:app_commands.Range[int,1,12]=5):
  try:await check_bet(self.bot.db,it.user.id,bet,"dragon_tower")
  except ValueError as e:return await ephemeral_send(it,embed=embed("Bet rejected",str(e)))
  if not await game_is_enabled(self.bot.db,'dragon_tower'):return await ephemeral_send(it,embed=embed('Game disabled','Dragon Tower is currently unavailable.'))
  if self.bot.settings.maintenance:return await ephemeral_send(it,embed=embed('Maintenance','Games are paused.'))
  if it.user.id in self.bot.active_users:return await ephemeral_send(it,embed=embed("Game in progress","Finish your active game first."))
  self.bot.active_users.add(it.user.id)
  try:
   await it.response.defer(ephemeral=True,thinking=True)
   edge=self.bot.settings.house_edge; cap=self.bot.settings.max_payout
   sid=await self.bot.db.start_game(it.user.id,"dragon_tower",bet,self.bot.settings.daily_bet_limit); fair=await self.bot.fairness.allocate(it.user.id,'dragon_tower'); await self.bot.db.attach_fair_round(sid,fair['round_id']); v=TowerView(self.bot,it.user.id,bet,floors,difficulty.value,sid,fair); v.edge=edge; v.cap=cap
   await it.edit_original_response(embed=embed("🐉 Dragon Tower",f"Bet {money(bet)} · {floors} floors · {difficulty.name}\nPick a safe path to climb; cash out any time."),view=v); v.message=await it.original_response()
  except ValueError as e:
   self.bot.active_users.discard(it.user.id); return await it.edit_original_response(embed=embed('Play limit',str(e)))
  except Exception:
   if 'sid' in locals(): await self.bot.db.refund_game(sid)
   self.bot.active_users.discard(it.user.id);raise
async def setup(bot):await bot.add_cog(DragonTower(bot))
