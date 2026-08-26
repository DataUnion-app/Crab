import fcntl
import multiprocessing

from commands.rewards.sender_lock import reward_sender_lock


def cannot_take_lock(path, result):
    with open(path, "a+") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            result.put(True)
        else:
            result.put(False)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def test_reward_sender_lock_serializes_processes_and_is_owner_only(tmp_path):
    path = tmp_path / "reward-sender.lock"
    context = multiprocessing.get_context("fork")
    result = context.Queue()
    with reward_sender_lock(path):
        process = context.Process(target=cannot_take_lock, args=(path, result))
        process.start()
        process.join(5)
        assert process.exitcode == 0
        assert result.get(timeout=1) is True
    assert path.stat().st_mode & 0o777 == 0o600
