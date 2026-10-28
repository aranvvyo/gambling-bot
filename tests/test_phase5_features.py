import asyncio
import pytest
from database.db import Database
from services.process_lock import DatabaseProcessLock, ProcessAlreadyRunning


@pytest.mark.asyncio
async def test_daily_reward_uses_atomic_persistent_cooldown_and_ledger(tmp_path):
    db=await Database(f'sqlite:///{tmp_path / "daily.sqlite"}').open()
    now=1_800_000_000
    async def claim():
        try:return await db.daily_claim(77,125,now)
        except ValueError:return None
    results=await asyncio.gather(claim(),claim())
    wins=[x for x in results if x]
    assert len(wins)==1
    assert wins[0]['amount']==125 and wins[0]['balance']==125
    assert await db.balance(77)==125
    assert await db.daily_claim_status(77,now+86399)==1
    with pytest.raises(ValueError,match='cooldown'):
        await db.daily_claim(77,125,now+86399)
    next_claim=await db.daily_claim(77,125,now+86400)
    assert next_claim['balance']==250
    history=await db.history(77,10)
    assert [r['kind'] for r in history].count('daily_reward')==2
    assert not await db.reconcile_balances()
    await db.set_config('daily_reward','125',77)
    await db.close()
    db=await Database(f'sqlite:///{tmp_path / "daily.sqlite"}').open()
    assert await db.daily_claim_status(77,now+2*86400)==0
    assert await db.get_config('daily_reward')=='125'
    await db.close()


@pytest.mark.asyncio
async def test_daily_reward_is_blocked_during_maintenance(tmp_path):
    db=await Database(f'sqlite:///{tmp_path / "daily-maintenance.sqlite"}').open()
    db.maintenance_mode=True
    with pytest.raises(ValueError,match='maintenance'):
        await db.daily_claim(8,100)
    assert await db.balance(8)==0
    await db.close()


@pytest.mark.asyncio
async def test_self_exclusion_cannot_be_shortened_by_repeating_command(tmp_path):
    db=await Database(f'sqlite:///{tmp_path / "exclusion.sqlite"}').open()
    long_until=await db.self_exclude(3,30)
    short_until=await db.self_exclude(3,1)
    assert short_until==long_until
    assert (await db.play_controls(3))['excluded_until']==long_until
    await db.close()


@pytest.mark.asyncio
async def test_leaderboard_uses_settled_round_ledger_and_excludes_refunds(tmp_path):
    db=await Database(f'sqlite:///{tmp_path / "leaderboard.sqlite"}').open()
    await db.change_balance(1,100,'seed','leader-seed:1')
    win=await db.start_game(1,'dice',20)
    await db.finish_game(win,35,'win')
    await db.change_balance(2,10,'seed','leader-seed:2')
    loss=await db.start_game(2,'mines',10)
    await db.finish_game(loss,0,'loss')
    # Only settled game sessions and actual payout ledger rows determine rank.
    rows=await db.leaderboard(10)
    assert [r['discord_id'] for r in rows]==[1,2]
    assert (rows[0]['net'],rows[0]['wins'],rows[0]['rounds'])==(15,1,1)
    assert (rows[1]['net'],rows[1]['wins'],rows[1]['rounds'])==(-10,0,1)
    await db.close()


def test_database_process_lock_rejects_second_bot_and_releases_cleanly(tmp_path):
    database=tmp_path/'casino.sqlite'
    first=DatabaseProcessLock(f'sqlite:///{database}')
    second=DatabaseProcessLock(f'sqlite:///{database}')
    first.acquire()
    with pytest.raises(ProcessAlreadyRunning):second.acquire()
    first.release()
    second.acquire()
    second.release()
    lock_file=database.with_name(database.name+'.bot.lock')
    assert lock_file.exists() and lock_file.stat().st_mode & 0o077 == 0


def test_prefix_bridge_preserves_free_form_admin_reason():
    from types import SimpleNamespace
    from cogs.admin import Admin
    from cogs.prefix_bridge import _make_command
    command=_make_command(SimpleNamespace(),Admin.credit)
    last=list(command.params.values())[-1]
    assert last.name=='reason'
    assert last.kind.name=='KEYWORD_ONLY'


@pytest.mark.asyncio
async def test_dashboard_timeout_disables_controls_and_edits_message():
    from types import SimpleNamespace
    from cogs.dashboard import EconomyView
    bot=SimpleNamespace()
    view=EconomyView(bot,7)
    edited=[]
    class Message:
        async def edit(self,**kwargs):edited.append(kwargs)
    view.message=Message()
    await view.on_timeout()
    assert all(item.disabled for item in view.children)
    assert edited and edited[0]['view'] is view
