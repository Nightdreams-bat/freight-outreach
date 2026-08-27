import json

from outreach.paths import CONFIG_PATH, DEFAULT_EXCEL_PATH
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

# Defaults for the reply-handling / auto-scheduling feature. Everything here is
# optional in config.json - an older config that predates the feature still loads
# fine, and callers read these values through `get(cfg, key)` (or `cfg.get(key,
# DEFAULTS[key])`) so a missing key falls back to the default below.
DEFAULTS = {
    "reply_scan_enabled": False,
    "llm_model": "claude-haiku-4-5-20251001",
    "meeting_duration_minutes": 30,
    "business_hours": {"start": 9, "end": 17},
    "business_days": [0, 1, 2, 3, 4],  # Python weekday(): Mon-Fri
    "scheduling_window_days": 10,
    "min_notice_hours": 24,
    "calendar_id": "primary",
    "reply_lookback_days": 30,
}


def default_config():
    """A complete config.json for a brand-new install. Every field is editable on
    the dashboard's Settings page - there is no setup wizard."""
    return {
        "sender_name": "",
        "sender_company": "",
        "sender_phone": "",
        "sender_pitch": "",
        "excel_path": str(DEFAULT_EXCEL_PATH),
        # {logical: header} or {logical: [first_header, last_header]}. Empty means
        # "auto-detect from the sheet's own headers" (outreach/column_map.py).
        "column_map": {},
        "gmail_address": "",
        "reminder_interval_hours": 2,
        "reminder_window_hours": 2,
        "max_reminders_per_run": 25,
        "daily_send_cap": 150,
        "disallowed_domains": [],
        "disallowed_emails": [],
        "cold_subject_template": COLD_INTRO_SUBJECT,
        "cold_body_template": COLD_INTRO_BODY,
        "reminder_subject_template": REMINDER_SUBJECT,
        "reminder_body_template": REMINDER_BODY,
        "meeting_confirm_subject_template": MEETING_CONFIRM_SUBJECT,
        "meeting_confirm_body_template": MEETING_CONFIRM_BODY,
        "propose_times_subject_template": PROPOSE_TIMES_SUBJECT,
        "propose_times_body_template": PROPOSE_TIMES_BODY,
        "decline_ack_subject_template": DECLINE_ACK_SUBJECT,
        "decline_ack_body_template": DECLINE_ACK_BODY,
        **DEFAULTS,
    }


def _migrate(cfg):
    """Bring an older config.json up to date. Returns (cfg, changed)."""
    changed = False

    # column_aliases was the wizard's name for the same thing.
    if "column_map" not in cfg:
        cfg["column_map"] = cfg.pop("column_aliases", {}) or {}
        changed = True
    elif "column_aliases" in cfg:
        cfg.pop("column_aliases")
        changed = True

    # Back-fill any keys added since this file was written, without clobbering
    # the user's own edits (templates, business details, limits).
    for key, value in default_config().items():
        if key not in cfg:
            cfg[key] = value
            changed = True

    return cfg, changed


def load_config():
    if not CONFIG_PATH.exists():
        cfg = default_config()
        save_config(cfg)
        return cfg

    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    cfg, changed = _migrate(cfg)
    if changed:
        save_config(cfg)
    return cfg


def save_config(data):
    CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get(cfg, key):
    """Read a config value, falling back to DEFAULTS for the reply-handling keys.

    Raises KeyError only if the key is unknown to both the config and DEFAULTS.
    """
    if key in cfg:
        return cfg[key]
    return DEFAULTS[key]
