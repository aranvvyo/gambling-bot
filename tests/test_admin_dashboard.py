from types import SimpleNamespace
import pytest
from cogs.dashboard import PrefixConfirmView, EmojiSaveView, MaintenanceConfirmView, allowed
from services.emojis import DEFAULT_EMOJIS, validate_emoji, resolve_emoji

class FakeDB:
    def __init__(self): self.values=[]
    async def set_config(self,key,value,admin): self.values.append((key,value,admin))

class FakeInteraction:
    def __init__(self,uid):
        self.user=SimpleNamespace(id=uid,guild_permissions=SimpleNamespace(administrator=False))
        self.guild=None;self.channel=None;self.sent=[]
        self.response=SimpleNamespace(send_message=self.send,edit_message=self.edit)
    async def send(self,*args,**kwargs):self.sent.append((args,kwargs))
    async def edit(self,*args,**kwargs):self.sent.append((args,kwargs))

def bot():
    return SimpleNamespace(settings=SimpleNamespace(owners={7},admins={8},maintenance=False,deposits_enabled=False,deposits_live_verified=False,casino_name='Test',brand_color=123),db=FakeDB(),active_prefix='.',prefix_aliases=[],maintenance_notice='Paused',event_logger=None,emoji_map=DEFAULT_EMOJIS.copy())

@pytest.mark.asyncio
async def test_prefix_preview_apply_persists_and_updates_live_resolver():
    b=bot();v=PrefixConfirmView(b,7,'!');it=FakeInteraction(7)
    await v.children[0].callback(it)
    assert b.active_prefix=='!' and b.db.values==[('command_prefix','!',7)]
    assert all(x.disabled for x in v.children)

@pytest.mark.asyncio
async def test_prefix_confirm_rejects_unauthorized_component_user():
    b=bot();v=PrefixConfirmView(b,7,'?');it=FakeInteraction(9)
    assert not await v.interaction_check(it)
    assert not b.db.values and it.sent

@pytest.mark.asyncio
async def test_emoji_save_and_reset_are_persistent():
    b=bot();v=EmojiSaveView(b,7,'ltc','✅','set');it=FakeInteraction(7)
    await v.children[0].callback(it)
    assert b.emoji_map['ltc']=='✅' and b.db.values==[('emoji:ltc','✅',7)]
    reset=EmojiSaveView(b,7,'ltc',DEFAULT_EMOJIS['ltc'],'reset')
    await reset.children[0].callback(FakeInteraction(7))
    assert b.emoji_map['ltc']==DEFAULT_EMOJIS['ltc']

@pytest.mark.asyncio
async def test_emoji_remove_stores_fallback_override():
    b=bot();v=EmojiSaveView(b,7,'ltc','','remove')
    await v.children[0].callback(FakeInteraction(7))
    assert b.emoji_map['ltc']=='' and b.db.values==[('emoji:ltc','',7)]
    assert resolve_emoji(b,'ltc')=='Ł'

def test_emoji_validation_and_missing_custom_emoji_fallback():
    assert validate_emoji('✅') and validate_emoji('<:achivement:1564816726749741117>')
    assert not validate_emoji('foo✅') and not validate_emoji('not an emoji') and not validate_emoji('<:bad name:42>')
    b=bot();assert resolve_emoji(b,'ltc')=='Ł'
