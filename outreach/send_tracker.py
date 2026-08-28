import json
from datetime import date, datetime

from outreach.config import get as cfg_get
from outreach.config import save_config
from outreach.locking import data_lock
from outreach.paths import SEND_HISTORY_PATH as HISTORY_PATH
from outreach.paths import SEND_LOG_PATH as TRACKER_PATH

HISTORY_MAX_ENTRIES = 500


def _load():
    if TRACKER_PATH.exists():
        return json.loads(TRACKER_PATH.read_text(encoding="utf-8"))
    return {}


def _save(data):
    TRACKER_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def sent_today():
    return _load().get(str(date.today()), 0)


def remaining_today(daily_cap):
    return max(0, daily_cap - sent_today())


def record_sent(count=1):
    with data_lock():
        data = _load()
        today = str(date.today())
        data[today] = data.get(today, 0) + count
        if len(data) > 14:  # keep the file small, we only ever need "today"
            for old_day in sorted(data)[:-14]:
                del data[old_day]
        _save(data)


def effective_daily_cap(cfg):
    """The daily send cap in force right now. With warm-up on, this ramps from
    `warmup_start` by `warmup_step_per_day` each day up to `daily_send_cap`."""
    ceiling = int(cfg_get(cfg, "daily_send_cap"))
    if not cfg_get(cfg, "warmup_enabled"):
        return ceiling
    start = int(cfg_get(cfg, "warmup_start"))
    step = int(cfg_get(cfg, "warmup_step_per_day"))
    started_on = str(cfg_get(cfg, "warmup_started_on") or "").strip()
    if not started_on:
        return min(ceiling, start)
    try:
        days = (date.today() - date.fromisoformat(started_on)).days
    except ValueError:
        return min(ceiling, start)
    return min(ceiling, start + step * max(0, days))


def ensure_warmup_started(cfg):
    """Stamp `warmup_started_on` on the first cold send after warm-up is enabled."""
    if cfg_get(cfg, "warmup_enabled") and not str(cfg_get(cfg, "warmup_started_on") or "").strip():
        cfg["warmup_started_on"] = str(date.today())
        save_config(cfg)


def warmup_note(cfg):
    """A short human line for the dashboard, or "" when warm-up is off/complete."""
    if not cfg_get(cfg, "warmup_enabled"):
        return ""
    ceiling = int(cfg_get(cfg, "daily_send_cap"))
    current = effective_daily_cap(cfg)
    if current >= ceiling:
        return ""
    step = int(cfg_get(cfg, "warmup_step_per_day"))
    return f"warming up: {current}/day, +{step}/day → {ceiling}"


def record_send_history(kind, email, name, company, subject):
    entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "kind": kind,
        "email": email,
        "name": name,
        "company": company,
        "subject": subject,
    }
    with data_lock():
        lines = []
        if HISTORY_PATH.exists():
            lines = HISTORY_PATH.read_text(encoding="utf-8").splitlines()
        lines.append(json.dumps(entry))
        lines = lines[-HISTORY_MAX_ENTRIES:]
        HISTORY_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def recent_history(limit=100):
    if not HISTORY_PATH.exists():
        return []
    lines = HISTORY_PATH.read_text(encoding="utf-8").splitlines()
    entries = [json.loads(line) for line in lines if line.strip()]
    return list(reversed(entries))[:limit]
