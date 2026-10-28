"""Shared result embed and attachment builder for settled game rounds."""
import discord
from services.ui import embed, money
from services.result_art import render_result
from services.emojis import resolve_emoji

async def game_result(bot, user_id, game, *, outcome, bet, payout, data=None, game_id=None, fair=None, won=None, status=None):
    balance=await bot.db.balance(int(user_id))
    won=payout>0 if won is None else bool(won)
    status=status or ("win" if won else "loss")
    label={"win":"Win","loss":"Loss","push":"Push"}.get(status,"Result")
    color={"win":0x22B980,"loss":0xD84D59,"push":0xDAB567}.get(status,0x347C65)
    icon=resolve_emoji(bot,'outcome' if status=='push' else ('success' if won else 'failed'))
    e=embed(f'{icon} {game.replace("-"," ").title()} · {label}',str(outcome),color=color)
    e.add_field(name='Wager',value=money(bet),inline=True)
    e.add_field(name='Payout',value=money(payout),inline=True)
    e.add_field(name='Balance',value=money(balance),inline=True)
    if fair and fair.get('round_id'): e.add_field(name='Provably fair',value=f"Round `{fair['round_id']}`",inline=False)
    if game_id: e.set_footer(text=f'Game ID {game_id} • Play responsibly')
    data=dict(data or {})
    data.setdefault("payout",payout)
    image=render_result(game,outcome=outcome,bet=bet,payout=payout,balance=money(balance),data=data,game_id=game_id,won=won,status=status)
    file=discord.File(image,filename='game-result.png'); e.set_image(url='attachment://game-result.png')
    return e,file
