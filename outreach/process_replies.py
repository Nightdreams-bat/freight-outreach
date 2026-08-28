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
import json
import os
import re
import time
from datetime import datetime

from outreach import gmail_read, llm, llm_tracker, optout_scan, reply_queue, scheduling
from outreach.config import get as cfg_get
from outreach.config import load_config, save_config
from outreach.excel_store import ExcelFileLocked, ExcelStore
from outreach.lead_fields import lead_company, lead_name
from outreach.llm import LLMNotConfigured
from outreach.logging_setup import get_logger
from outreach.paths import REPLY_FAILURES_PATH, REPLY_SCAN_LOCK_PATH

log = get_logger("process_replies")

# Auto-replies / out-of-office bounces - a later genuine reply is a new message
# id, so skipping these costs us nothing and saves a Claude call.
_OOO_RE = re.compile(
    r"out of office|on leave|away until|autoreply|auto-reply|vacation"
    r"|absen[țt][ăa]|concediu",
    re.IGNORECASE,
)

# A reply-scan lock older than this is assumed stale (crashed run) and broken.
_LOCK_STALE_SECONDS = 30 * 60

# A lead in one of these reply states is done - don't keep scanning their thread.
TERMINAL_REPLY_STATES = {"booked", "no"}

# Give up classifying a single message after this many failures (encoding, size,
# an API edge) - mark it processed and log once for manual review.
MAX_CLASSIFY_ATTEMPTS = 3


