import discord,json
from decimal import Decimal,ROUND_DOWN
from discord import app_commands
from discord.ext import commands
from services.game_math import payout
from services.ui import embed,money,check_bet,game_is_enabled,ephemeral_send
from services.result_ui import game_result
from config import settings

class Limbo(commands.Cog):
 def __init__(self,bot):self.bot=bot
 @app_commands.command(name="limbo",description="Pick a target multiplier and test your luck")
 async def limbo(self,it:discord.Interaction,bet:int,target:app_commands.Range[float,1.01,1000.0]):
  try:await check_bet(self.bot.db,it.user.id,bet,"limbo")
  except ValueError as e:return await ephemeral_send(it,embed=embed("Bet rejected",str(e)))
  if not await game_is_enabled(self.bot.db,'limbo'):return await ephemeral_send(it,embed=embed('Game disabled','Limbo is currently unavailable.'))
  if self.bot.settings.maintenance:return await ephemeral_send(it,embed=embed('Maintenance','Games are paused.'))
  if it.user.id in self.bot.active_users:return await ephemeral_send(it,embed=embed("Game in progress","Finish your active game first."))
  self.bot.active_users.add(it.user.id)
  try:
   await it.response.defer(ephemeral=True,thinking=True)
   edge=self.bot.settings.house_edge; cap=self.bot.settings.max_payout
   sid=await self.bot.db.start_game(it.user.id,"limbo",bet,self.bot.settings.daily_bet_limit)
   fair=await self.bot.fairness.allocate(it.user.id,'limbo'); await self.bot.db.attach_fair_round(sid,fair['round_id'])
   roll=Decimal(int(fair['digest'][:13],16))/Decimal(16**13)
   result=(Decimal(1)/max(roll,Decimal(1)/Decimal(16**13))).quantize(Decimal("0.01"),rounding=ROUND_DOWN)
   won=result>=Decimal(str(target))
   mult=Decimal(str(target))*(Decimal(1)-edge)
   amount=payout(bet,mult,cap) if won else 0
   await self.bot.db.finish_game(sid,amount,json.dumps({'algorithm':'casino-v1','roll':str(result),'target':str(target),'won':won,'payout':amount,'bet':bet,'edge':str(edge),'cap':cap})); self.bot.active_users.discard(it.user.id)
   e=embed("🎯 Limbo · Win" if won else "🎯 Limbo · Miss",f"Target: **{target:.2f}×**\nResult: **{result}×**\n"+(f"Return: **{money(amount)}**" if won else f"Lost {money(bet)}."),color=0x35D07F if won else 0xE34B5B)
   e,f=await game_result(self.bot,it.user.id,"limbo",outcome=(f"Target {target:.2f}x · result {result}x" if won else f"Target {target:.2f}x · result {result}x · bet lost"),bet=bet,payout=amount,data={"target":float(target),"result":float(result)},game_id=sid,fair=fair,won=won)
   await it.edit_original_response(embed=e,attachments=[f])
  except ValueError as e:
   self.bot.active_users.discard(it.user.id)
   return await it.edit_original_response(embed=embed('Bet rejected',str(e)))
  except Exception:
   if 'sid' in locals(): await self.bot.db.refund_game(sid)
   self.bot.active_users.discard(it.user.id);raise
async def setup(bot):await bot.add_cog(Limbo(bot))
