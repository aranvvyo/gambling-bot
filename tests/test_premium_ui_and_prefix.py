import asyncio
import logging
import struct
import zlib
import binascii
from pathlib import Path
from types import SimpleNamespace
import discord
import pytest
from discord.ext import commands
from cogs.prefix import PrefixCommands, parse_credits, GAME_META
from cogs.prefix_bridge import PrefixInteraction, _choice_value
from database.db import Database
from discord import app_commands
from services.ui import embed, deposit_status, qr_file, PALETTE

PROJECT=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize(('status','title','state'),[
 ('created','Awaiting payment','pending'),('paid','Payment detected','pending'),
 ('partpaid','Partial payment detected','pending'),('completed','Payment confirmed · review pending','pending'),
 ('expired','Invoice expired','error'),('failed','Payment failed','error'),('overpaid','Overpayment detected','pending')])
def test_provider_statuses_have_accurate_ui(status,title,state):
 result_title,description,result_state=deposit_status({'status':status,'credited':False,'reason':'review' if status=='completed' else ''})
 assert result_title==title and result_state==state and ('no wallet credit' in description.lower() or 'no automatic wallet credit' in description.lower() or 'no balance was credited' in description.lower())

def test_success_and_already_credited_states_are_explicit():
 assert deposit_status({'status':'completed','credited':True,'amount':120})[0]=='Deposit confirmed'
 assert 'already credited' in deposit_status({'status':'completed','already_credited':True})[1]

def test_theme_embeds_have_timestamp_contrast_and_size_limits():
 e=embed('Premium screen','Readable message')
 assert e.color.value==PALETTE['base'] and e.timestamp is not None
 assert e.footer.text and len(e.title)<=256 and len(e.description)<=4096
 assert embed('Success','Done',state='success').color.value==PALETTE['success']
 assert embed('Failure','No',state='error').color.value==PALETTE['error']

def test_original_asset_pack_is_complete_and_valid_png():
 expected={'logo','welcome','games','wallet',*GAME_META}
 files={p.stem:p for p in (PROJECT/'assets'/'premium').glob('*.png')}
 assert expected==set(files)
 for name,path in files.items():
  data=path.read_bytes();assert data[:8]==b'\x89PNG\r\n\x1a\n'
  width,height=struct.unpack('!II',data[16:24]);assert (width,height)==((1200,400) if name in {'welcome','games','wallet'} else (256,256))
  offset=8;compressed=[]
  while offset<len(data):
   length=struct.unpack('!I',data[offset:offset+4])[0];tag=data[offset+4:offset+8];chunk=data[offset+8:offset+8+length];crc=struct.unpack('!I',data[offset+8+length:offset+12+length])[0]
   assert binascii.crc32(tag+chunk)&0xffffffff==crc
   if tag==b'IDAT':compressed.append(chunk)
   offset+=12+length
  assert len(zlib.decompress(b''.join(compressed)))>height

def test_payment_qr_is_a_real_png_generated_from_given_address():
 f=qr_file('LTC-address-from-provider-123456789')
 assert f.filename=='deposit-qr.png'
 assert f.fp.read(8)==b'\x89PNG\r\n\x1a\n'
 f.close()
 with pytest.raises(ValueError):qr_file('')

@pytest.mark.asyncio
async def test_prefix_bridge_has_every_existing_app_command_and_game():
 from bot import CasinoBot
 bot=CasinoBot()
 modules=('wallet','deposits','mines','dragon_tower','blackjack','crash','limbo','limo','admin','responsible','casino','new_games','prefix','prefix_bridge')
 try:
  for module in modules:await bot.load_extension('cogs.'+module)
  assert {'mines','blackjack','dragon-tower','crash','limbo','limo','dice','chicken-road','pump'} <= set(bot.all_commands)
  assert {'play-limit','self-exclude','play-status','admin-status','admin-credit','admin-game','admin-config'} <= set(bot.all_commands)
  assert 'bal' in bot.all_commands and bot.all_commands['balance'] is bot.all_commands['bal']
  from cogs.prefix import GamesView
  menu=GamesView(77,GAME_META)
  assert {opt.value for opt in menu.children[0].options}==set(GAME_META)
  for app in bot.tree.walk_commands():
   assert app.name in bot.all_commands,app.name
  captured={}
  async def reply(**kwargs):captured.update(kwargs);return SimpleNamespace(edit=lambda **kw:None)
  guide_ctx=SimpleNamespace(bot=bot,author=SimpleNamespace(id=77),reply=reply)
  await bot.get_cog('PrefixCommands').help_menu(guide_ctx)
  categories=bot.get_cog('PrefixCommands')
  view=captured['view']
  assert {'Wallet','Games','Deposits','Responsible play','Administration','Guide and fairness'}==set(view.children[0].categories)
  admin_embed=view.children[0].categories['Administration']
  assert all(len(field.value)<=1024 for field in admin_embed.fields)
  assert any('.admin-rate' in field.value and 'Owner only' in field.value for field in admin_embed.fields)
 finally:await bot.close()

