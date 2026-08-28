import argparse

from kairo.config import get as cfg_get
from kairo.config import load_config
from kairo.core import apply_daily_cap, build_mailer, cold_candidates, send_cold_batch
from kairo.excel_store import ExcelFileLocked, ExcelStore
from kairo.logging_setup import get_logger
from kairo.send_tracker import effective_daily_cap, ensure_warmup_started

log = get_logger("send_cold")


def main():
    parser = argparse.ArgumentParser(description="Send cold-intro emails to new leads.")
    parser.add_argument("--dry-run", action="store_true", help="Preview without sending")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip the confirmation prompt")
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

    candidates = cold_candidates(store)
    if not candidates:
        log.info("No new leads to email.")
        return

    if not args.dry_run:
        ensure_warmup_started(cfg)
        cap = effective_daily_cap(cfg)
        candidates, _, deferred = apply_daily_cap(candidates, cap)
        if deferred:
            log.warning(
                f"{deferred} lead(s) deferred to the next run - today's send cap "
                f"({cap}) doesn't leave room for them."
            )
        if not candidates:
            log.warning("Daily send cap already reached for today. Try again tomorrow.")
            return

        if not args.yes:
            print(f"About to send {len(candidates)} cold intro email(s). Continue? (y/n)")
            if not input("> ").strip().lower().startswith("y"):
                print("Cancelled.")
                return

    mailer = None if args.dry_run else build_mailer(cfg)
    result = send_cold_batch(cfg, store, mailer, candidates, dry_run=args.dry_run)

    if args.dry_run:
        for item in result["preview"]:
            print(f"[DRY RUN] Would send to {item['email']}:\nSubject: {item['subject']}\n{item['body']}\n{'-' * 40}")
        print("Dry run complete.")
    else:
        log.info(f"Cold intro run complete: {result['sent']}/{len(candidates)} sent.")


if __name__ == "__main__":
    main()
