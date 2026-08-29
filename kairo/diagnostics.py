"""Active health checks for every external thing the tool depends on.

`run_checks(cfg)` returns a list of {"name", "status", "detail"} where status is
"ok", "warn", or "fail". Each check is fully guarded - one failure never breaks
the page or the others. The checks run concurrently (the Anthropic ping and the
three Google round-trips dominate), so the whole set finishes in ~2-3s instead
of ~7s. Powers the /diagnostics page and `--selfcheck`.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from kairo.config import get as cfg_get
from kairo.logging_setup import get_logger

log = get_logger("diagnostics")

# Stable, order-fixed names so the /diagnostics page can match async results to
# the placeholder rows it renders first.
CHECK_NAMES = [
    "Business details",
    "Postal address",
    "Leads spreadsheet",
    "Time zone",
    "Gmail - account & token",
    "Gmail - read replies",
    "Google Calendar",
    "Anthropic API",
    "Scheduled tasks",
]


def _ok(name, detail=""):
    return {"name": name, "status": "ok", "detail": detail}


def _warn(name, detail=""):
    return {"name": name, "status": "warn", "detail": detail}


def _fail(name, detail=""):
    return {"name": name, "status": "fail", "detail": detail}


# --- shared Gmail service ---------------------------------------------------
# Built once per run_checks() call and reused by both Gmail checks, so the
# discovery document is only downloaded once.

class _GmailCtx:
    def __init__(self, cfg):
        self.cfg = cfg
        self._lock = threading.Lock()
        self._svc = None
        self._err = None

    def service(self):
        with self._lock:
            if self._svc is None and self._err is None:
                try:
                    from googleapiclient.discovery import build

                    from kairo.gmail_oauth import get_credentials

                    creds = get_credentials(self.cfg["gmail_address"])
                    try:
                        self._svc = build("gmail", "v1", credentials=creds,
                                          cache_discovery=False, static_discovery=True)
                    except TypeError:  # older googleapiclient without static_discovery
                        self._svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
                except Exception as e:  # noqa: BLE001
                    self._err = e
            if self._err is not None:
                raise self._err
            return self._svc


# --- individual checks ----------------------------------------------------

def _check_config(cfg, _gmail):
    missing = [k for k in ("sender_name", "sender_company") if not (cfg.get(k) or "").strip()]
    if missing:
        return _warn("Business details", f"Not set: {', '.join(missing)} (Settings -> Business details)")
    return _ok("Business details", f"{cfg.get('sender_name')} - {cfg.get('sender_company')}")


def _check_postal_address(cfg, _gmail):
    if not (cfg.get("sender_address") or "").strip():
        return _warn(
            "Postal address",
            "No postal address set - required by anti-spam law. Settings -> Business details.",
        )
    return _ok("Postal address", "included in every email footer")


def _check_excel(cfg, _gmail):
    try:
        from kairo.excel_store import ExcelFileMissing, ExcelStore

        try:
            store = ExcelStore(
                cfg["excel_path"],
                column_map=cfg.get("column_map"),
                disallowed_emails=cfg.get("disallowed_emails"),
                disallowed_domains=cfg.get("disallowed_domains"),
                create_if_missing=False,
            )
        except ExcelFileMissing:
            return _fail(
                "Leads spreadsheet",
                f"File not found: {cfg['excel_path']} - restore it or pick another "
                f"under Settings. Kairo will not recreate a deleted leads file.",
            )
        if store.email_column_missing:
            return _fail("Leads spreadsheet", "No email column found - map one in Settings.")
        n = sum(1 for _ in store.all_rows())
        return _ok("Leads spreadsheet", f"{n} lead(s) readable from {cfg['excel_path']}")
    except Exception as e:  # noqa: BLE001
        return _fail("Leads spreadsheet", f"Can't open it: {e}")


def _stale_token_note(gmail_address):
    """A warning string if the stored OAuth token looks like it hasn't been
    refreshed in >5 days (Testing-mode refresh tokens die after 7), or None if
    that can't be determined from the token JSON."""
    try:
        import json
        from datetime import timezone

        from kairo.credentials import get_oauth_token

        raw = json.loads(get_oauth_token(gmail_address)).get("expiry")
        if not raw:
            return None
        expiry = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - expiry).total_seconds() / 86400
        if age_days > 5:
            return (f"token last refreshed ~{int(age_days)}d ago - if sends start failing, "
                    f"click Connect Gmail again (Testing-mode tokens expire after 7 days)")
    except Exception:  # noqa: BLE001
        return None
    return None


