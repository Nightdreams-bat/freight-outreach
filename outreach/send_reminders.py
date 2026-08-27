import argparse

from outreach.config import load_config
from outreach.core import apply_daily_cap, build_mailer, reminder_candidates, send_reminder_batch
from outreach.excel_store import ExcelFileLocked, ExcelStore
from outreach.logging_setup import get_logger

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

    window_hours = cfg.get("reminder_window_hours", 2)
    candidates = reminder_candidates(store, window_hours)

    if not candidates:
        log.info("No reminders due this run.")
        return

    max_per_run = cfg.get("max_reminders_per_run", 25)
    if len(candidates) > max_per_run:
        log.critical(
            f"{len(candidates)} reminders matched this run, which exceeds the safety cap of "
            f"{max_per_run}. Sending NONE - check clients.xlsx for a data problem "
            f"(e.g. many rows with the same MeetingDateTime), then run send_reminders.py "
            f"manually once you've confirmed it's correct."
        )
        return

    if not args.dry_run:
        daily_cap = cfg.get("daily_send_cap", 150)
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
