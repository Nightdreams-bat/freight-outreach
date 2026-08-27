import sys
from pathlib import Path

from outreach.config import CONFIG_PATH, DEFAULTS, save_config
from outreach.excel_store import LOGICAL_COLUMNS
from outreach.templates import (
    COLD_INTRO_BODY,
    COLD_INTRO_SUBJECT,
    DECLINE_ACK_BODY,
    DECLINE_ACK_SUBJECT,
    MEETING_CONFIRM_BODY,
    MEETING_CONFIRM_SUBJECT,
    PROPOSE_TIMES_BODY,
    PROPOSE_TIMES_SUBJECT,
    REMINDER_BODY,
    REMINDER_SUBJECT,
)


def prompt(msg, default=None):
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"{msg}{suffix}: ").strip().lstrip("﻿")
    except EOFError:
        print()
        return default
    return val or default


def prompt_int(msg, default):
    while True:
        raw = prompt(msg, str(default))
        try:
            return int(raw)
        except (TypeError, ValueError):
            print("Please enter a whole number.")


def prompt_column_aliases():
    print("\nExpected Excel columns:", ", ".join(LOGICAL_COLUMNS))
    same = prompt("Does your Excel file use exactly these column headers? (y/n)", "y")
    if same.lower().startswith("y"):
        return {}
    print("Enter the actual header text for each column (leave blank to keep the default name).")
    aliases = {}
    for logical in LOGICAL_COLUMNS:
        actual = prompt(f"  {logical}", logical)
        if actual and actual != logical:
            aliases[logical] = actual
    return aliases


def main():
    print("=== Freight Outreach Setup ===\n")

    sender_name = prompt("Client's full name")
    sender_company = prompt("Client's company name")
    sender_phone = prompt("Client's contact phone")
    sender_pitch = prompt(
        "One-line pitch (e.g. 'We specialize in reefer and dry van freight across the Midwest.')"
    )

    from outreach.paths import DEFAULT_EXCEL_PATH

    excel_path = prompt("Full path to clients.xlsx", str(DEFAULT_EXCEL_PATH))
    column_aliases = prompt_column_aliases()

    interval_hours = prompt_int("How often should the reminder check run, in hours", 2)
    # Window must be >= interval so consecutive checks overlap and no meeting slips
    # through between two runs; this trades reminder-timing precision for the
    # guarantee that every lead gets exactly one reminder.
    window_hours = interval_hours
    max_reminders_per_run = prompt_int(
        "Safety cap: max reminders to send in a single run (protects against bad data "
        "accidentally mass-emailing everyone at once)",
        25,
    )
    daily_send_cap = prompt_int(
        "Daily send cap across cold intros + reminders combined (Gmail itself caps around "
        "500/day; staying well under that protects the account from spam flags)",
        150,
    )

    config = {
        "sender_name": sender_name,
        "sender_company": sender_company,
        "sender_phone": sender_phone,
        "sender_pitch": sender_pitch,
        "excel_path": excel_path,
        "column_aliases": column_aliases,
        "gmail_address": "",
        "reminder_interval_hours": interval_hours,
        "reminder_window_hours": window_hours,
        "max_reminders_per_run": max_reminders_per_run,
        "daily_send_cap": daily_send_cap,
        "disallowed_domains": [],
        "disallowed_emails": [],
        "cold_subject_template": COLD_INTRO_SUBJECT,
        "cold_body_template": COLD_INTRO_BODY,
        "reminder_subject_template": REMINDER_SUBJECT,
        "reminder_body_template": REMINDER_BODY,
        # Reply-handling / auto-scheduling. Off by default; enable it and add an
        # Anthropic API key on the dashboard's Settings page.
        "meeting_confirm_subject_template": MEETING_CONFIRM_SUBJECT,
        "meeting_confirm_body_template": MEETING_CONFIRM_BODY,
        "propose_times_subject_template": PROPOSE_TIMES_SUBJECT,
        "propose_times_body_template": PROPOSE_TIMES_BODY,
        "decline_ack_subject_template": DECLINE_ACK_SUBJECT,
        "decline_ack_body_template": DECLINE_ACK_BODY,
        **DEFAULTS,
    }
    save_config(config)
    print(f"\nSaved config to {CONFIG_PATH}")

    frozen = getattr(sys, "frozen", False)
    open_dashboard = "FreightOutreach.exe" if frozen else "python -m outreach"
    print(
        f"\nOne step left: connect the sending Gmail account. Open the dashboard "
        f"({open_dashboard}) and click 'Connect Gmail' on the Settings page - "
        f"it opens the real Google sign-in screen, no passwords typed here."
    )

    register = prompt(
        "Register a Windows scheduled task to run reminders automatically now? (y/n)", "y"
    )
    if register.lower().startswith("y"):
        from outreach.schedule_task import register_task

        register_task(interval_hours)
    else:
        print("Skipped. You can register it later with: python -m outreach.schedule_task")

    print(
        "\nTo permanently block a domain or address (e.g. after a bounce), use:\n"
        "  python -m outreach.manage_blocklist block-domain example.com\n"
        "  python -m outreach.manage_blocklist block-email person@example.com"
    )


if __name__ == "__main__":
    main()
