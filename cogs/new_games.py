from decimal import Decimal
import asyncio,json,io
import discord
from discord import app_commands
from discord.ext import commands
from games.math import dice_result, chicken_safe_tile, chicken_multiplier, pump_crash_point
from services.game_math import payout
from services.fairness import unit_float
from services.ui import embed, money, check_bet, game_is_enabled,ephemeral_send
from services.result_ui import game_result


class RoadView(discord.ui.View):
    def __init__(self, cog, interaction, sid, fair, bet, game, edge, cap):
        super().__init__(timeout=120); self.cog=cog; self.uid=interaction.user.id; self.sid=sid; self.fair=fair; self.bet=bet; self.game=game; self.step=0; self.chosen=[]; self.attempted=None; self.done=False; self.lock=asyncio.Lock(); self.edge=edge; self.cap=cap
        if game=='chicken-road': self.safe=chicken_safe_tile(fair['digest'],0); self.remove_item(self.inflate)
        else: self.crash=pump_crash_point(fair['digest'],self.edge); self.mult=Decimal('1.00'); self.remove_item(self.t0); self.remove_item(self.t1); self.remove_item(self.t2)
    async def interaction_check(self,it):
        if it.user.id!=self.uid: await ephemeral_send(it,'This game belongs to another player.'); return False
        if self.done: await ephemeral_send(it,'This round has already ended.'); return False
        return True
    async def conclude(self,it,won,pay,reason):
        if self.done: return
        self.done=True
        for child in self.children: child.disabled=True
        await self.cog.bot.db.finish_game(self.sid,pay,self.outcome(pay,reason))
        if self.cog.bot.event_logger:self.cog.bot.event_logger.emit('bet','Game round settled',user_id=self.uid,game=self.game,round_id=self.sid,amount=self.bet,payout=pay,outcome=reason,reference='settle:'+self.sid)
        if pay>self.bet and self.cog.bot.event_logger:self.cog.bot.event_logger.emit('wins','Verified game payout',user_id=self.uid,game=self.game,round_id=self.sid,amount=pay,reference='win:'+self.sid)
        data=json.loads(self.outcome(pay,reason))
        if self.game=="chicken-road": data.update({"safe_path":data.get("safe_path",[]),"chosen_path":data.get("chosen_path",[]),"steps":self.step,"cols":3,"rows":5})
        else: data.update({"point":str(self.crash),"result":str(self.mult),"attempted":str(self.attempted or 0),"multiplier":str(self.mult),"cols":5,"rows":3})
        e,f=await game_result(self.cog.bot,self.uid,self.game,outcome=reason,bet=self.bet,payout=pay,data=data,game_id=self.sid,fair=self.fair,won=won)
        await it.response.edit_message(embed=e,view=self,attachments=[f])
    def outcome(self,pay,reason):
        if self.game=='chicken-road':
            path=[chicken_safe_tile(self.fair['digest'],i) for i in range(5)]
            data={'steps_total':5,'choices':3,'safe_path':path,'chosen_path':self.chosen,'steps':self.step}
        else:
            data={'point':str(self.crash),'edge':str(self.edge),'cap':'100','attempted':str(self.attempted)}
        data.update({'algorithm':'casino-v1','payout':pay,'reason':reason,'bet':self.bet,'cap':self.cap,'edge':str(self.edge),'multiplier':str(self.mult) if self.game=='pump' else None})
        return json.dumps(data)
    async def on_timeout(self):
        async with self.lock:
            if not self.done:
                self.done=True
                try:
                    await self.cog.bot.db.finish_game(self.sid,0,self.outcome(0,'expired without cashout'))
                except Exception: self.cog.bot.logger.exception('Game timeout settlement failed session=%s',self.sid)
                for item in self.children:item.disabled=True
                if getattr(self,'message',None):
                    try:
                        if self.game=='chicken-road': data={'cols':3,'rows':5,'safe_path':[chicken_safe_tile(self.fair['digest'],i) for i in range(5)],'chosen_path':self.chosen,'steps':self.step,'multiplier':'0'}
                        else: data={'point':float(self.crash),'result':float(self.mult),'multiplier':str(self.mult),'attempted':str(self.attempted or 0)}
                        e,f=await game_result(self.cog.bot,self.uid,self.game,outcome='Timed out · bet lost',bet=self.bet,payout=0,data=data,game_id=self.sid,fair=self.fair,won=False)
                        await self.message.edit(embed=e,view=self,attachments=[f])
                    except discord.HTTPException: pass
    @discord.ui.button(label='Tile 1',style=discord.ButtonStyle.success,row=0)
    async def t0(self,it,b): await self.choose(it,0)
    @discord.ui.button(label='Tile 2',style=discord.ButtonStyle.success,row=0)
    async def t1(self,it,b): await self.choose(it,1)
    @discord.ui.button(label='Tile 3',style=discord.ButtonStyle.success,row=0)
    async def t2(self,it,b): await self.choose(it,2)
    async def choose(self,it,tile):
        async with self.lock:
            return await self._choose(it,tile)
    async def _choose(self,it,tile):
        if self.game!='chicken-road': return await ephemeral_send(it,'Not available in this game.')
        safe=chicken_safe_tile(self.fair['digest'],self.step)
        self.chosen.append(tile)
        if tile!=safe: return await self.conclude(it,False,0,f'Wrong tile at step {self.step+1}. Bet lost.')
        self.step+=1
        if self.step>=5:
            m=chicken_multiplier(self.step,edge=self.edge); return await self.conclude(it,True,payout(self.bet,m,self.cap),f'Completed 5 safe steps at **{m}×**.')
        self.safe=chicken_safe_tile(self.fair['digest'],self.step)
        m=chicken_multiplier(self.step)
        await it.response.edit_message(embed=embed('🐔 Chicken Road · Safe step',f'Steps: **{self.step}/5**\nMultiplier: **{m}×**\nCash out: **{money(payout(self.bet,m,self.cap))}**'),view=self)
    @discord.ui.button(label='Cash out',style=discord.ButtonStyle.primary,row=1)
    async def cash(self,it,b):
        async with self.lock:
            return await self._cash(it)
    async def _cash(self,it):
        if self.game=='chicken-road':
            if not self.step:return await ephemeral_send(it,'Reach a safe step before cashing out.')
            m=chicken_multiplier(self.step)
        else: m=self.mult
        await self.conclude(it,True,payout(self.bet,m,self.cap),f'Cashed out at **{m}×**.')
    @discord.ui.button(label='Pump +0.25×',style=discord.ButtonStyle.success,row=1)
    async def inflate(self,it,b):
        async with self.lock:
            return await self._inflate(it)
    async def _inflate(self,it):
        if self.game!='pump': return await ephemeral_send(it,'Not available in this game.')
        next_mult=self.mult+Decimal('0.25')
        if next_mult>=self.crash:
            self.attempted=next_mult
            await self.conclude(it,False,0,f'Pump burst before **{next_mult}×**. Bet lost.')
        else:
            self.mult=next_mult
            await it.response.edit_message(embed=embed('📈 Pump · Rising',f'Current multiplier: **{self.mult}×**\nPotential return: **{money(payout(self.bet,self.mult,self.cap))}**\nBurst point remains hidden until settlement.'),view=self)

