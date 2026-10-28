import sqlite3
import pytest
from scripts.backup_db import backup, database_path

def test_online_backup_can_be_restored(tmp_path):
 original=tmp_path/'live.sqlite';copy=tmp_path/'backup.sqlite'
 with sqlite3.connect(original) as db: db.execute('CREATE TABLE ledger(value INTEGER)');db.execute('INSERT INTO ledger VALUES(99)')
 backup(original,copy)
 assert copy.exists()
 with sqlite3.connect(copy) as restored: assert restored.execute('SELECT value FROM ledger').fetchone()==(99,)
 with pytest.raises(FileExistsError): backup(original,copy)

def test_backup_requires_sqlite_url():
 with pytest.raises(ValueError):database_path('postgres://host/db')
