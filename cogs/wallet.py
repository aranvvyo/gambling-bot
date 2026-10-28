import discord
import time
from discord import app_commands
from discord.ext import commands
from services.ui import embed,money
from services.emojis import resolve_emoji
from services.components import EmbedPager


def limits_text(bot,uid,controls=None):
 import time
 ctl=controls
 cap=min(bot.settings.daily_bet_limit,ctl['daily_limit']) if ctl and ctl['daily_limit'] else bot.settings.daily_bet_limit
 excluded=bool(ctl and ctl['excluded_until'] and int(ctl['excluded_until'])>int(time.time()))
 text=(f'Minimum bet: **{money(bot.settings.min_bet)}**\nMaximum bet: **{money(bot.settings.max_bet) if bot.settings.max_bet else "No per-bet cap"}**\n'
       f'Casino daily cap: **{money(bot.settings.daily_bet_limit)}**\nYour daily cap: **{money(cap)}**\nDaily reward: **{money(bot.settings.daily_reward)}**\n'
       f'Self-excluded: **{"Yes" if excluded else "No"}**')
 if excluded:text+=f' until <t:{ctl["excluded_until"]}:F>'
 return text

def make_pages(rows):
 pages=[]
 for start in range(0,max(1,len(rows)),5):
  batch=rows[start:start+5]
  text='\n'.join(f"`{r['created_at']}` · **{r['kind'].replace('_',' ').title()}** · {money(int(r['amount']))} · balance {money(int(r['balance_after']))}" for r in batch) or 'No transactions yet.'
  e=embed('Wallet activity','Private, append-only wallet ledger · newest first')
  e.add_field(name='Transactions',value=text[:1024],inline=False)
  e.set_footer(text=f'{e.footer.text}  •  Page {len(pages)+1}/{max(1,(len(rows)+4)//5)}')
  pages.append(e)
 return pages

class Wallet(commands.Cog):
 def __init__(self,bot):self.bot=bot
 @app_commands.command(name='balance',description='View your wallet balance')
 async def balance(self,it):
  balance=await self.bot.db.balance(it.user.id);spent=await self.bot.db.daily_wagered(it.user.id)
  e=embed(f'{resolve_emoji(self.bot,"outcome")} Wallet balance','Available funds in virtual casino credits.')
  e.add_field(name='Available',value=f'**{money(balance)}**',inline=True)
  e.add_field(name='Wagered today',value=f'{money(spent)} / {money(self.bot.settings.daily_bet_limit)}',inline=True)
  await it.response.send_message(embed=e,ephemeral=True)
 @app_commands.command(name='transactions',description='View your latest wallet transactions')
 async def transactions(self,it):
  rows=await self.bot.db.history(it.user.id,50);pages=make_pages(rows);view=EmbedPager(it.user.id,pages)
  await it.response.send_message(embed=pages[0],view=view,ephemeral=True)
  view.message=await it.original_response()
 @app_commands.command(name='profile',description='View your player profile')
 async def profile(self,it):
  rows=await self.bot.db.history(it.user.id,50);today=await self.bot.db.daily_wagered(it.user.id)
  stats=await self.bot.db.player_game_stats(it.user.id)
  e=embed(f'{resolve_emoji(self.bot,"achievement")} Player profile',f'{it.user.mention} · Account created <t:{int(it.user.created_at.timestamp())}:D>')
  e.set_thumbnail(url=it.user.display_avatar.url)
  e.add_field(name='Balance',value=f'**{money(await self.bot.db.balance(it.user.id))}**',inline=True)
  e.add_field(name='Wagered today',value=f'{money(today)} / {money(self.bot.settings.daily_bet_limit)}',inline=True)
  e.add_field(name='Settled games',value=f'{stats["rounds"]} rounds · {stats["wins"]} wins · net {money(int(stats["net"]))}',inline=False)
  e.add_field(name='Recent ledger',value=f'{len(rows)} latest entries available (maximum 50)',inline=False)
  await it.response.send_message(embed=e,ephemeral=True)

 @app_commands.command(name='daily',description='Claim your configurable daily virtual-credit reward')
 async def daily(self,it):
  reward=int(self.bot.settings.daily_reward)
  try:result=await self.bot.db.daily_claim(it.user.id,reward)
  except ValueError as exc:return await it.response.send_message(embed=embed('Daily reward unavailable',str(exc),state='pending' if 'cooldown' in str(exc).lower() else 'error'),ephemeral=True)
  if self.bot.event_logger:self.bot.event_logger.emit('wallet','Daily reward credited',user_id=it.user.id,amount=result['amount'],reference=f'daily:{it.user.id}:{result["next_claim_at"]-86400}')
  await it.response.send_message(embed=embed('Daily reward claimed',f'Added **{money(result["amount"])}** to your wallet. New balance: **{money(result["balance"])}**.\nNext claim: <t:{result["next_claim_at"]}:R>',state='success'),ephemeral=True)

 @app_commands.command(name='limits',description='View casino and personal responsible-play limits')
 async def limits(self,it):
  ctl=await self.bot.db.play_controls(it.user.id); text=limits_text(self.bot,it.user.id,ctl)
  await it.response.send_message(embed=embed('Your limits',text,state='info'),ephemeral=True)

 @app_commands.command(name='leaderboard',description='View net results from completed game rounds')
 async def leaderboard(self,it):
  rows=await self.bot.db.leaderboard(10)
  if not rows:text='No completed game rounds have been recorded yet.'
  else:
   text='\n'.join(f'**{i}.** <@{int(row["discord_id"])}> · Net **{money(int(row["net"]))}** · {int(row["wins"])} wins / {int(row["rounds"])} rounds' for i,row in enumerate(rows,1))
  e=embed('Casino leaderboard',text,state='info');e.set_footer(text=f'{settings.casino_name} · Settled game records only · Wallet balances and deposits are private')
  await it.response.send_message(embed=e,allowed_mentions=discord.AllowedMentions.none())

async def setup(bot):await bot.add_cog(Wallet(bot))