class NewGames(commands.Cog):
    def __init__(self,bot): self.bot=bot
    async def allowed(self,it,bet,game):
        if self.bot.settings.maintenance: await ephemeral_send(it,embed=embed('Maintenance','Games are paused.')); return False
        if not await game_is_enabled(self.bot.db,game): await ephemeral_send(it,embed=embed('Game disabled',f'{game} is currently unavailable.')); return False
        try: await check_bet(self.bot.db,it.user.id,bet,game)
        except ValueError as e: await ephemeral_send(it,embed=embed('Bet rejected',str(e))); return False
        return True
    @app_commands.command(name='dice',description='Bet under or over a target roll')
    @app_commands.choices(direction=[app_commands.Choice(name='Under',value='under'),app_commands.Choice(name='Over',value='over')])
    async def dice(self,it:discord.Interaction,bet:app_commands.Range[int,1,1000000],direction:app_commands.Choice[str],target:app_commands.Range[int,1,99]):
        if not await self.allowed(it,bet,"dice"): return
        await it.response.defer(ephemeral=True,thinking=True)
        try:
            edge=self.bot.settings.house_edge; cap=self.bot.settings.max_payout
            sid=await self.bot.db.start_game(it.user.id,'dice',bet,self.bot.settings.daily_bet_limit)
            fair=await self.bot.fairness.allocate(it.user.id,'dice')
            await self.bot.db.attach_fair_round(sid,fair['round_id'])
            roll,won,mult,prob=dice_result(fair['digest'],direction.value,target,edge)
            amount=payout(bet,mult,cap) if won else 0
            await self.bot.db.finish_game(sid,amount,json.dumps({'algorithm':'casino-v1','roll':roll,'won':won,'target':target,'direction':direction.value,'edge':str(edge),'payout':amount,'bet':bet,'cap':cap}))
            if self.bot.event_logger:self.bot.event_logger.emit('bet','Dice round settled',user_id=it.user.id,game='dice',round_id=sid,bet=bet,payout=amount,reference='settle:'+sid)
            if amount>bet and self.bot.event_logger:self.bot.event_logger.emit('wins','Verified game payout',user_id=it.user.id,game='dice',round_id=sid,amount=amount,reference='win:'+sid)
            e=embed('🎲 Dice · '+('Win' if won else 'Loss'),f'Roll: **{roll}** · {direction.value} **{target}**\nWin chance: **{prob*100:.2f}%** · Multiplier: **{mult}×**\nBet: **{money(bet)}** · Return: **{money(amount)}**\nFair round: `{fair["round_id"]}` · Commitment: `{fair["commitment"][:16]}…`',color=0x35D07F if won else 0xE34B5B)
            e,f=await game_result(self.bot,it.user.id,"dice",outcome=f"Roll {roll} · {direction.value} {target} · {'won' if won else 'lost'}",bet=bet,payout=amount,data={"roll":roll,"target":target,"direction":direction.value},game_id=sid,fair=fair,won=won)
            await it.edit_original_response(embed=e,attachments=[f])
        except ValueError as e:
            if 'sid' in locals(): await self.bot.db.refund_game(sid)
            await it.edit_original_response(embed=embed('Bet rejected',str(e)))

    @app_commands.command(name='fairness',description='View the active server-seed commitment')
    async def fairness_status(self,it:discord.Interaction):
        await it.response.defer(ephemeral=True,thinking=True)
        info=await self.bot.fairness.ensure_commitment(); await self.bot.fairness.publish_commitment(info['commitment'])
        await it.edit_original_response(embed=embed('Provably fair commitment',f"Active server-seed SHA-256: `{info['commitment']}`\nRotation interval: **30 minutes**. Seeds reveal only after rotation and every associated round settles.\nVerify a round with `/fair-verify`."))
    @app_commands.command(name='fair-verify',description='Publicly verify a completed revealed fair round')
    async def fairness_verify(self,it:discord.Interaction,round_id:str):
        result=await self.bot.fairness.verify(round_id)
        if result is None:return await ephemeral_send(it,embed=embed('Not yet verifiable','The round has not settled or its server seed is still active.'))
        record={key:result[key] for key in ('id','game','discord_id','client_seed','nonce','result_digest','outcome','created_at','commitment','revealed_seed') if key in result}
        file=discord.File(io.BytesIO(json.dumps(record,sort_keys=True,indent=2).encode()),filename='fair-round-verification.json')
        e=embed('Public fairness verification',f"Valid: **{result['valid']}**\nCommitment valid: **{result['commitment_valid']}** · Digest valid: **{result['digest_valid']}** · Outcome valid: **{result['outcome_valid']}**\nGame: **{result['game']}** · Nonce: **{result['nonce']}**\nClient seed: `{result['client_seed']}`\nServer seed: `{result['revealed_seed']}`\nCommitment: `{result['commitment']}`\nHMAC digest: `{result['result_digest']}`\nFull settled record is attached as JSON.",color=0x35D07F if result['valid'] else 0xE34B5B)
        await it.response.send_message(embed=e,file=file,allowed_mentions=discord.AllowedMentions.none())

    async def start_step_game(self,it,bet,game):
        if not await self.allowed(it,bet,game): return
        await it.response.defer(ephemeral=True,thinking=True)
        try:
            edge=self.bot.settings.house_edge; cap=self.bot.settings.max_payout
            sid=await self.bot.db.start_game(it.user.id,game,bet,self.bot.settings.daily_bet_limit)
            fair=await self.bot.fairness.allocate(it.user.id,game)
            await self.bot.db.attach_fair_round(sid,fair['round_id'])
            view=RoadView(self,it,sid,fair,bet,game,edge,cap)
            intro=('Pick one safe tile from three. Multiplier triples per safe step; cash out after any safe step.' if game=='chicken-road' else 'Pump advances in 0.25× steps. Cash out before its hidden burst point.')
            await it.edit_original_response(embed=embed(('🐔 Chicken Road' if game=='chicken-road' else '📈 Pump'),f'{intro}\nBet: **{money(bet)}**\nFair commitment: `{fair["commitment"]}` · Round `{fair["round_id"]}`'),view=view); view.message=await it.original_response()
        except ValueError as e:
            if 'sid' in locals(): await self.bot.db.refund_game(sid)
            await it.edit_original_response(embed=embed('Bet rejected',str(e)))
        except Exception:
            if 'sid' in locals(): await self.bot.db.refund_game(sid)
            self.bot.active_users.discard(it.user.id)
            raise
    @app_commands.command(name='chicken-road',description='Advance through a risky road and cash out')
    async def chicken(self,it:discord.Interaction,bet:app_commands.Range[int,1,1000000]): await self.start_step_game(it,bet,'chicken-road')
    @app_commands.command(name='pump',description='Raise the multiplier and cash out before the pump bursts')
    async def pump(self,it:discord.Interaction,bet:app_commands.Range[int,1,1000000]): await self.start_step_game(it,bet,'pump')

async def setup(bot): await bot.add_cog(NewGames(bot))