def _check_timezone(cfg, _gmail):
    name = str(cfg.get("timezone") or "").strip()
    if not name:
        from kairo.config import detect_timezone

        guess = detect_timezone()
        if guess:
            return _warn("Time zone", f"Not set - would auto-detect '{guess}'. Set it in Settings.")
        return _warn("Time zone", "Not set and can't be auto-detected - set an IANA name in Settings "
                                  "(e.g. Europe/Chisinau). Calendar bookings will fail without it.")
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(name)
    except Exception as e:  # noqa: BLE001
        return _warn("Time zone", f"'{name}' is not a valid IANA name ({e}). Fix it in Settings.")
    return _ok("Time zone", name)


def _check_gmail_send(cfg, gmail):
    if not (cfg.get("gmail_address") or "").strip():
        return _fail("Gmail - account & token", "No sending account connected (Settings -> Connect Gmail).")
    # Read the stored token age before gmail.service() refreshes it.
    stale = _stale_token_note(cfg["gmail_address"])
    try:
        profile = gmail.service().users().getProfile(userId="me").execute()
        detail = f"Authorised as {profile.get('emailAddress')}"
        if stale:
            return _warn("Gmail - account & token", f"{detail} - {stale}")
        return _ok("Gmail - account & token", detail)
    except Exception as e:  # noqa: BLE001
        return _fail("Gmail - account & token", f"{e}")


def _check_gmail_read(cfg, gmail):
    if not (cfg.get("gmail_address") or "").strip():
        return _warn("Gmail - read replies", "Connect Gmail first.")
    try:
        gmail.service().users().threads().list(userId="me", maxResults=1).execute()
        return _ok("Gmail - read replies", "gmail.readonly scope working")
    except Exception as e:  # noqa: BLE001
        return _fail("Gmail - read replies", f"{e} (re-run Connect Gmail to grant the scope)")


def _check_calendar(cfg, _gmail):
    if not (cfg.get("gmail_address") or "").strip():
        return _warn("Google Calendar", "Connect Gmail first.")
    try:
        from kairo import calendar_api

        now = datetime.now()
        calendar_api.busy_intervals(
            cfg["gmail_address"],
            cfg.get("calendar_id", "primary"),
            calendar_api._to_rfc3339(now),
            calendar_api._to_rfc3339(now + timedelta(hours=1)),
        )
        return _ok("Google Calendar", "free/busy lookup on '%s' working" % cfg.get("calendar_id", "primary"))
    except Exception as e:  # noqa: BLE001
        return _fail("Google Calendar", f"{e} (re-run Connect Gmail to grant calendar scopes)")


def _check_anthropic(cfg, _gmail):
    try:
        from kairo.credentials import get_anthropic_key

        key = get_anthropic_key()
    except Exception as e:  # noqa: BLE001
        return _warn("Anthropic API", f"Couldn't read the credential store: {e}")
    if not key:
        return _warn("Anthropic API", "No key set - reply classification stays off (Settings).")

    from kairo import llm_tracker

    cap = int(cfg_get(cfg, "max_llm_calls_per_month"))
    if llm_tracker.remaining_this_month(cap) <= 0:
        return _warn("Anthropic API", "monthly call cap reached")
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=key).with_options(timeout=15.0, max_retries=0)
        client.messages.create(
            model=cfg.get("llm_model", "claude-haiku-4-5-20251001"),
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )
        llm_tracker.record_llm_call(1)
        return _ok(
            "Anthropic API",
            f"key valid, model reachable ({llm_tracker.calls_this_month()}/{cap} calls this month)",
        )
    except Exception as e:  # noqa: BLE001
        return _fail("Anthropic API", f"{e}")


def _check_tasks(cfg, _gmail):
    try:
        from kairo.schedule_task import REPLY_TASK_NAME, task_status

        rem = task_status()
        rep = task_status(REPLY_TASK_NAME)
        bits = [
            "reminder+follow-up scan: " + ("registered" if rem else "not registered"),
            "reply scan: " + ("registered" if rep else "not registered"),
        ]
        return {"name": "Scheduled tasks", "status": "ok" if rem else "warn", "detail": " · ".join(bits)}
    except Exception as e:  # noqa: BLE001
        return _warn("Scheduled tasks", f"{e}")


_CHECKS = [
    _check_config,
    _check_postal_address,
    _check_excel,
    _check_timezone,
    _check_gmail_send,
    _check_gmail_read,
    _check_calendar,
    _check_anthropic,
    _check_tasks,
]


def run_checks(cfg):
    gmail = _GmailCtx(cfg)

    def _run(fn):
        try:
            return fn(cfg, gmail)
        except Exception as e:  # noqa: BLE001 - a check must never break the page
            log.warning("diagnostic %s crashed: %s", getattr(fn, "__name__", fn), e)
            return _fail(getattr(fn, "__name__", "check").replace("_check_", "").title(), str(e))

    with ThreadPoolExecutor(max_workers=len(_CHECKS)) as pool:
        return list(pool.map(_run, _CHECKS))
