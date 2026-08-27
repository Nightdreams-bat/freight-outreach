"""Scan Gmail for lead replies, classify each with Claude, and queue a drafted
action for the client to approve. Mirrors `send_reminders.py`.

This NEVER sends an email or books a meeting - it only reads Gmail and writes to
the local approval queue and the sheet. The actual outward actions happen in
`reply_queue.approve` when the client clicks Approve on the dashboard.

Run headless on a timer (the FreightOutreach_ReplyCheck scheduled task) or from
the CLI: `python -m outreach --replies` (add `--dry-run` to classify without
queueing or touching the sheet).
"""

import argparse
from datetime import datetime

from outreach import gmail_read, llm, reply_queue, scheduling
from outreach.config import get as cfg_get
from outreach.config import load_config
from outreach.excel_store import ExcelFileLocked, ExcelStore
from outreach.llm import LLMNotConfigured
from outreach.logging_setup import get_logger

log = get_logger("process_replies")

# A lead in one of these reply states is done - don't keep scanning their thread.
TERMINAL_REPLY_STATES = {"booked", "no"}


def _awaiting_reply(store):
    """(row_idx, values) for leads that got a cold email and haven't reached a
    terminal reply state."""
    for row_idx, values in store.rows():
        if not values.get("ColdEmailSentAt"):
            continue
        if str(values.get("ReplyStatus") or "").strip().lower() in TERMINAL_REPLY_STATES:
            continue
        yield row_idx, values


def _append_note(existing, summary):
    stamp = datetime.now().strftime("%Y-%m-%d")
    note = f"[{stamp}] reply: {summary}"
    existing = str(existing or "").strip()
    return f"{existing}\n{note}" if existing else note


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Scan Gmail for lead replies, classify them, and queue drafted actions."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify and print, but don't queue anything or touch the sheet.",
    )
    args = parser.parse_args(argv)

    cfg = load_config()
    if not cfg_get(cfg, "reply_scan_enabled"):
        log.info("Reply scan is off (reply_scan_enabled=false in config). Nothing to do.")
        return

    gmail_address = cfg.get("gmail_address")
    if not gmail_address:
        log.error("No Gmail account connected - connect one in the dashboard first.")
        return

    try:
        store = ExcelStore(
            cfg["excel_path"],
            column_aliases=cfg.get("column_aliases"),
            disallowed_emails=cfg.get("disallowed_emails"),
            disallowed_domains=cfg.get("disallowed_domains"),
        )
    except ExcelFileLocked as e:
        log.error(str(e))
        return

    by_email = {}
    for row_idx, values in _awaiting_reply(store):
        email = str(values.get("Email") or "").strip().lower()
        if email and email not in by_email:
            by_email[email] = (row_idx, values)

    if not by_email:
        log.info("No leads are awaiting a reply.")
        return

    lookback = int(cfg_get(cfg, "reply_lookback_days"))
    try:
        replies = gmail_read.fetch_new_replies(gmail_address, lookback, list(by_email))
    except Exception as e:  # noqa: BLE001
        log.error("Reading Gmail failed: %s", e)
        return

    if not replies:
        log.info("No new replies.")
        return

    model = cfg_get(cfg, "llm_model")
    now_iso = datetime.now().isoformat(timespec="minutes")
    sender_company = cfg.get("sender_company") or ""

    queued = flagged = skipped = 0

    for reply in replies:
        email = reply["email"].strip().lower()
        match = by_email.get(email)
        if not match:
            continue
        row_idx, values = match

        text = (reply.get("text") or "").strip()
        if not text:
            log.info("Reply from %s had no readable text - skipping.", email)
            skipped += 1
            continue

        try:
            classification = llm.classify_reply(
                text, sender_company=sender_company, now_iso=now_iso, model=model
            )
        except LLMNotConfigured:
            log.error("No Anthropic API key set - add one in Settings to classify replies.")
            return
        except Exception as e:  # noqa: BLE001
            log.error("Could not classify the reply from %s (%s) - skipping.", email, e)
            skipped += 1
            continue

        intent = classification.get("intent") or ""
        summary = classification.get("summary") or ""
        action = scheduling.plan_action(classification, values, cfg, gmail_address)

        if args.dry_run:
            kind = action.get("kind") if action else None
            print(f"[DRY RUN] {email}: intent={intent}, action={kind}")
            print(f"          {summary}")
            continue

        if action is not None:
            reply_queue.enqueue(
                action,
                lead_row_idx=row_idx,
                lead_email=reply["email"],
                lead_name=values.get("Name") or "",
                lead_company=values.get("Company") or "",
                thread_id=reply.get("thread_id") or "",
                reply_summary=summary,
            )
            if action.get("kind") == "manual":
                flagged += 1
            else:
                queued += 1

        try:
            store.set_value(row_idx, "ReplyStatus", intent)
            store.set_value(
                row_idx,
                "LastReplyAt",
                reply.get("received_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            if summary:
                store.set_value(row_idx, "Notes", _append_note(values.get("Notes"), summary))
        except ExcelFileLocked as e:
            log.warning("Couldn't update the sheet for %s: %s", email, e)

        gmail_read.mark_processed([reply["message_id"]])

    log.info(
        "Reply scan complete: %d queued for approval, %d flagged for manual scheduling, %d skipped.",
        queued,
        flagged,
        skipped,
    )


if __name__ == "__main__":
    main()
