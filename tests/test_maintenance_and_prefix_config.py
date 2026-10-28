from types import SimpleNamespace
import pytest
from bot import CasinoBot, MaintenanceModeError, active_command_prefix

@pytest.mark.asyncio
async def test_prefix_resolver_uses_active_prefix_and_only_explicit_aliases():
    bot=SimpleNamespace(active_prefix='!',prefix_aliases=['?'])
    assert await active_command_prefix(bot,None)==['!','?']
    bot.active_prefix='?';bot.prefix_aliases=[]
    assert await active_command_prefix(bot,None)==['?']

@pytest.mark.asyncio
async def test_maintenance_blocks_prefix_and_slash_money_commands_but_allows_safe_read_command():
    bot=CasinoBot();bot.settings=SimpleNamespace(maintenance=True);bot.maintenance_notice='Maintenance notice'
    ctx=SimpleNamespace(command=SimpleNamespace(name='tip'))
    with pytest.raises(MaintenanceModeError):await bot.maintenance_prefix_check(ctx)
    assert await bot.maintenance_prefix_check(SimpleNamespace(command=SimpleNamespace(name='balance')))
    class Response:
        def __init__(self):self.sent=[]
        async def send_message(self,**kw):self.sent.append(kw)
    it=SimpleNamespace(command=SimpleNamespace(name='deposit'),response=Response())
    assert not await bot.maintenance_interaction_check(it)
    assert it.response.sent[0]['ephemeral'] and 'Maintenance notice' in it.response.sent[0]['embed'].description
    allowed=SimpleNamespace(command=SimpleNamespace(name='admin-dashboard'),response=Response())
    assert await bot.maintenance_interaction_check(allowed)
    await bot.close()
