"""Send the next follow-up nudge to cold leads who haven't replied or booked.

Opt-in: does nothing unless `followup_enabled` is true in config.json. Runs
alongside the reminder scan on the hourly scheduled task, or on demand:

    python -m kairo --followup            # send now
    python -m kairo --followup --dry-run  # preview only
"""

import argparse

from kairo.config import get as cfg_get
from kairo.config import load_config
from kairo.core import (
    apply_daily_cap,
    build_mailer,
    followup_candidates,
    priority_sort_key,
    send_followup_batch,
)
from kairo.excel_store import ExcelFileLocked, ExcelStore
from kairo.logging_setup import get_logger
from kairo.send_tracker import effective_daily_cap

log = get_logger("send_followups")


def main():
    parser = argparse.ArgumentParser(description="Send multi-touch follow-up nudges.")
    parser.add_argument("--dry-run", action="store_true", help="Preview without sending")
    args = parser.parse_args()

    cfg = load_config()
    if not cfg_get(cfg, "followup_enabled"):
        log.info("Follow-up drip is off (followup_enabled=false). Nothing to do.")
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

    candidates = followup_candidates(store, cfg)
    if not candidates:
        log.info("No follow-ups due this run.")
        return

    max_per_run = cfg_get(cfg, "max_followups_per_run")
    if len(candidates) > max_per_run:
        log.critical(
            f"{len(candidates)} follow-ups matched this run, over the safety cap of "
            f"{max_per_run}. Sending NONE - check clients.xlsx, then raise "
            f"max_followups_per_run once you've confirmed it's correct."
        )
        return

    if not args.dry_run:
        daily_cap = effective_daily_cap(cfg)
        candidates, _, deferred = apply_daily_cap(
            candidates, daily_cap, sort_key=priority_sort_key(cfg)
        )
        if deferred:
            log.warning(
                f"{deferred} follow-up(s) deferred to the next run - today's send cap "
                f"({daily_cap}) doesn't leave room for them."
            )
        if not candidates:
            log.warning("Daily send cap already reached for today.")
            return

    mailer = None if args.dry_run else build_mailer(cfg)
    result = send_followup_batch(cfg, store, mailer, candidates, dry_run=args.dry_run)

    if args.dry_run:
        for item in result["preview"]:
            print(f"[DRY RUN] Would follow up with {item['email']}:\n"
                  f"Subject: {item['subject']}\n{item['body']}\n{'-' * 40}")
        print("Dry run complete.")
    else:
        log.info(f"Follow-up run complete: {result['sent']}/{len(candidates)} sent.")


if __name__ == "__main__":
    main()
