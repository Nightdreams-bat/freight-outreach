"""Remembers the last Diagnostics run so the page can point out what changed.

`run_checks()` stays pure - it just reports the current state. This module keeps
a tiny JSON snapshot of the previous run next to the other trackers and diffs the
new results against it, so Diagnostics can show a "3 checks changed since last
run" notification instead of the operator having to remember what was green.
"""

import json
from datetime import datetime

from kairo.logging_setup import get_logger
from kairo.paths import data_dir

log = get_logger("diag_state")

DIAG_STATE_PATH = data_dir() / "diagnostics_state.json"


def _load():
    try:
        data = json.loads(DIAG_STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def diff_and_record(results):
    """Compare `results` (a list of {name, status, detail}) with the stored run,
    persist the new snapshot, and return
    {"changes": [{"name", "from", "to"}], "previous_run": "<timestamp or None>"}.
    A check that is brand-new (no prior status) is not reported as a change.
    """
    prev = _load()
    prev_status = prev.get("checks") or {}

    changes = []
    now_status = {}
    for c in results:
        name = c.get("name")
        status = c.get("status")
        if not name:
            continue
        now_status[name] = status
        old = prev_status.get(name)
        if old is not None and old != status:
            changes.append({"name": name, "from": old, "to": status})

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        DIAG_STATE_PATH.write_text(
            json.dumps({"at": now, "checks": now_status}, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        log.warning("Couldn't save the diagnostics snapshot: %s", e)

    return {"changes": changes, "previous_run": prev.get("at")}
