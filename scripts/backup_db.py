"""Create an online SQLite backup without copying a live WAL file by hand."""
import argparse, os, sqlite3
from pathlib import Path
from config import settings

def database_path(url):
    if not url.startswith('sqlite:///'): raise ValueError('Only SQLite databases can be backed up')
    return Path(url.removeprefix('sqlite:///'))

def backup(source: Path, destination: Path):
    if not source.is_file(): raise FileNotFoundError(source)
    if destination.exists(): raise FileExistsError(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    src=sqlite3.connect(source); dst=sqlite3.connect(destination)
    try: src.backup(dst)
    finally: dst.close();src.close()
    os.chmod(destination,0o600)
    return destination

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('destination',type=Path);args=parser.parse_args()
    target=backup(database_path(settings.database_url),args.destination)
    print(f'Backup created: {target}')
