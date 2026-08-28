"""Cross-process advisory lock over the shared data directory.

The scheduled Windows tasks (reminder / reply scans) run as separate processes
and touch the same files as the dashboard - send_log.json, send_history.jsonl,
reply_queue.jsonl, clients.xlsx. `data_lock()` serialises the read-modify-write
sections so two writers can't clobber each other's changes.

Windows only (msvcrt); on any other platform it degrades to a no-op. Re-entrant
within a single process via a threading.RLock, so nested acquisitions (e.g. a
batch send that also calls record_sent) don't deadlock.
"""

import threading
import time
from contextlib import contextmanager

from kairo.paths import data_dir

try:
    import msvcrt
except ImportError:  # non-Windows
    msvcrt = None

_LOCK_PATH = data_dir() / ".lock"

# Guards the file-lock handle across threads in this process and makes the
# cross-process lock re-entrant (only the outermost acquisition touches the file).
_local_lock = threading.RLock()
_depth = 0
_handle = None


@contextmanager
def data_lock(timeout=60):
    global _depth, _handle

    _local_lock.acquire()
    try:
        if _depth > 0 or msvcrt is None:
            _depth += 1
            try:
                yield
            finally:
                _depth -= 1
            return

        try:
            _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
            _handle = open(_LOCK_PATH, "a+")
        except OSError:
            # Can't even open the lock file - don't block real work over it.
            _handle = None
            _depth += 1
            try:
                yield
            finally:
                _depth -= 1
            return

        deadline = time.time() + timeout
        while True:
            try:
                _handle.seek(0)
                msvcrt.locking(_handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.time() >= deadline:
                    _handle.close()
                    _handle = None
                    raise TimeoutError(
                        f"Timed out after {timeout}s waiting for the data lock "
                        f"({_LOCK_PATH}) - another Kairo process may be busy."
                    )
                time.sleep(0.2)

        _depth += 1
        try:
            yield
        finally:
            _depth -= 1
            try:
                _handle.seek(0)
                msvcrt.locking(_handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            _handle.close()
            _handle = None
    finally:
        _local_lock.release()
