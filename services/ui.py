"""Shared visual design system for the Emerald Vault casino UI."""
from datetime import datetime, timezone
from pathlib import Path
from io import BytesIO
import segno
import discord
from config import settings
from services.emojis import resolve_emoji

_BOT = None
_BRAND_COLOR = None

def bind_bot(bot, brand_color=None):
    global _BOT, _BRAND_COLOR
    _BOT = bot
    _BRAND_COLOR = int(brand_color) if brand_color is not None else None

def set_brand_color(color):
    global _BRAND_COLOR
    _BRAND_COLOR = int(color)

def emoji(bot, key):
    return resolve_emoji(bot, key)

PALETTE = {
    'base': 0x101713,       # charcoal green
    'success': 0x1D9A6C,    # emerald
    'pending': 0xC8A85A,    # restrained gold
    'error': 0xB94C52,      # muted red
    'info': 0x347C65,
    'muted': 0x68766F,
}

def embed(title, description='', *, color=None, state='base', timestamp=True):
    """Create a compact, consistent embed. State sets a coherent accent color."""
    accent = color if color is not None else (_BRAND_COLOR if _BRAND_COLOR is not None else PALETTE['base']) if state=='base' else PALETTE.get(state, PALETTE['base'])
    icon={'success':'success','error':'failed','pending':'alert','info':'info'}.get(state)
    text=str(title)
    if icon: text=f'{resolve_emoji(_BOT,icon)} {text}'
    e = discord.Embed(title=text[:256], description=str(description)[:4096], color=accent)
    e.set_footer(text=f'{settings.casino_name}  •  Play responsibly')
    if timestamp:
        e.timestamp = datetime.now(timezone.utc)
    return e

def money(amount):
    return f'{amount:,} {settings.currency_symbol}'

def asset_file(name):
    path=Path(__file__).resolve().parents[1]/'assets'/'premium'/f'{name}.png'
    return discord.File(path,filename=f'{name}.png') if path.is_file() else None

def qr_file(address):
    """Create a payment QR only from the exact provider-supplied address."""
    if not isinstance(address,str) or not address.strip() or len(address)>512:
        raise ValueError('Invalid provider address for QR generation')
    qr=segno.make(address.strip())
    stream=BytesIO();qr.save(stream,kind='png',scale=6,border=2);stream.seek(0)
    return discord.File(stream,filename='deposit-qr.png')

def deposit_status(result):
    status=str(result.get('status','unknown')).lower()
    amounts=''
    if result.get('currency'):
        from services.apirone import SUPPORTED
        currency=result['currency'];network=SUPPORTED.get(currency,(currency,currency,0))[1]
        amounts=(f"\nConfirmed: **{result.get('paid_amount','0')} {network}**"
                 f" · Remaining: **{result.get('remaining_amount','0')} {network}**.")
    if result.get('already_credited'):
        return 'Deposit confirmed', 'This invoice was already credited. No additional wallet credit was made.'+amounts, 'success'
    if result.get('credited'):
        return 'Deposit confirmed', f"Provider confirmation received. Credited **{money(result['amount'])}**."+amounts, 'success'
    if status=='completed':
        reason=result.get('reason') or 'Provider confirms payment; wallet credit is held for review.'
        return 'Payment confirmed · review pending', f'Apirone marked this invoice completed. No wallet credit was made. {reason}'+amounts, 'pending'
    if status=='expired': return 'Invoice expired', 'This invoice expired. No wallet credit was made.'+amounts, 'error'
    if status=='failed': return 'Payment failed', 'The provider reported a failed invoice. No wallet credit was made.'+amounts, 'error'
    if status=='partpaid': return 'Partial payment detected', 'No wallet credit was made; the invoice remains under review.'+amounts, 'pending'
    if status=='overpaid': return 'Overpayment detected', 'Funds are held for review; no wallet credit was made.'+amounts, 'pending'
    if status=='paid': return 'Payment detected', 'Final confirmation is still pending. No wallet credit was made.'+amounts, 'pending'
    if status=='created': return 'Awaiting payment', 'No completed payment is confirmed yet. No wallet credit was made.'+amounts, 'pending'
    return 'Payment status unavailable', f'Provider status: `{status}`. No wallet credit was made.'+amounts, 'pending'

async def check_bet(db,uid,bet,game=None):
    if game and (await db.get_config(f"game_enabled:{game}","true")).lower()!="true": raise ValueError("This game is currently disabled.")
    if type(bet) is not int or bet < settings.min_bet or (settings.max_bet and bet > settings.max_bet): raise ValueError(f'Bet must be at least {settings.min_bet:,} {settings.currency_symbol}' + (f' and at most {settings.max_bet:,} {settings.currency_symbol}.' if settings.max_bet else '.'))
    if await db.balance(uid)<bet: raise ValueError('You do not have enough balance.')
    ctl=await db.play_controls(uid)
    if ctl and ctl['excluded_until'] and ctl['excluded_until']>__import__('time').time(): raise ValueError('You are currently self-excluded from play.')
    cap=min(settings.daily_bet_limit,ctl['daily_limit']) if ctl and ctl['daily_limit'] else settings.daily_bet_limit
    if await db.daily_wagered(uid)+bet>cap: raise ValueError(f'Daily wager limit reached ({cap:,} VC).')

async def game_is_enabled(db, game):
    return (await db.get_config('game_enabled:'+game,'true')).lower() == 'true'

async def ephemeral_send(interaction, *args, **kwargs):
    kwargs['ephemeral'] = True
    if args and isinstance(args[0],str):
        args=(embed('Private game message',args[0],state='info'),*args[1:])
    elif isinstance(kwargs.get('content'),str):
        kwargs['embed']=embed('Private game message',kwargs.pop('content'),state='info')
    return await interaction.response.send_message(*args, **kwargs)
