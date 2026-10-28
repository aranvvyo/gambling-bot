import asyncio
import pytest
from cogs.prefix import parse_credits
from database.db import Database

@pytest.mark.parametrize(('raw','expected'), [('1',1),('1$',1),('1,000',1000)])
def test_prefix_credit_parser(raw,expected):
    assert parse_credits(raw)==expected

@pytest.mark.parametrize('raw',['0','-1','1.5','1usd','nan','$'])
def test_prefix_credit_parser_rejects_invalid(raw):
    with pytest.raises(ValueError): parse_credits(raw)

@pytest.mark.asyncio
async def test_tip_transfer_is_atomic_and_ledgered(tmp_path):
    db=await Database(f"sqlite:///{tmp_path/'tip.sqlite'}").open()
    await db.change_balance(1,25,'seed','seed:1')
    sender,recipient=await db.transfer(1,2,7,'tip:test')
    assert (sender,recipient)==(18,7)
    assert await db.balance(1)==18 and await db.balance(2)==7
    rows=await db.history(1,5)
    assert rows[0]['kind']=='tip_sent' and rows[0]['amount']==-7
    with pytest.raises(ValueError): await db.transfer(1,2,100,'tip:overdraw')
    with pytest.raises(ValueError): await db.transfer(1,1,1,'tip:self')
    assert await db.balance(1)==18
    await db.close()

def test_prefix_admin_gate_requires_configured_or_server_admin():
    from types import SimpleNamespace
    from cogs.prefix import PrefixCommands
    cog=PrefixCommands(SimpleNamespace(settings=SimpleNamespace(owners=frozenset({10}),admins=frozenset({20}))))
    def context(uid, administrator=False):
        return SimpleNamespace(author=SimpleNamespace(id=uid,guild_permissions=SimpleNamespace(administrator=administrator)),guild=object())
    assert cog._admin(context(10))
    assert cog._admin(context(20))
    assert cog._admin(context(30,True))
    assert not cog._admin(context(30))
