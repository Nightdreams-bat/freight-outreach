"""Shared "retire a lead" helper.

Retiring a lead sets `Suppressed="yes"` on its row, appends a dated `Notes`
line, and emits an activity-feed event. `excel_store.rows()` already excludes
suppressed rows, so this one write halts the cold, follow-up, reminder, reply
and opt-out passes at once.

This is a *soft* suppression - a bounce or a dead domain shouldn't permanently
block an address, so nothing here touches the config blocklist.
"""

from datetime import datetime

from kairo.excel_store import ExcelFileLocked
from kairo.lead_fields import lead_company, lead_name
from kairo.logging_setup import get_logger
from kairo.send_tracker import record_send_history

log = get_logger("suppression")


def note_line(existing, text):
    """`existing` with a `"[YYYY-MM-DD] {text}"` line appended (newline-joined)."""
    stamp = datetime.now().strftime("%Y-%m-%d")
    note = f"[{stamp}] {text}"
    existing = str(existing or "").strip()
    return f"{existing}\n{note}" if existing else note


def retire_lead(store, row_idx, values, *, reason):
    """Suppress a lead and log it. Returns True on success, False if the sheet
    was locked (the caller retries next run)."""
    email = str(values.get("Email") or "").strip()
    try:
        store.set_value(row_idx, "Suppressed", "yes")
        store.set_value(row_idx, "Notes", note_line(values.get("Notes"), reason))
    except ExcelFileLocked as e:
        log.warning("Couldn't retire %s (sheet locked): %s", email or row_idx, e)
        return False

    record_send_history(
        "suppressed", email, lead_name(values), lead_company(values), reason
    )
    log.info("Retired lead %s: %s", email or row_idx, reason)
    return True
