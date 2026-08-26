from contextlib import contextmanager
import fcntl
import os
from pathlib import Path

from utils.get_project_dir import get_project_root


def reward_sender_lock_path():
    return Path(get_project_root()) / "data" / "reward-sender.lock"


@contextmanager
def reward_sender_lock(path=None):
    """Serialize the single-host payout signer across web processes."""
    # ponytail: single-host lock; use one external transaction worker before
    # running Crab writers on hosts that do not share this data volume.
    lock_path = Path(path) if path else reward_sender_lock_path()
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
