import json

from outreach import templates
from outreach.paths import CONFIG_PATH, DEFAULT_EXCEL_PATH

try:  # Python 3.9+
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None


def detect_timezone():
    """Best-effort IANA time zone name for this machine, or "" if it can't be
    determined. Uses tzlocal when installed, then $TZ, then the OS tzinfo key."""
    try:
        import tzlocal

        name = tzlocal.get_localzone_name()
        if name:
            return name
    except Exception:  # noqa: BLE001 - tzlocal missing or detection failed
        pass

    import os
    from datetime import datetime

    tz = os.environ.get("TZ")
    if tz and _is_valid_tz(tz):
        return tz
    key = getattr(datetime.now().astimezone().tzinfo, "key", None)
    return key or ""


def _is_valid_tz(name):
    if not name or ZoneInfo is None:
        return False
    try:
        ZoneInfo(name)
        return True
    except Exception:  # noqa: BLE001
        return False

# Defaults for the reply-handling / auto-scheduling feature. Everything here is
# optional in config.json - an older config that predates the feature still loads
# fine, and callers read these values through `get(cfg, key)` (or `cfg.get(key,
# DEFAULTS[key])`) so a missing key falls back to the default below.
DEFAULTS = {
    "reply_scan_enabled": False,
    # IANA time zone name (e.g. "Europe/Chisinau") used for every calendar
    # booking and reminder. Detected from the machine on install / migration;
    # editable on Settings. Empty or invalid -> Diagnostics warns and the
    # calendar code raises rather than guessing a fixed offset.
    "timezone": "",
    "llm_model": "claude-haiku-4-5-20251001",
    "meeting_duration_minutes": 30,
    "business_hours": {"start": 9, "end": 17},
    "business_days": [0, 1, 2, 3, 4],  # Python weekday(): Mon-Fri
    "scheduling_window_days": 10,
    "min_notice_hours": 24,
    "calendar_id": "primary",
    "reply_lookback_days": 30,
    # Multi-touch follow-up drip (outreach/send_followups.py). Off until the
    # client turns it on in Settings.
    "followup_enabled": False,
    "followup_offsets_days": [3, 7, 14],  # touch N goes out this many days after the cold intro
    "max_followups_per_run": 25,
    # Rules-based lead priority (outreach/scoring.py) - used to order the send
    # queue when the daily cap trims it. A numeric "Priority" cell in the sheet
    # always wins; otherwise this is the fallback score.
    "scoring_rules": {"has_company": 2, "has_phone": 1, "keyword_hit": 3},
    "scoring_keywords": ["urgent", "asap", "quote", "rfp", "rfq", "lane", "dedicated", "contract"],
    # Abort a batch send after this many consecutive failures (revoked token,
    # rate-limit) instead of throwing once per lead through the whole list.
    "send_failure_abort_threshold": 5,
    # Send pacing. Cold + follow-up sends wait a random gap in this range between
    # messages (a fixed interval is a blast fingerprint). Reminders are time
    # sensitive and low volume, so they use a short fixed delay.
    "send_delay_min_seconds": 45,
    "send_delay_max_seconds": 150,
    "reminder_send_delay_seconds": 5,
    # Route replies to a different address. Empty = omit the Reply-To header
    # (recommended). Setting this breaks automated reply detection, which only
    # searches the connected mailbox.
    "reply_to": "",
    # Language a fresh install's templates are seeded in ("en" or "ro"). An
    # existing config keeps whatever it already has; migration back-fills "en".
    "template_language": "en",
}

# New installs are seeded in Romanian (the tool's primary use); the DEFAULTS
# fallback above stays "en" so an older config / a bare cfg dict is legacy-safe.
NEW_INSTALL_LANGUAGE = "ro"


def default_config(lang=None):
    """A complete config.json for a brand-new install. Every field is editable on
    the dashboard's Settings page - there is no setup wizard."""
    lang = lang or NEW_INSTALL_LANGUAGE
    return {
        "sender_name": "",
        "sender_company": "",
        "sender_phone": "",
        "sender_address": "",
        "sender_pitch": "",
        "excel_path": str(DEFAULT_EXCEL_PATH),
        # {logical: header} or {logical: [first_header, last_header]}. Empty means
        # "auto-detect from the sheet's own headers" (outreach/column_map.py).
        "column_map": {},
        "gmail_address": "",
        "reminder_interval_hours": 2,
        "reminder_window_hours": 2,
        "max_reminders_per_run": 60,
        "daily_send_cap": 20,
        "disallowed_domains": [],
        "disallowed_emails": [],
        **templates.defaults(lang),
        **DEFAULTS,
        "timezone": detect_timezone(),
        "template_language": lang,
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

    # An existing config predates the Romanian switch - keep it on English so we
    # don't silently rewrite templates the user may have customised.
    if "template_language" not in cfg:
        cfg["template_language"] = "en"
        changed = True

    # Back-fill any keys added since this file was written, without clobbering
    # the user's own edits (templates, business details, limits). Back-fill uses
    # English template text for the same reason. Note this only ADDS missing keys
    # - an existing daily_send_cap (even one above today's lower default) is kept
    # as the user set it.
    for key, value in default_config("en").items():
        if key not in cfg:
            cfg[key] = value
            changed = True

    # Validate a stored time zone; on a bad value fall back to fresh detection
    # rather than carrying an unusable name into the calendar code.
    stored_tz = str(cfg.get("timezone") or "").strip()
    if stored_tz and not _is_valid_tz(stored_tz):
        from outreach.logging_setup import get_logger

        get_logger("config").warning(
            "Configured timezone %r is not a valid IANA name - re-detecting.", stored_tz
        )
        cfg["timezone"] = detect_timezone()
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
