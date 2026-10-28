from types import SimpleNamespace as NS
import logging
import pytest
from cogs.admin import Admin

class Response:
 def __init__(self): self.sent=[]
 def is_done(self): return bool(self.sent)
 async def send_message(self,*args,**kwargs): self.sent.append((args,kwargs))

@pytest.mark.asyncio
async def test_admin_allowlist_owner_and_private_channel():
 settings=NS(owners=frozenset({1}),admins=frozenset({2}),admin_channel_id=50)
 bot=NS(settings=settings,logger=logging.getLogger('test'),event_logger=None)
 cog=Admin(bot)
 def interaction(uid,channel=50,guild=None): return NS(user=NS(id=uid),channel=NS(id=channel),guild=guild,response=Response(),command=NS(name='admin-status'),id=uid)
 assert await cog.authorized(interaction(1))
 assert await cog.authorized(interaction(2))
 denied=interaction(3)
 assert not await cog.authorized(denied) and denied.response.sent
 wrong_channel=interaction(2,51)
 assert not await cog.authorized(wrong_channel) and wrong_channel.response.sent

@pytest.mark.asyncio
async def test_configured_admins_and_server_admins_are_authorized_in_guild():
 settings=NS(owners=frozenset({1}),admins=frozenset({2}),admin_channel_id=0)
 cog=Admin(NS(settings=settings,logger=logging.getLogger('test'),event_logger=None))
 ordinary_staff=NS(user=NS(id=2,guild_permissions=NS(administrator=False)),channel=NS(id=3),guild=object(),response=Response(),command=None,id=22)
 assert await cog.authorized(ordinary_staff)
 owner=NS(user=NS(id=1,guild_permissions=NS(administrator=False)),channel=NS(id=3),guild=object(),response=Response(),command=None,id=23)
 assert await cog.authorized(owner)
