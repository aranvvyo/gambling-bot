import pytest
from config import Settings

def test_config_requires_token_and_rejects_bad_values():
 with pytest.raises(ValueError,match='DISCORD_TOKEN'):
  Settings(token='').validate()
 valid=Settings(token='test-token').validate()
 assert valid.daily_bet_limit>=valid.max_bet
 with pytest.raises(ValueError,match='SQLite'):
  Settings(token='test-token',database_url='postgres://example').validate()
 with pytest.raises(ValueError,match='HOUSE_EDGE'):
  Settings(token='test-token',house_edge=__import__('decimal').Decimal('0.9')).validate()


def test_withdrawals_cannot_be_enabled_without_provider():
 with pytest.raises(ValueError,match='WITHDRAWALS_ENABLED'):
  Settings(token='test-token',withdrawals_enabled=True).validate()


def test_fairness_rotation_interval_and_channel_ids_validated():
 with pytest.raises(ValueError,match='FAIRNESS_ROTATION_SECONDS'):
  Settings(token='test-token',fairness_rotation_seconds=30).validate()
 with pytest.raises(ValueError,match='Discord channel'):
  Settings(token='test-token',admin_channel_id=-4).validate()

def test_config_rejects_empty_database_path():
 with pytest.raises(ValueError,match='database path'):
  Settings(token='test-token',database_url='sqlite:///').validate()


def test_apirone_credentials_must_be_configured_as_a_pair():
 with pytest.raises(ValueError,match='configured together'):
  Settings(token='test-token',apirone_account='account',apirone_key='').validate()
 with pytest.raises(ValueError,match='configured together'):
  Settings(token='test-token',apirone_account='',apirone_key='key').validate()
 blank=Settings(token='test-token',apirone_account='  ',apirone_key='  ').validate()
 assert blank.apirone_account == blank.apirone_key == ''

def test_safe_host_defaults_and_unlimited_per_bet_cap():
 from config import settings
 assert settings.guild_id == 0
 assert settings.owners == frozenset()
 assert settings.admins == frozenset()
 assert all(channel_id == 0 for channel_id in settings.log_channels.values())
 assert settings.min_bet == 1
 assert settings.max_bet == 0

@pytest.mark.asyncio
async def test_max_bet_zero_disables_only_per_bet_cap(tmp_path):
 from database.db import Database
 db=await Database(f"sqlite:///{tmp_path/'no-per-bet-cap.sqlite'}",min_bet=1,max_bet=0,max_payout=1000000,daily_bet_limit=50000).open()
 await db.change_balance(780,100000,'test-credit','test:unlimited-bet')
 sid=await db.start_game(780,'dice',20000)
 row=await (await db.conn.execute('SELECT session_max_bet FROM game_sessions WHERE id=?',(sid,))).fetchone()
 assert row['session_max_bet']==0
 await db.finish_game(sid,0,'test cleanup')
 with pytest.raises(ValueError,match='Daily wager limit'):
  await db.start_game(780,'dice',30001,50000)
 assert await db.reconcile_balances()==[]
 await db.close()