def test_choice_parser_accepts_labels_and_values_and_rejects_unknown():
 option=SimpleNamespace(choices=[app_commands.Choice(name='Under',value='under'),app_commands.Choice(name='Over',value='over')])
 assert _choice_value(option,'UNDER')=='under'
 assert _choice_value(option,'over')=='over'
 with pytest.raises(commands.BadArgument):_choice_value(option,'sideways')

@pytest.mark.asyncio
async def test_private_prefix_adapter_sends_dm_and_does_not_leak_on_dm_failure():
 class User:
  id=7
  def __init__(self,fail=False):self.sent=[];self.fail=fail
  async def send(self,*args,**kwargs):
   if self.fail:raise discord.Forbidden(SimpleNamespace(status=403,reason='Forbidden',headers={}), 'DMs disabled')
   self.sent.append((args,kwargs));return 'dm-message'
 class Channel:
  id=3
  def __init__(self):self.sent=[]
  async def send(self,*args,**kwargs):self.sent.append((args,kwargs));return 'safe-channel-message'
 async def exercise(fail):
  user=User(fail);channel=Channel();ctx=SimpleNamespace(author=user,guild=object(),channel=channel,bot=None,message=SimpleNamespace(id=1),send=channel.send)
  command=SimpleNamespace(name='mines')
  adapter=PrefixInteraction(ctx,command)
  if fail:
   with pytest.raises(discord.Forbidden):await adapter.send('private',ephemeral=True)
   assert channel.sent==[]
  else:
   assert await adapter.send('private',ephemeral=True)=='dm-message'
   assert user.sent[0][0][0]=='private' and channel.sent==[]
 await exercise(False);await exercise(True)

@pytest.mark.asyncio
async def test_prefix_tip_command_uses_atomic_ledger_and_rejects_invalid_users(tmp_path):
 db=await Database(f"sqlite:///{tmp_path/'prefix-tip.sqlite'}").open()
 await db.change_balance(10,40,'seed','seed:10')
 settings=SimpleNamespace(owners=frozenset(),admins=frozenset(),max_payout=100,currency_symbol='VC')
 bot=SimpleNamespace(db=db,settings=settings)
 cog=PrefixCommands(bot)
 class User:
  def __init__(self,uid,bot_user=False):self.id=uid;self.bot=bot_user;self.mention=f'<@{uid}>'
 class Ctx:
  def __init__(self):self.author=User(10);self.guild=None;self.sent=[]
  async def reply(self,**kwargs):self.sent.append(kwargs)
 ctx=Ctx();await PrefixCommands.tip.callback(cog,ctx,User(11),'12')
 assert await db.balance(10)==28 and await db.balance(11)==12
 assert 'Tip sent' in ctx.sent[-1]['embed'].title
 for target,amount in [(User(10),'1'),(User(12,True),'1'),(User(12),'-2'),(User(12),'1.2'),(User(12),'100')]:
  ctx=Ctx();await PrefixCommands.tip.callback(cog,ctx,target,amount)
  assert ctx.sent[-1]['embed'].title.endswith('Tip not sent')
 assert await db.balance(10)==28
 await db.close()

