r"""Single source of truth for where files live, whether running from source or as a frozen .exe.

When running from source, user data (config.json, client_secret.json, logs, the send
trackers) sits in the project root next to the `kairo/` package - unchanged from before.

When running as a PyInstaller build, `__file__` points inside a temporary extraction
dir, so that logic would put user data somewhere useless. Installed copies keep their
data in `%APPDATA%\Kairo` - a stable per-user location that survives an uninstall,
reinstall, or version upgrade (the installer only ever touches `%LocalAppData%\Programs\Kairo`).
Older builds kept data next to `Kairo.exe`; `_migrate_from_exe_dir` moves it across once.
"""

import os
import shutil
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)

# Files an older (next-to-the-exe) build may have left behind, to carry across on
# first run of an installed build. The Gmail/Anthropic tokens live in the Windows
# credential store, not here, so they are untouched.
_MIGRATABLE = (
    "config.json", "client_secret.json", "clients.xlsx",
    "send_log.json", "send_history.jsonl", "llm_calls.json",
    "processed_replies.json", "reply_failures.json", "reply_queue.jsonl",
    "kairo.log",
)

_DATA_DIR: "Path | None" = None


def _frozen_data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "Kairo"


def _migrate_from_exe_dir(dest: Path) -> None:
    """One-time copy of user data from builds that kept it beside Kairo.exe."""
    try:
        old = Path(sys.executable).resolve().parent
    except OSError:
        return
    if old == dest:
        return
    for name in _MIGRATABLE:
        src, tgt = old / name, dest / name
        if src.exists() and not tgt.exists():
            try:
                shutil.copy2(src, tgt)
            except OSError:
                pass


def _seed_bundled_client_secret(dest: Path) -> None:
    """Copy the OAuth client bundled into the build out to the data dir on first run."""
    target = dest / "client_secret.json"
    if target.exists():
        return
    bundled = resource_path("client_secret.json")
    if bundled.exists():
        try:
            shutil.copy2(bundled, target)
        except OSError:
            pass


def data_dir() -> Path:
    """Folder that holds user data (config, credentials, logs, trackers).

    Pure path resolution - it never creates the folder. Importing kairo.paths (or
    anything that reads these path constants) must NOT resurrect a folder the user
    deleted; only a real write does, via ensure_data_dir(). An hourly scheduled
    task that merely imports the package therefore leaves a decommissioned install
    alone."""
    global _DATA_DIR
    if _DATA_DIR is not None:
        return _DATA_DIR
    if FROZEN:
        d = _frozen_data_dir()
    else:
        d = Path(__file__).resolve().parent.parent
    _DATA_DIR = d
    return d


_ENSURED = False


def ensure_data_dir() -> Path:
    """Create the data folder (and, for frozen builds, migrate old next-to-exe
    files + seed the bundled OAuth client) if it isn't there yet. Call this once
    from a real write entry point - app startup, a CLI action that writes - not
    at import time."""
    global _ENSURED
    d = data_dir()
    if _ENSURED:
        return d
    if FROZEN:
        try:
            d.mkdir(parents=True, exist_ok=True)
            _migrate_from_exe_dir(d)
            _seed_bundled_client_secret(d)
        except OSError:
            pass
    _ENSURED = True
    return d


def resource_path(relative: str) -> Path:
    """Absolute path to a bundled read-only resource (e.g. Flask templates/static).

    `relative` is given relative to the project root, e.g. "kairo/web/templates".
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if FROZEN and meipass:
        return Path(meipass) / relative
    return Path(__file__).resolve().parent.parent / relative


CONFIG_PATH = data_dir() / "config.json"
CLIENT_SECRET_PATH = data_dir() / "client_secret.json"
LOG_PATH = data_dir() / "kairo.log"
SEND_LOG_PATH = data_dir() / "send_log.json"
SEND_HISTORY_PATH = data_dir() / "send_history.jsonl"
LLM_CALLS_PATH = data_dir() / "llm_calls.json"
DEFAULT_EXCEL_PATH = data_dir() / "clients.xlsx"

# Reply-handling feature: which inbound messages have already been classified,
# and the queue of drafted actions awaiting the client's approval.
PROCESSED_REPLIES_PATH = data_dir() / "processed_replies.json"
# Per-message classification-failure counts, so a message that reliably breaks
# the classifier is given up on (and marked processed) after a few tries instead
# of costing an API call every scan forever.
REPLY_FAILURES_PATH = data_dir() / "reply_failures.json"
REPLY_QUEUE_PATH = data_dir() / "reply_queue.jsonl"
# Lockfile so two overlapping reply scans can't double-bill the LLM. Written at
# the top of process_replies.main(), removed in a finally; considered stale after
# 30 minutes.
REPLY_SCAN_LOCK_PATH = data_dir() / "reply_scan.lock"
