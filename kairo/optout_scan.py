"""Keyword-only opt-out scan - the always-on suppression safety net.

Unlike `process_replies.py`, this needs no Anthropic key and runs even when
`reply_scan_enabled` is false. It reads inbound replies for leads still awaiting
a response and, for any whose text plainly says "stop / unsubscribe / remove me"
(English or Romanian), it:

  * sets the lead's ReplyStatus to "optout",
  * adds the address to `disallowed_emails` in config.json (so every future
    cold / follow-up / reminder batch filters it out via ExcelStore), and
  * marks the Gmail message processed so it isn't re-examined.

Called from `send_reminders.main()` before the reminder/follow-up passes.
"""

import re

from kairo import gmail_read
from kairo.config import get as cfg_get
from kairo.config import save_config
from kairo.logging_setup import get_logger

log = get_logger("optout_scan")

# Case-insensitive. EN + RO phrasings a lead uses to ask off the list.
OPTOUT_RE = re.compile(
    r"unsubscribe|stop|remove me|opt out|do not contact|take me off"
    r"|unsubscrie|dezabon|nu m[ăa] contacta|scoate[țt]i-m[ăa]",
    re.IGNORECASE,
)


def _awaiting(store):
    """(row_idx, values) for leads that got a cold email and aren't already
    in a terminal reply state."""
    terminal = {"booked", "no", "optout"}
    for row_idx, values in store.rows():
        if not values.get("ColdEmailSentAt"):
            continue
        if str(values.get("ReplyStatus") or "").strip().lower() in terminal:
            continue
        yield row_idx, values


def scan_optouts(cfg, store):
    """Returns the list of addresses newly opted out this run (possibly empty)."""
    gmail_address = cfg.get("gmail_address")
    if not gmail_address:
        return []

    by_email = {}
    for row_idx, values in _awaiting(store):
        email = str(values.get("Email") or "").strip().lower()
        if email and email not in by_email:
            by_email[email] = (row_idx, values)
    if not by_email:
        return []

    lookback = int(cfg_get(cfg, "reply_lookback_days"))
    replies = gmail_read.fetch_new_replies(gmail_address, lookback, list(by_email))

    disallowed = cfg.setdefault("disallowed_emails", [])
    known = {str(e).strip().lower() for e in disallowed}
    opted_out = []

    for reply in replies:
        email = str(reply.get("email") or "").strip().lower()
        match = by_email.get(email)
        if not match:
            continue
        text = reply.get("text") or ""
        if not OPTOUT_RE.search(text):
            # Leave it untouched - the LLM reply scan (if enabled) still sees it.
            continue

        row_idx, _ = match
        try:
            store.set_value(row_idx, "ReplyStatus", "optout")
        except Exception as e:  # noqa: BLE001 - a locked sheet shouldn't lose the suppression
            log.warning("Couldn't stamp ReplyStatus for %s: %s", email, e)

        if email not in known:
            disallowed.append(email)
            known.add(email)
            save_config(cfg)
        gmail_read.mark_processed([reply["message_id"]])
        opted_out.append(email)
        log.info("Opt-out detected from %s - added to the permanent blocklist.", email)

    return opted_out
