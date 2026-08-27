import json

from outreach.paths import CONFIG_PATH

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


def load_config():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"No config.json found at {CONFIG_PATH}. Run the setup wizard first "
            f"(FreightOutreach.exe --setup, or `python -m outreach.setup`)."
        )
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(data):
    CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get(cfg, key):
    """Read a config value, falling back to DEFAULTS for the reply-handling keys.

    Raises KeyError only if the key is unknown to both the config and DEFAULTS.
    """
    if key in cfg:
        return cfg[key]
    return DEFAULTS[key]
