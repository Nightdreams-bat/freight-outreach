"""Active health checks for every external thing the tool depends on.

`run_checks(cfg)` returns a list of {"name", "status", "detail"} where status is
"ok", "warn", or "fail". Each check is fully guarded - one failure never breaks
the page or the others. Powers the /diagnostics page and `--selfcheck`.
"""

from datetime import datetime, timedelta

from outreach.logging_setup import get_logger

log = get_logger("diagnostics")


def _ok(name, detail=""):
    return {"name": name, "status": "ok", "detail": detail}


def _warn(name, detail=""):
    return {"name": name, "status": "warn", "detail": detail}


def _fail(name, detail=""):
    return {"name": name, "status": "fail", "detail": detail}


def _check_config(cfg):
    missing = [k for k in ("sender_name", "sender_company") if not (cfg.get(k) or "").strip()]
    if missing:
        return _warn("Business details", f"Not set: {', '.join(missing)} (Settings -> Business details)")
    return _ok("Business details", f"{cfg.get('sender_name')} - {cfg.get('sender_company')}")


def _check_excel(cfg):
    try:
        from outreach.excel_store import ExcelStore

        store = ExcelStore(
            cfg["excel_path"],
            column_map=cfg.get("column_map"),
            disallowed_emails=cfg.get("disallowed_emails"),
            disallowed_domains=cfg.get("disallowed_domains"),
        )
        if store.email_column_missing:
            return _fail("Leads spreadsheet", "No email column found - map one in Settings.")
        n = sum(1 for _ in store.all_rows())
        return _ok("Leads spreadsheet", f"{n} lead(s) readable from {cfg['excel_path']}")
    except Exception as e:  # noqa: BLE001
        return _fail("Leads spreadsheet", f"Can't open it: {e}")


def _gmail_service(cfg):
    from outreach.gmail_oauth import get_credentials
    from googleapiclient.discovery import build

    creds = get_credentials(cfg["gmail_address"])
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _check_gmail_send(cfg):
    if not (cfg.get("gmail_address") or "").strip():
        return _fail("Gmail - account", "No sending account connected (Settings -> Connect Gmail).")
    try:
        svc = _gmail_service(cfg)
        profile = svc.users().getProfile(userId="me").execute()
        return _ok("Gmail - account & token", f"Authorised as {profile.get('emailAddress')}")
    except Exception as e:  # noqa: BLE001
        return _fail("Gmail - account & token", f"{e}")


def _check_gmail_read(cfg):
    if not (cfg.get("gmail_address") or "").strip():
        return _warn("Gmail - read replies", "Connect Gmail first.")
    try:
        svc = _gmail_service(cfg)
        svc.users().threads().list(userId="me", maxResults=1).execute()
        return _ok("Gmail - read replies", "gmail.readonly scope working")
    except Exception as e:  # noqa: BLE001
        return _fail("Gmail - read replies", f"{e} (re-run Connect Gmail to grant the scope)")


def _check_calendar(cfg):
    if not (cfg.get("gmail_address") or "").strip():
        return _warn("Google Calendar", "Connect Gmail first.")
    try:
        from outreach import calendar_api

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


def _check_anthropic(cfg):
    try:
        from outreach.credentials import get_anthropic_key

        key = get_anthropic_key()
    except Exception as e:  # noqa: BLE001
        return _warn("Anthropic API", f"Couldn't read the credential store: {e}")
    if not key:
        return _warn("Anthropic API", "No key set - reply classification stays off (Settings).")
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=key).with_options(timeout=15.0, max_retries=0)
        client.messages.create(
            model=cfg.get("llm_model", "claude-haiku-4-5-20251001"),
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )
        return _ok("Anthropic API", "key valid, model reachable")
    except Exception as e:  # noqa: BLE001
        return _fail("Anthropic API", f"{e}")


def _check_tasks():
    try:
        from outreach.schedule_task import REPLY_TASK_NAME, task_status

        rem = task_status()
        rep = task_status(REPLY_TASK_NAME)
        bits = []
        bits.append("reminder+follow-up scan: " + ("registered" if rem else "not registered"))
        bits.append("reply scan: " + ("registered" if rep else "not registered"))
        status = "ok" if rem else "warn"
        return {"name": "Scheduled tasks", "status": status, "detail": " · ".join(bits)}
    except Exception as e:  # noqa: BLE001
        return _warn("Scheduled tasks", f"{e}")


def run_checks(cfg):
    checks = [
        _check_config,
        _check_excel,
        _check_gmail_send,
        _check_gmail_read,
        _check_calendar,
        _check_anthropic,
    ]
    results = []
    for fn in checks:
        try:
            results.append(fn(cfg))
        except Exception as e:  # noqa: BLE001 - a check must never break the page
            log.warning("diagnostic %s crashed: %s", getattr(fn, "__name__", fn), e)
            results.append(_fail(getattr(fn, "__name__", "check"), str(e)))
    try:
        results.append(_check_tasks())
    except Exception as e:  # noqa: BLE001
        results.append(_warn("Scheduled tasks", str(e)))
    return results
