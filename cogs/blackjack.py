import asyncio,json
from decimal import Decimal
import discord
from discord import app_commands
from discord.ext import commands
from services.game_math import deck,blackjack_value,payout
from services.ui import embed,money,check_bet,game_is_enabled,ephemeral_send
from services.result_ui import game_result
from config import settings

_RANKS={1:'A',11:'J',12:'Q',13:'K'}
def card_name(rank):return _RANKS.get(rank,str(rank))
def hand(cards):return ' '.join(f'{card_name(c)}' for c in cards)

class BlackjackView(discord.ui.View):
 def __init__(self,bot,uid,bet,sid,shoe,player,dealer,fair):
  super().__init__(timeout=120);self.bot,self.uid,self.bet,self.sid=bot,uid,bet,sid
  self.shoe,self.player,self.dealer=shoe,player,dealer;self.fair=fair;self.dealt=player+dealer;self.done=False;self.lock=asyncio.Lock();self.first_action=True
  self.hitb=discord.ui.Button(label='Hit',style=discord.ButtonStyle.primary,emoji='🃏');self.hitb.callback=self.hit;self.add_item(self.hitb)
  self.standb=discord.ui.Button(label='Stand',style=discord.ButtonStyle.secondary);self.standb.callback=self.stand;self.add_item(self.standb)
  self.doubleb=discord.ui.Button(label='Double down',style=discord.ButtonStyle.success,emoji='💰');self.doubleb.callback=self.double;self.add_item(self.doubleb)
 def draw(self):
  card=self.shoe.pop(); self.dealt.append(card); return card
 def outcome(self,out,reason='settled'):return json.dumps({'algorithm':'casino-v1','dealt':self.dealt,'player':self.player,'dealer':self.dealer,'payout':out,'bet':self.bet,'cap':getattr(self,'cap',settings.max_payout),'reason':reason})
 def render(self,reveal=False):
  dealer=hand(self.dealer) if reveal else f'{card_name(self.dealer[0])} · 🂠'
  return embed('♠ Blackjack',f'**Your hand:** {hand(self.player)} · **{blackjack_value(self.player)}**\n**Dealer:** {dealer}'+(f' · **{blackjack_value(self.dealer)}**' if reveal else ''))
 async def valid(self,it):
  if it.user.id!=self.uid:await ephemeral_send(it,'This is not your hand.');return False
  if self.done:await ephemeral_send(it,'This hand has ended.');return False
  return True
 async def hit(self,it):
  async with self.lock:
   if not await self.valid(it):return
   self.first_action=False;self.player.append(self.draw());total=blackjack_value(self.player)
   if total>=21:await self.resolve(it,'bust' if total>21 else 'stand')
   else:self.doubleb.disabled=True;await it.response.edit_message(embed=self.render(),view=self)
 async def stand(self,it):
  async with self.lock:
   if not await self.valid(it):return
   self.first_action=False;await self.resolve(it,'stand')
 async def double(self,it):
  async with self.lock:
   if not await self.valid(it):return
   if not self.first_action or len(self.player)!=2:return await ephemeral_send(it,'Double down is available only before your first hit.')
   try:await self.bot.db.start_extra_bet(self.sid,self.uid,self.bet,self.bot.settings.daily_bet_limit)
   except ValueError as e:return await ephemeral_send(it,str(e))
   self.bet*=2;self.first_action=False;self.player.append(self.draw());await self.resolve(it,'bust' if blackjack_value(self.player)>21 else 'stand')
 async def resolve(self,it,action):
  if self.done:return
  self.done=True;player=blackjack_value(self.player)
  if action!='bust':
   while blackjack_value(self.dealer)<17:self.dealer.append(self.draw())
  dealer=blackjack_value(self.dealer);natural=len(self.player)==2 and player==21;dealer_natural=len(self.dealer)==2 and dealer==21
  if action=='bust' and player>21:out=0;label='Bust · lost bet'
  elif natural and dealer_natural:out=self.bet;label='Push · both have blackjack'
  elif natural:out=payout(self.bet,Decimal('2.5'),self.cap);label='Blackjack · 3:2 profit'
  elif player==dealer:out=self.bet;label='Push · bet returned'
  elif dealer>21 or player>dealer:out=payout(self.bet,Decimal(2),self.cap);label='Win'
  else:out=0;label='Dealer wins'
  await self.bot.db.finish_game(self.sid,out,self.outcome(out));self.bot.active_users.discard(self.uid);self.stop()
  e=self.render(True);e.description+=f'\n\n**{label}** · Return **{money(out)}**'
  for c in self.children:c.disabled=True
  result_text=f"{label} · player {hand(self.player)} ({player}) · dealer {hand(self.dealer)} ({dealer})"
  e,f=await game_result(self.bot,self.uid,"blackjack",outcome=result_text,bet=self.bet,payout=out,data={"player":[card_name(c) for c in self.player],"dealer":[card_name(c) for c in self.dealer]},game_id=self.sid,fair=self.fair,won=out>0,status="push" if label.startswith("Push") else None)
  await it.response.edit_message(embed=e,view=self,attachments=[f])
 async def on_timeout(self):
     async with self.lock:
      if not self.done:
       self.done=True;await self.bot.db.finish_game(self.sid,0,self.outcome(0,'timeout'));self.bot.active_users.discard(self.uid)
       for item in self.children:item.disabled=True
       if getattr(self,'message',None):
        try:
         e,f=await game_result(self.bot,self.uid,'blackjack',outcome='Timed out · bet lost',bet=self.bet,payout=0,data={'player':[card_name(c) for c in self.player],'dealer':[card_name(c) for c in self.dealer]},game_id=self.sid,fair=self.fair,won=False)
         await self.message.edit(embed=e,view=self,attachments=[f])
        except discord.HTTPException: pass