@pytest.mark.asyncio
async def test_prefix_add_is_owner_admin_gated_and_audited(tmp_path):
 db=await Database(f"sqlite:///{tmp_path/'prefix-add.sqlite'}").open()
 settings=SimpleNamespace(owners=frozenset({10}),admins=frozenset(),max_payout=100,currency_symbol='VC')
 bot=SimpleNamespace(db=db,settings=settings)
 cog=PrefixCommands(bot)
 class User:
  def __init__(self,uid):self.id=uid;self.bot=False;self.mention=f'<@{uid}>'
 class Ctx:
  def __init__(self,uid):self.author=User(uid);self.guild=None;self.sent=[]
  async def reply(self,**kwargs):self.sent.append(kwargs)
 denied=Ctx(22);await PrefixCommands.add.callback(cog,denied,User(30),'4')
 assert denied.sent[-1]['embed'].title.endswith('Access denied') and await db.balance(30)==0
 owner=Ctx(10);await PrefixCommands.add.callback(cog,owner,User(30),'4')
 assert await db.balance(30)==4 and owner.sent[-1]['embed'].title.endswith('Credit adjustment recorded')
 cur=await db.conn.execute('SELECT action FROM admin_audit')
 assert (await cur.fetchone())['action']=='wallet_adjustment'
 await db.close()

@pytest.mark.asyncio
async def test_bridged_command_executes_existing_responsible_play_callback(tmp_path):
    from bot import CasinoBot
    bot=CasinoBot()
    db=await Database(f"sqlite:///{tmp_path/'bridge-play.sqlite'}").open();bot.db=db
    for module in ('wallet','deposits','mines','dragon_tower','blackjack','crash','limbo','limo','admin','responsible','casino','new_games','prefix','prefix_bridge'):
        await bot.load_extension('cogs.'+module)
    class User:
        id=501
    class Channel:
        async def send(self,*args,**kwargs):return SimpleNamespace(channel=self,edit=lambda **kw:None)
    ctx=SimpleNamespace(author=User(),guild=None,channel=Channel(),bot=bot,message=SimpleNamespace(id=8),send=Channel().send)
    try:
        await bot.get_command('play-limit').callback(ctx,500)
        assert (await db.play_controls(501))['daily_limit']==500
    finally:
        await db.close();await bot.close()

@pytest.mark.asyncio
async def test_bridged_private_command_stops_before_callback_if_dm_unavailable(tmp_path):
    from bot import CasinoBot
    bot=CasinoBot()
    db=await Database(f"sqlite:///{tmp_path/'bridge-dm.sqlite'}").open();bot.db=db
    for module in ('wallet','deposits','mines','dragon_tower','blackjack','crash','limbo','limo','admin','responsible','casino','new_games','prefix','prefix_bridge'):
        await bot.load_extension('cogs.'+module)
    class User:
        id=502;dm_channel=None
        async def create_dm(self):
            raise discord.Forbidden(SimpleNamespace(status=403,reason='Forbidden',headers={}), 'DMs disabled')
    class Channel:
        id=12
        def __init__(self):self.sent=[]
        async def send(self,*args,**kwargs):self.sent.append((args,kwargs));return SimpleNamespace(channel=self,edit=lambda **kw:None)
    channel=Channel()
    async def reply(**kwargs):channel.sent.append(((),kwargs))
    ctx=SimpleNamespace(author=User(),guild=object(),channel=channel,bot=bot,message=SimpleNamespace(id=9),send=channel.send,reply=reply)
    try:
        await bot.get_command('play-limit').callback(ctx,400)
        assert await db.play_controls(502) is None
        assert 'Enable direct messages' in channel.sent[-1][1]['embed'].description
    finally:
        await db.close();await bot.close()

@pytest.mark.asyncio
async def test_new_deposit_invoice_creation_is_disabled_by_default(tmp_path):
    db=await Database(f"sqlite:///{tmp_path/'deposit-gate.sqlite'}").open()
    class Payments:
        def __init__(self):self.calls=[]
        async def create(self,*args):self.calls.append(args);raise AssertionError('provider must not be called')
    payments=Payments()
    settings=SimpleNamespace(deposits_enabled=False,maintenance=False,max_payout=10,currency_symbol='VC')
    bot=SimpleNamespace(db=db,settings=settings,payments=payments)
    cog=PrefixCommands(bot)
    class Ctx:
        channel=object();author=SimpleNamespace(id=72);guild=None
        def __init__(self):self.sent=[]
        async def reply(self,**kwargs):self.sent.append(kwargs)
    ctx=Ctx()
    await PrefixCommands.depoamount.callback(cog,ctx,'ltc','1')
    assert not payments.calls
    assert ctx.sent[0]['embed'].title.endswith('Deposits disabled')
    await db.close()

