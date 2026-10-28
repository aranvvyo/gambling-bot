import asyncio, discord, json
from discord import app_commands
from discord.ext import commands
from services.game_math import mines_multiplier, payout
from services.fairness import mines_layout
from services.ui import embed, money, check_bet, game_is_enabled,ephemeral_send
from services.result_ui import game_result
from config import settings

class MinesView(discord.ui.View):
    def __init__(self,bot,user_id,bet,mines,session_id,tiles,fair,edge,cap):
        super().__init__(timeout=180); self.bot,self.uid,self.bet,self.mines,self.sid,self.tiles=bot,user_id,bet,mines,session_id,tiles
        self.edge=edge; self.cap=cap; self.fair=fair; self.layout=set(mines_layout(fair['digest'],tiles,mines)); self.opened=set(); self.done=False; self.lock=asyncio.Lock()
        for i in range(tiles):
            b=discord.ui.Button(label="　",style=discord.ButtonStyle.secondary,row=i//(tiles//4))
            b.callback=self.make_cb(i); self.add_item(b)
        cash=discord.ui.Button(label="Cash out",style=discord.ButtonStyle.success,row=4,emoji="💰"); cash.callback=self.cash; self.add_item(cash)
    def make_cb(self,i):
        async def cb(interaction):
            async with self.lock:
                return await self._tile(interaction, i)
        return cb
    async def _tile(self, interaction, i):
            if self.done or interaction.user.id!=self.uid: return await ephemeral_send(interaction,"This is not your game.")
            if i in self.opened: return await interaction.response.defer()
            self.opened.add(i)
            if i in self.layout:
                self.opened.add(i)
                self.done=True
                for item in self.children:
                    if isinstance(item,discord.ui.Button) and item.label=="　": item.disabled=True
                b=self.children[i]; b.label="💣"; b.style=discord.ButtonStyle.danger
                await self.finish(0,"💥 Mine hit",interaction); return
            b=self.children[i]; b.label="💎"; b.style=discord.ButtonStyle.success; b.disabled=True
            mult=mines_multiplier(self.mines,len(self.opened),self.edge,self.tiles)
            await interaction.response.edit_message(embed=embed("💎 Mines",f"Safe tiles: **{len(self.opened)}**\nCash-out multiplier: **{mult}×**\nPotential return: **{money(payout(self.bet,mult,self.cap))}**"),view=self)
    async def cash(self,interaction):
        async with self.lock:
            return await self._cash(interaction)
    async def _cash(self,interaction):
        if self.done or interaction.user.id!=self.uid: return await ephemeral_send(interaction,"This is not your game.")
        if not self.opened: return await ephemeral_send(interaction,"Reveal a safe tile first.")
        self.done=True; mult=mines_multiplier(self.mines,len(self.opened),self.edge,self.tiles); win=payout(self.bet,mult,self.cap)
        await self.finish(win,"💰 Cashed out",interaction)
    def outcome(self, win, title):
        import json
        return json.dumps({'algorithm':'casino-v1','tiles':self.tiles,'mines':self.mines,'layout':sorted(self.layout),'opened':sorted(self.opened),'payout':win,'title':title,'bet':self.bet,'edge':str(self.edge),'cap':self.cap})
    async def finish(self,win,title,interaction):
        try:
            await self.bot.db.finish_game(self.sid,win,self.outcome(win,title))
        finally:
            self.bot.active_users.discard(self.uid); self.stop()
        for i,item in enumerate(self.children):
            if isinstance(item,discord.ui.Button): item.disabled=True
            if isinstance(item,discord.ui.Button) and i<self.tiles and i in self.layout: item.label="💣"; item.style=discord.ButtonStyle.danger
        desc=f"Bet: {money(self.bet)} · Return: {money(win)}" if win else f"You lost {money(self.bet)}."
        data={"cols":4,"rows":self.tiles//4,"bombs":sorted(self.layout),"opened":sorted(self.opened),"steps":len(self.opened),"multiplier":str(mines_multiplier(self.mines,len(self.opened),self.edge,self.tiles)) if win else "0"}
        e,f=await game_result(self.bot,self.uid,"mines",outcome=title,bet=self.bet,payout=win,data=data,game_id=self.sid,fair=self.fair,won=win>0)
        await interaction.response.edit_message(embed=e,view=self,attachments=[f])


    async def on_timeout(self):
        async with self.lock:
            if not self.done:
                self.done=True
                await self.bot.db.finish_game(self.sid,0,self.outcome(0,'timeout'))
                self.bot.active_users.discard(self.uid)
                for item in self.children:
                    if isinstance(item,discord.ui.Button): item.disabled=True
                if getattr(self,'message',None):
                    try:
                        e,f=await game_result(self.bot,self.uid,'mines',outcome='Timed out · bet lost',bet=self.bet,payout=0,data={'cols':4,'rows':self.tiles//4,'bombs':sorted(self.layout),'opened':sorted(self.opened),'steps':len(self.opened),'multiplier':'0'},game_id=self.sid,fair=self.fair,won=False)
                        await self.message.edit(embed=e,view=self,attachments=[f])
                    except discord.HTTPException: pass

class Mines(commands.Cog):
    def __init__(self,bot): self.bot=bot
    @app_commands.command(name="mines",description="Play interactive Mines")
    @app_commands.choices(board=[app_commands.Choice(name="4 × 4 · 16 tiles",value=16),app_commands.Choice(name="4 × 5 · 20 tiles",value=20)])
    async def mines(self,interaction:discord.Interaction,bet:int,mines:int=3,board:app_commands.Choice[int]=None):
        tiles=board.value if board else 20
        if not 1<=mines<tiles: return await ephemeral_send(interaction,embed=embed("Invalid game","Mine count must be from 1 to board size minus one."))
        try: await check_bet(self.bot.db,interaction.user.id,bet,"mines")
        except ValueError as e: return await ephemeral_send(interaction,embed=embed("Bet rejected",str(e)))
        if not await game_is_enabled(self.bot.db,'mines'): return await ephemeral_send(interaction,embed=embed('Game disabled','Mines is currently unavailable.'))
        if self.bot.settings.maintenance: return await ephemeral_send(interaction,embed=embed("Maintenance","Games are paused."))
        if interaction.user.id in self.bot.active_users: return await ephemeral_send(interaction,embed=embed("Game in progress","Finish your current game first."))
        self.bot.active_users.add(interaction.user.id)
        try:
            await interaction.response.defer(ephemeral=True,thinking=True)
            edge=self.bot.settings.house_edge; cap=self.bot.settings.max_payout
            sid=await self.bot.db.start_game(interaction.user.id,"mines",bet,self.bot.settings.daily_bet_limit)
            fair=await self.bot.fairness.allocate(interaction.user.id,'mines'); await self.bot.db.attach_fair_round(sid,fair['round_id'])
            view=MinesView(self.bot,interaction.user.id,bet,mines,sid,tiles,fair,edge,cap)
            await interaction.edit_original_response(embed=embed("💎 Mines",f"Bet: **{money(bet)}** · Mines: **{mines}** · Board: **{tiles} tiles**\nReveal safe tiles and cash out before hitting a mine."),view=view)
            view.message=await interaction.original_response()
        except ValueError as e:
            self.bot.active_users.discard(interaction.user.id); return await interaction.edit_original_response(embed=embed('Play limit',str(e)))
        except Exception:
            if 'sid' in locals(): await self.bot.db.refund_game(sid)
            self.bot.active_users.discard(interaction.user.id); raise
async def setup(bot): await bot.add_cog(Mines(bot))
