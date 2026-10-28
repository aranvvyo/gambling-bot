import os
import subprocess
import sys
from pathlib import Path

import pytest

from database.db import Database


@pytest.mark.asyncio
async def test_sqlite_creates_configured_persistent_parent_directory(tmp_path):
    path = tmp_path / 'persistent' / 'data' / 'casino.sqlite'
    db = await Database(f'sqlite:///{path}').open()
    assert path.is_file()
    await db.close()


def test_entrypoint_missing_token_fails_safely_without_traceback():
    project = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env['DISCORD_TOKEN'] = ''
    result = subprocess.run(
        [sys.executable, 'bot.py'], cwd=project, env=env,
        text=True, capture_output=True, timeout=20,
    )
    assert result.returncode == 2
    assert 'Configuration error: DISCORD_TOKEN is required' in result.stderr
    assert 'Traceback' not in result.stderr
    assert 'Configuration error' not in result.stdout
