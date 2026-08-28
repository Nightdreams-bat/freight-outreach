import argparse

from outreach.config import get as cfg_get
from outreach.config import load_config
from outreach.core import (
    apply_daily_cap,
    build_mailer,
    cap_reminders_per_run,
    reminder_candidates,
    send_reminder_batch,
)
from outreach.excel_store import ExcelFileLocked, ExcelStore
from outreach.logging_setup import get_logger
from outreach.bounce_scan import scan_bounces
from outreach.optout_scan import scan_optouts
from outreach.send_tracker import effective_daily_cap

log = get_logger("send_reminders")


def main():
    parser = argparse.ArgumentParser(description="Send 24h-before-meeting reminders.")
    parser.add_argument("--dry-run", action="store_true", help="Preview without sending")
    args = parser.parse_args()

    cfg = load_config()
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

    # Always-on suppression: honour "stop / unsubscribe" replies even with the
    # LLM reply scan switched off. A Gmail error here must not block reminders.
    try:
        opted_out = scan_optouts(cfg, store)
        if opted_out:
            log.info(f"Opt-out scan: suppressed {len(opted_out)} address(es): {', '.join(opted_out)}")
    except Exception as e:  # noqa: BLE001
        log.warning(f"Opt-out scan failed (continuing with reminders): {e}")

    # Always-on deliverability: retire hard-bounced leads. No API cost, so this
    # runs even with the LLM reply scan off. A Gmail error must not block reminders.
    try:
        bounced = scan_bounces(cfg, store)
        if bounced:
            log.info(f"Bounce scan: retired {len(bounced)} hard-bounced lead(s): {', '.join(bounced)}")
    except Exception as e:  # noqa: BLE001
        log.warning(f"Bounce scan failed (continuing with reminders): {e}")

    window_hours = cfg_get(cfg, "reminder_window_hours")
    candidates = reminder_candidates(store, window_hours)

    if not candidates:
        log.info("No reminders due this run.")
        return

    max_per_run = cfg_get(cfg, "max_reminders_per_run")
    n = len(candidates)
    candidates, overflow, aborted = cap_reminders_per_run(candidates, max_per_run)
    if aborted:
        log.critical(
            f"{n} reminders matched this run - far over the per-run cap of {max_per_run}. "
            f"Sending NONE; check clients.xlsx for a data problem (e.g. many rows sharing "
            f"one MeetingDateTime)."
        )
        return
    if overflow:
        log.critical(
            f"{max_per_run + overflow} reminders matched this run, over the per-run cap of "
            f"{max_per_run}. Sending the {max_per_run} with the soonest meetings; the other "
            f"{overflow} will go out on the next run. If this is unexpected, check clients.xlsx "
            f"for a data problem (e.g. many rows with the same MeetingDateTime)."
        )

    if not args.dry_run:
        daily_cap = effective_daily_cap(cfg)
        candidates, _, deferred = apply_daily_cap(
            candidates, daily_cap, sort_key=lambda c: c[2]  # soonest meeting first if capped
        )
        if deferred:
            log.critical(
                f"{deferred} time-sensitive reminder(s) could NOT be sent this run - daily send "
                f"cap ({daily_cap}) reached. Consider raising daily_send_cap in config.json."
            )
        if not candidates:
            return

    mailer = None if args.dry_run else build_mailer(cfg)
    result = send_reminder_batch(cfg, store, mailer, candidates, dry_run=args.dry_run)

    if args.dry_run:
        for item in result["preview"]:
            print(f"[DRY RUN] Would remind {item['email']}:\nSubject: {item['subject']}\n{item['body']}\n{'-' * 40}")
        print("Dry run complete.")
    else:
        log.info(f"Reminder run complete: {result['sent']}/{len(candidates)} sent.")


if __name__ == "__main__":
    main()