@pytest.mark.asyncio
async def test_prefix_deposit_invoice_embed_uses_provider_address_and_qr_mock(tmp_path):
    from decimal import Decimal
    import logging
    db=await Database(f"sqlite:///{tmp_path/'prefix-deposit-ui.sqlite'}").open()
    class Payments:
        def __init__(self):self.calls=[]
        async def create(self,*args):
            self.calls.append(args)
            return {'invoice':'invoice123456','address':'L-provider-address-123456789','currency':'ltc','amount_coin':Decimal('0.1'),'status':'created','expire':'2099-01-01T00:00:00Z'}
    payments=Payments();payments.live_enabled=True
    settings=SimpleNamespace(deposits_enabled=True,deposits_live_verified=True,maintenance=False,invoice_lifetime=3600,currency_symbol='VC',casino_name='Emerald Vault',min_deposit=Decimal('0.01'))
    bot=SimpleNamespace(db=db,settings=settings,payments=payments,logger=logging.getLogger('prefix-deposit-ui'))
    cog=PrefixCommands(bot)
    class Ctx:
        channel=object.__new__(discord.DMChannel);guild=None;author=SimpleNamespace(id=41)
        def __init__(self):self.sent=[]
        async def reply(self,**kwargs):self.sent.append(kwargs);return SimpleNamespace(channel=self.channel)
    ctx=Ctx()
    await PrefixCommands.depoamount.callback(cog,ctx,'ltc','0.1')
    assert payments.calls==[(41,'ltc',Decimal('0.1'),3600)]
    message=ctx.sent[0]
    assert 'LTC' in message['embed'].fields[0].value and 'L-provider-address-123456789' in message['embed'].fields[3].value
    assert message['embed'].thumbnail.url=='attachment://deposit-qr.png'
    assert message['file'].fp.read(8)==b'\x89PNG\r\n\x1a\n'
    assert [item.label for item in message['view'].children]==['Copy Address','Check Payment']
    await db.close()

@pytest.mark.asyncio
async def test_casino_bridge_preserves_multiple_bundled_files():
    class User:
        id=79
        def __init__(self):self.sent=[]
        async def send(self,*args,**kwargs):self.sent.append(kwargs);return 'sent'
    user=User();ctx=SimpleNamespace(author=user,guild=object(),channel=SimpleNamespace(id=2),bot=None,message=SimpleNamespace(id=2),send=lambda *a,**k:None)
    adapter=PrefixInteraction(ctx,SimpleNamespace(name='casino'))
    first=discord.File(PROJECT/'assets'/'premium'/'welcome.png',filename='welcome.png')
    second=discord.File(PROJECT/'assets'/'premium'/'logo.png',filename='logo.png')
    try:
        await adapter.send(embed=embed('Lobby','Welcome'),ephemeral=True,files=[first,second])
        assert len(user.sent[0]['files'])==2 and 'file' not in user.sent[0]
    finally:first.close();second.close()

@pytest.mark.asyncio
async def test_game_menu_is_owner_scoped_and_disables_on_timeout():
    from cogs.prefix import GamesView
    class Response:
        def __init__(self):self.sent=[]
        async def send_message(self,**kwargs):self.sent.append(kwargs)
    interaction=SimpleNamespace(user=SimpleNamespace(id=99),response=Response())
    view=GamesView(7,GAME_META)
    assert not await view.interaction_check(interaction)
    assert 'another player' in interaction.response.sent[0]['embed'].description
    await view.on_timeout()
    assert view.children[0].disabled

@pytest.mark.asyncio
async def test_responsible_play_confirmation_disables_after_timeout():
    from cogs.responsible import ExclusionConfirm
    edits=[]
    view=ExclusionConfirm(None,5,7)
    async def edit(**kwargs):edits.append(kwargs)
    view.message=SimpleNamespace(edit=edit)
    await view.on_timeout()
    assert all(item.disabled for item in view.children)
    assert len(edits)==1 and edits[0]['view'] is view
