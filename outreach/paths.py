"""Single source of truth for where files live, whether running from source or as a frozen .exe.

When running from source, user data (config.json, client_secret.json, logs, the send
trackers) sits in the project root next to the `outreach/` package - unchanged from before.

When running as a PyInstaller onedir/onefile build, `__file__` points inside a temporary
extraction dir, so that logic would put user data somewhere useless. Instead we anchor it
to the folder the .exe itself lives in, so the client can see and back up config.json and
client_secret.json right next to FreightOutreach.exe.
"""

import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)


def data_dir() -> Path:
    """Folder that holds user data (config, credentials, logs, trackers)."""
    if FROZEN:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_path(relative: str) -> Path:
    """Absolute path to a bundled read-only resource (e.g. Flask templates/static).

    `relative` is given relative to the project root, e.g. "outreach/web/templates".
    """
    if FROZEN:
        return Path(sys._MEIPASS) / relative  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent / relative


CONFIG_PATH = data_dir() / "config.json"
CLIENT_SECRET_PATH = data_dir() / "client_secret.json"
LOG_PATH = data_dir() / "outreach.log"
SEND_LOG_PATH = data_dir() / "send_log.json"
SEND_HISTORY_PATH = data_dir() / "send_history.jsonl"
DEFAULT_EXCEL_PATH = data_dir() / "clients.xlsx"

# Reply-handling feature: which inbound messages have already been classified,
# and the queue of drafted actions awaiting the client's approval.
PROCESSED_REPLIES_PATH = data_dir() / "processed_replies.json"
# Per-message classification-failure counts, so a message that reliably breaks
# the classifier is given up on (and marked processed) after a few tries instead
# of costing an API call every scan forever.
REPLY_FAILURES_PATH = data_dir() / "reply_failures.json"
REPLY_QUEUE_PATH = data_dir() / "reply_queue.jsonl"
