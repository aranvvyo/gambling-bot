"""Advisory single-process lock for a bot using a persistent SQLite database."""
import os
import stat
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - Termux and supported Linux use fcntl
    fcntl = None


class ProcessAlreadyRunning(RuntimeError):
    pass


class DatabaseProcessLock:
    def __init__(self, database_url):
        if not database_url.startswith('sqlite:///'):
            raise ValueError('Only SQLite database URLs are supported')
        raw = database_url.removeprefix('sqlite:///')
        self.path = None if raw == ':memory:' else Path(raw).expanduser().resolve()
        self.file = None

    def acquire(self):
        if self.path is None:
            return
        if fcntl is None:
            raise RuntimeError('This platform does not support the required SQLite process lock')
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_path = self.path.with_name(self.path.name + '.bot.lock')
        flags=os.O_CREAT | os.O_RDWR | getattr(os,'O_CLOEXEC',0) | getattr(os,'O_NOFOLLOW',0)
        fd=os.open(lock_path,flags,0o600)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise RuntimeError('SQLite process lock path is not a regular file')
        os.fchmod(fd,0o600)
        self.file=os.fdopen(fd,'a+',encoding='ascii')
        try:
            fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.file.close()
            self.file = None
            raise ProcessAlreadyRunning('Another bot process already owns this SQLite database.') from None

    def release(self):
        if self.file is not None:
            try:
                if fcntl is not None:
                    fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            finally:
                self.file.close()
                self.file = None
