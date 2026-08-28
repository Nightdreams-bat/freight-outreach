"""Bounce detection + auto-suppress - the always-on deliverability safety net.

Like `optout_scan.py`, this needs no Anthropic key and runs even when
`reply_scan_enabled` is false. It reads Gmail delivery-failure notices (NDRs)
for leads we've cold-emailed and, for any whose address hard-bounced (5.x.x):

  * retires the lead (`Suppressed="yes"` + a dated Notes line + an activity
    event), which halts every future pass for that address, and
  * marks the NDR processed so it isn't re-examined.

Transient failures (4.x.x) are only marked processed - the sequence continues.

Called from `send_reminders.main()` beside `scan_optouts`.
"""

from kairo import gmail_read, suppression
from kairo.config import get as cfg_get
from kairo.logging_setup import get_logger

log = get_logger("bounce_scan")


def _emailed(store):
    """(row_idx, values) for leads that got a cold email and aren't booked."""
    for row_idx, values in store.rows():
        if not values.get("ColdEmailSentAt"):
            continue
        if str(values.get("ReplyStatus") or "").strip().lower() in {"booked"}:
            continue
        yield row_idx, values


def scan_bounces(cfg, store):
    """Returns the list of addresses retired for a hard bounce this run."""
    gmail_address = cfg.get("gmail_address")
    if not gmail_address:
        return []

    by_email = {}
    for row_idx, values in _emailed(store):
        email = str(values.get("Email") or "").strip().lower()
        if email and email not in by_email:
            by_email[email] = (row_idx, values)
    if not by_email:
        return []

    lookback = int(cfg_get(cfg, "reply_lookback_days"))
    bounces = gmail_read.fetch_bounces(gmail_address, lookback)

    retired = []
    for bounce in bounces:
        email = str(bounce.get("failed_email") or "").strip().lower()
        match = by_email.get(email)
        if not match:
            continue
        row_idx, values = match
        message_id = bounce.get("message_id")

        if bounce.get("permanent"):
            ok = suppression.retire_lead(
                store, row_idx, values,
                reason=f"undeliverable: hard bounce ({email})",
            )
            if not ok:
                # sheet locked - leave the NDR unprocessed and retry next run
                continue
            retired.append(email)
            log.info("Hard bounce from %s - lead retired.", email)

        if message_id:
            gmail_read.mark_processed([message_id])

    return retired