def _load_failures():
    try:
        data = json.loads(REPLY_FAILURES_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_failures(counts):
    try:
        REPLY_FAILURES_PATH.write_text(json.dumps(counts, indent=0), encoding="utf-8")
    except OSError as e:  # noqa: BLE001
        log.warning("Couldn't persist reply-failure counts: %s", e)


def _bump_failure(counts, message_id):
    counts[message_id] = int(counts.get(message_id, 0)) + 1
    return counts[message_id]


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

    if not _acquire_lock():
        return
    try:
        return _scan(args, cfg)
    finally:
        _release_lock()


def _acquire_lock():
    """True if we got the reply-scan lock; False if another scan holds a fresh one."""
    try:
        if REPLY_SCAN_LOCK_PATH.exists():
            age = time.time() - REPLY_SCAN_LOCK_PATH.stat().st_mtime
            if age < _LOCK_STALE_SECONDS:
                log.warning("reply scan already running, skipping")
                return False
            log.warning("breaking a stale reply-scan lock (%d min old)", int(age / 60))
        REPLY_SCAN_LOCK_PATH.write_text(
            f"{os.getpid()} {datetime.now().isoformat(timespec='seconds')}",
            encoding="utf-8",
        )
    except OSError as e:  # noqa: BLE001 - a lock problem must not stop the scan
        log.warning("couldn't manage the reply-scan lock (%s) - proceeding anyway", e)
    return True


def _release_lock():
    try:
        REPLY_SCAN_LOCK_PATH.unlink()
    except OSError:
        pass


def _scan(args, cfg):
    gmail_address = cfg.get("gmail_address")
    if not gmail_address:
        log.error("No Gmail account connected - connect one in the dashboard first.")
        return

    try:
        store = ExcelStore(
            cfg["excel_path"],
            column_map=cfg.get("column_map"),
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

    max_per_run = int(cfg_get(cfg, "max_classify_per_run"))
    if len(replies) > max_per_run:
        log.critical(
            "%d replies matched this run, over the per-run classify cap of %d. "
            "Classifying the %d oldest; the rest are left for the next run. Raise "
            "max_classify_per_run if this is unexpected.",
            len(replies), max_per_run, max_per_run,
        )
        replies = sorted(replies, key=lambda r: r.get("received_at") or "")[:max_per_run]

    monthly_cap = int(cfg_get(cfg, "max_llm_calls_per_month"))

    model = cfg_get(cfg, "llm_model")
    now_iso = datetime.now().isoformat(timespec="minutes")
    sender_company = cfg.get("sender_company") or ""

    queued = flagged = skipped = classified = failed = 0
    failures = _load_failures()

    for reply in replies:
        email = reply["email"].strip().lower()
        match = by_email.get(email)
        if not match:
            continue
        row_idx, values = match
        message_id = str(reply["message_id"])

        text = (reply.get("text") or "").strip()
        if not text:
            log.info("Reply from %s had no readable text - skipping.", email)
            skipped += 1
            continue

        # Opt-out / OOO regex pre-filter - handled without a Claude call.
        if optout_scan.OPTOUT_RE.search(text):
            try:
                store.set_value(row_idx, "ReplyStatus", "optout")
            except ExcelFileLocked as e:
                log.warning("Couldn't stamp ReplyStatus for %s: %s", email, e)
            disallowed = cfg.setdefault("disallowed_emails", [])
            if email not in {str(x).strip().lower() for x in disallowed}:
                disallowed.append(email)
                save_config(cfg)
            gmail_read.mark_processed([message_id])
            log.info("Opt-out detected from %s - added to the blocklist (no Claude call).", email)
            skipped += 1
            continue

        if _OOO_RE.search(text):
            log.info("Auto-reply / out-of-office from %s - skipping (no Claude call).", email)
            gmail_read.mark_processed([message_id])
            skipped += 1
            continue

        if llm_tracker.remaining_this_month(monthly_cap) <= 0:
            log.critical(
                "monthly LLM call cap reached; raise max_llm_calls_per_month or "
                "wait for next month"
            )
            break

        try:
            classification = llm.classify_reply(
                text, sender_company=sender_company, now_iso=now_iso, model=model
            )
        except LLMNotConfigured:
            log.error("No Anthropic API key set - add one in Settings to classify replies.")
            _save_failures(failures)
            return _summary(classified, queued, flagged, failed, skipped)
        except Exception as e:  # noqa: BLE001
            attempts = _bump_failure(failures, message_id)
            if attempts >= MAX_CLASSIFY_ATTEMPTS:
                log.error(
                    "Giving up on the reply from %s after %d failed classification "
                    "attempts (%s) - marking it processed. Review it by hand in Gmail.",
                    email, attempts, e,
                )
                gmail_read.mark_processed([message_id])
                failures.pop(message_id, None)
                failed += 1
            else:
                log.error("Could not classify the reply from %s (attempt %d/%d: %s) - will retry.",
                          email, attempts, MAX_CLASSIFY_ATTEMPTS, e)
                skipped += 1
            continue

        classified += 1
        llm_tracker.record_llm_call(1)
        failures.pop(message_id, None)
        intent = classification.get("intent") or ""
        summary = classification.get("summary") or ""
        action = scheduling.plan_action(classification, values, cfg, gmail_address)

        if args.dry_run:
            kind = action.get("kind") if action else None
            print(f"[DRY RUN] {email}: intent={intent}, action={kind}")
            print(f"          {summary}")
            continue

        # Mark processed immediately - a crash after this loses at most an
        # enqueue (logged, recoverable), never re-bills the classify.
        gmail_read.mark_processed([message_id])

        if action is not None:
            reply_queue.enqueue(
                action,
                lead_row_idx=row_idx,
                lead_email=reply["email"],
                lead_name=lead_name(values),
                lead_company=lead_company(values),
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

    _save_failures(failures)
    log.info(
        "Reply scan complete: %d classified, %d queued for approval, %d flagged for "
        "manual scheduling, %d gave up, %d skipped (will retry).",
        classified, queued, flagged, failed, skipped,
    )
    return _summary(classified, queued, flagged, failed, skipped)


def _summary(classified, queued, flagged, failed, skipped):
    return {
        "classified": classified,
        "enqueued": queued,
        "flagged": flagged,
        "failed": failed,
        "skipped": skipped,
        "errors": [],
    }


if __name__ == "__main__":
    main()