class Blackjack(commands.Cog):
 def __init__(self,bot):self.bot=bot
 @app_commands.command(name='blackjack',description='Play blackjack: hit, stand, or double down')
 async def blackjack(self,it:discord.Interaction,bet:app_commands.Range[int,1,1000000]):
  try:await check_bet(self.bot.db,it.user.id,bet,"blackjack")
  except ValueError as e:return await ephemeral_send(it,embed=embed('Bet rejected',str(e)))
  if not await game_is_enabled(self.bot.db,'blackjack'):return await ephemeral_send(it,embed=embed('Game disabled','Blackjack is currently unavailable.'))
  if self.bot.settings.maintenance:return await ephemeral_send(it,embed=embed('Maintenance','Games are paused.'))
  if it.user.id in self.bot.active_users:return await ephemeral_send(it,embed=embed('Game in progress','Finish your active game first.'))
  self.bot.active_users.add(it.user.id)
  try:
   await it.response.defer(ephemeral=True,thinking=True)
   cap=self.bot.settings.max_payout
   sid=await self.bot.db.start_game(it.user.id,'blackjack',bet,self.bot.settings.daily_bet_limit);fair=await self.bot.fairness.allocate(it.user.id,'blackjack');await self.bot.db.attach_fair_round(sid,fair['round_id']);shoe=list(reversed(deck(fair['digest'])));player=[shoe.pop(),shoe.pop()];dealer=[shoe.pop(),shoe.pop()]
   view=BlackjackView(self.bot,it.user.id,bet,sid,shoe,player,dealer,fair); view.cap=cap
   player_nat=blackjack_value(player)==21; dealer_nat=blackjack_value(dealer)==21
   if player_nat or dealer_nat:
    from services.game_math import blackjack_return
    out=blackjack_return(bet,blackjack_value(player),blackjack_value(dealer),player_nat,dealer_nat,cap)
    await self.bot.db.finish_game(sid,out,view.outcome(out));self.bot.active_users.discard(it.user.id);view.done=True;view.stop()
    label='Push · both have blackjack' if player_nat and dealer_nat else ('Blackjack · return '+money(out) if player_nat else 'Dealer blackjack · bet lost')
    e,f=await game_result(self.bot,it.user.id,'blackjack',outcome=f'{label} · player {hand(player)} · dealer {hand(dealer)}',bet=bet,payout=out,data={'player':[card_name(c) for c in player],'dealer':[card_name(c) for c in dealer]},game_id=sid,fair=fair,won=out>0,status="push" if label.startswith("Push") else None)
    return await it.edit_original_response(embed=e,attachments=[f])
   start=view.render();start.description+=f'\nBet **{money(bet)}** · Dealer stands on 17 · Natural pays 3:2'
   await it.edit_original_response(embed=start,view=view); view.message=await it.original_response()
  except ValueError as e:
   self.bot.active_users.discard(it.user.id); return await it.edit_original_response(embed=embed('Play limit',str(e)))
  except Exception:
   if 'sid' in locals(): await self.bot.db.refund_game(sid)
   self.bot.active_users.discard(it.user.id);raise
async def setup(bot):await bot.add_cog(Blackjack(bot))
