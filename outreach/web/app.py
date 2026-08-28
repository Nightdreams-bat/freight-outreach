import secrets
import socket
import threading
import webbrowser
from datetime import datetime

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, url_for

from outreach import lead_sourcing, reply_queue, templates
from outreach.config import get as cfg_get
from outreach.config import load_config, save_config
from outreach.credentials import get_anthropic_key, set_anthropic_key
from outreach.logging_setup import get_logger
from outreach.optout_scan import scan_optouts
from outreach.paths import LOG_PATH, resource_path
from outreach.core import (
    apply_daily_cap,
    build_mailer,
    cap_reminders_per_run,
    cold_candidates,
    followup_candidates,
    priority_sort_key,
    reminder_candidates,
    send_cold_batch,
    send_followup_batch,
    send_reminder_batch,
)
from outreach.diagnostics import CHECK_NAMES, run_checks
from outreach.excel_store import ExcelFileLocked, ExcelStore, sheet_headers
from outreach.column_map import detect as detect_columns
from outreach.gmail_oauth import run_oauth_flow
from outreach.schedule_task import (
    REPLY_TASK_NAME,
    register_task,
    task_status,
    unregister_task,
)
from outreach.scoring import is_manual as priority_is_manual
from outreach.scoring import score_lead
from outreach.send_tracker import recent_history, remaining_today, sent_today

log = get_logger("web")

SUPPRESSED_TRUE_VALUES = ("1", "true", "yes", "y")


def _is_valid_timezone(name):
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(name)
        return True
    except Exception:  # noqa: BLE001
        return False

# Hostnames the dashboard is ever legitimately reached on. The port varies
# (_pick_port), so only the host part is checked.
_ALLOWED_HOSTS = ("127.0.0.1", "localhost")
_SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def _host_only(value):
    """'127.0.0.1:5000' -> '127.0.0.1'; strips an optional :port."""
    return (value or "").rsplit(":", 1)[0].strip("[]").lower()


def _same_origin_ok():
    """True if this request is safe to treat as coming from our own dashboard:
    a loopback Host, and an Origin/Referer that is absent or same-origin."""
    if _host_only(request.host) not in _ALLOWED_HOSTS:
        return False
    expected = f"{request.scheme}://{request.host}"
    origin = request.headers.get("Origin")
    if origin:
        return origin == expected
    referer = request.headers.get("Referer")
    if referer:
        return _host_only(referer.split("://", 1)[-1].split("/", 1)[0]) in _ALLOWED_HOSTS
    return True

# ---- manual "Run now" jobs (Dashboard) ------------------------------------
# One background job at a time, in-process (no subprocess - avoids a PyInstaller
# re-exec). The scheduled tasks are entirely separate from this.
_JOB = {"status": "idle", "severity": "idle", "action": None, "started": None,
        "finished": None, "summary": None}
_JOB_LOCK = threading.Lock()
_RUN_ACTIONS = ("cold", "followups", "reminders", "replies")

# Last /find-leads result, so the import step doesn't re-run the search. Single
# user, one search at a time - a module-level slot is enough.
_LEADS_LAST = {"what": "", "where": "", "scrape": True, "leads": []}


def _run_job(action):
    cfg = load_config()
    severity = "success"
    try:
        store = ExcelStore(
            cfg["excel_path"],
            column_map=cfg.get("column_map"),
            disallowed_emails=cfg.get("disallowed_emails"),
            disallowed_domains=cfg.get("disallowed_domains"),
        ) if action != "replies" else None

        if action == "cold":
            cands, _, deferred = apply_daily_cap(
                cold_candidates(store), cfg_get(cfg, "daily_send_cap"),
                sort_key=priority_sort_key(cfg),
            )
            r = send_cold_batch(cfg, store, build_mailer(cfg), cands) if cands else {"sent": 0, "errors": []}
            summary = f"{r['sent']} cold intro(s) sent"
            if deferred:
                summary += f", {deferred} deferred (daily cap)"
                severity = "warning"
        elif action == "followups":
            if not cfg_get(cfg, "followup_enabled"):
                r = {"sent": 0, "errors": []}
                summary = "Follow-up drip is off - turn it on in Settings first"
                severity = "warning"
            else:
                raw = followup_candidates(store, cfg)
                max_per_run = cfg_get(cfg, "max_followups_per_run")
                if len(raw) > max_per_run:
                    r = {"sent": 0, "errors": []}
                    summary = (f"{len(raw)} follow-ups matched, over the safety cap of "
                               f"{max_per_run} - sent none, check clients.xlsx")
                    severity = "danger"
                else:
                    cands, _, deferred = apply_daily_cap(
                        raw, cfg_get(cfg, "daily_send_cap"), sort_key=priority_sort_key(cfg),
                    )
                    r = send_followup_batch(cfg, store, build_mailer(cfg), cands) if cands else {"sent": 0, "errors": []}
                    summary = f"{r['sent']} follow-up(s) sent"
                    if deferred:
                        summary += f", {deferred} deferred (daily cap)"
                        severity = "warning"
        elif action == "reminders":
            try:
                scan_optouts(cfg, store)
            except Exception as e:  # noqa: BLE001
                log.warning(f"Opt-out scan failed (continuing with reminders): {e}")
            cands = reminder_candidates(store, cfg_get(cfg, "reminder_window_hours"))
            n = len(cands)
            cands, overflow, aborted = cap_reminders_per_run(
                cands, cfg_get(cfg, "max_reminders_per_run")
            )
            if aborted:
                r = {"sent": 0, "errors": []}
                severity = "danger"
                summary = (f"{n} reminders matched - far over the safety cap, sent none. "
                           f"Check clients.xlsx.")
            else:
                cands, _, deferred = apply_daily_cap(
                    cands, cfg_get(cfg, "daily_send_cap"), sort_key=lambda c: c[2]
                )
                r = send_reminder_batch(cfg, store, build_mailer(cfg), cands) if cands else {"sent": 0, "errors": []}
                summary = f"{r['sent']} reminder(s) sent"
                if overflow:
                    summary += f", {overflow} held for the next run (per-run cap)"
                    severity = "warning"
                if deferred:
                    summary += f", {deferred} deferred (daily cap)"
                    severity = "warning"
        else:  # replies
            from outreach.process_replies import main as scan_replies

            r = scan_replies([]) or {"errors": []}
            if isinstance(r, dict) and "classified" in r:
                summary = (f"Reply scan: {r['classified']} classified, {r['enqueued']} queued, "
                           f"{r['flagged']} flagged for manual, {r['failed']} gave up")
            else:
                summary = "Reply scan finished - check the Replies page"

        errs = r.get("errors") or []
        with _JOB_LOCK:
            _JOB["status"] = "failed" if errs else "success"
            _JOB["severity"] = "failed" if errs else severity
            _JOB["summary"] = summary + (f" ({len(errs)} error(s) - see the log)" if errs else "")
            _JOB["finished"] = datetime.now().strftime("%H:%M:%S")
    except Exception as e:  # noqa: BLE001
        with _JOB_LOCK:
            _JOB["status"] = "failed"
            _JOB["severity"] = "danger"
            _JOB["summary"] = f"{action}: {e}"
            _JOB["finished"] = datetime.now().strftime("%H:%M:%S")


def _relative_time(ts):
    """'2026-08-27 14:05:01' -> 'just now' / '5 min ago' / '3 h ago' / 'yesterday' / 'Aug 25'."""
    try:
        when = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return ""
    delta = datetime.now() - when
    secs = delta.total_seconds()
    if secs < 0:
        return "just now"
    if secs < 90:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)} min ago"
    if secs < 86400:
        return f"{int(secs // 3600)} h ago"
    if secs < 172800:
        return "yesterday"
    if secs < 604800:
        return f"{int(secs // 86400)} days ago"
    return when.strftime("%b %d")


def _activity_items(limit=12):
    """Human-readable feed built from the send history."""
    labels = {
        "cold": ("send", "Cold intro emailed to {who}"),
        "followup": ("nudge", "Follow-up nudge sent to {who}"),
        "reminder": ("clock", "Call reminder sent to {who}"),
        "reply": ("reply", "Reply handled — {subject}"),
    }
    out = []
    for e in recent_history(limit):
        kind = e.get("kind", "")
        icon, template = labels.get(kind, ("send", "{who}"))
        name = (e.get("name") or "").strip()
        company = (e.get("company") or "").strip()
        who = name or e.get("email") or "a lead"
        if company and kind != "reply":
            who = f"{who} — {company}"
        text = template.format(who=who, subject=(e.get("subject") or "no subject"))
        out.append({
            "icon": icon,
            "text": text,
            "ago": _relative_time(e.get("timestamp", "")),
            "day": (e.get("timestamp") or "")[:10],
        })
    return out


def create_app():
    app = Flask(
        __name__,
        template_folder=str(resource_path("outreach/web/templates")),
        static_folder=str(resource_path("outreach/web/static")),
    )
    # Local single-user tool: the key only needs to survive this process's lifetime,
    # it's not protecting anything beyond flash-message cookies. Fresh per process.
    app.secret_key = secrets.token_hex(32)

    @app.before_request
    def _block_cross_origin():
        """CSRF / DNS-rebind guard: any state-changing request must come from our
        own loopback dashboard. A cross-site page can issue the request but cannot
        set a matching Origin or forge the loopback Host, so it gets a 403."""
        if request.method in _SAFE_METHODS:
            return None
        if not _same_origin_ok():
            abort(403)
        return None

    @app.context_processor
    def inject_active():
        endpoint_to_active = {
            "dashboard": "dashboard",
            "leads": "leads",
            "send_page": "send",
            "replies_page": "replies",
            "history": "history",
            "blocklist_page": "blocklist",
            "diagnostics_page": "diagnostics",
            "settings": "settings",
            "logs_page": "logs",
            "find_leads": "find_leads",
            "find_leads_search": "find_leads",
        }
        active = endpoint_to_active.get(request.endpoint)
        try:
            cfg = load_config()
        except Exception:  # noqa: BLE001
            cfg = {}
        try:
            pending = len(reply_queue.pending())
        except Exception:  # noqa: BLE001
            pending = 0
        return {
            "active": active,
            "pending_replies": pending,
            "gmail_connected": bool((cfg.get("gmail_address") or "").strip()),
            "gmail_address": cfg.get("gmail_address") or "",
            "sender_company": cfg.get("sender_company") or "",
        }

    def get_config_and_store():
        cfg = load_config()
        store = ExcelStore(
            cfg["excel_path"],
            column_map=cfg.get("column_map"),
            disallowed_emails=cfg.get("disallowed_emails"),
            disallowed_domains=cfg.get("disallowed_domains"),
        )
        return cfg, store

    @app.errorhandler(ExcelFileLocked)
    def handle_locked(e):
        flash(str(e), "danger")
        return render_template("excel_locked.html"), 200

    @app.route("/")
    def dashboard():
        cfg, store = get_config_and_store()
        daily_cap = cfg_get(cfg, "daily_send_cap")
        setup_todo = []
        if not (cfg.get("sender_name") or "").strip() or not (cfg.get("sender_company") or "").strip():
            setup_todo.append("Add your name and company under Settings → Business details.")
        if not (cfg.get("gmail_address") or "").strip():
            setup_todo.append("Connect the sending Gmail account under Settings → Gmail account.")
        if store.email_column_missing:
            setup_todo.append(
                "Your leads file has no email column - pick one under Settings → Lead spreadsheet columns."
            )

        stats = {
            "total_leads": sum(1 for _ in store.all_rows()),
            "sent_today": sent_today(),
            "daily_cap": daily_cap,
            "remaining_today": remaining_today(daily_cap),
            "cold_pending": len(cold_candidates(store)),
            "reminders_due": len(reminder_candidates(store, cfg_get(cfg, "reminder_window_hours"))),
            "followups_due": len(followup_candidates(store, cfg)) if cfg_get(cfg, "followup_enabled") else 0,
            "blocklist_count": len(cfg.get("disallowed_domains", [])) + len(cfg.get("disallowed_emails", [])),
            "pending_replies": len(reply_queue.pending()),
        }
        return render_template(
            "dashboard.html", stats=stats, cfg=cfg, setup_todo=setup_todo,
            followup_enabled=cfg_get(cfg, "followup_enabled"),
        )

    @app.route("/leads")
    def leads():
        cfg, store = get_config_and_store()
        from outreach.lead_fields import lead_company, lead_name

        rows = []
        for row_idx, values, reason in store.all_rows():
            name, company = lead_name(values), lead_company(values)
            rows.append({
                "row_idx": row_idx,
                "v": values,
                "reason": reason,
                "display_name": name,
                "display_company": company,
                "name_derived": not str(values.get("Name") or "").strip() and name != "there",
                "company_derived": not str(values.get("Company") or "").strip() and company != "your company",
                "score": score_lead(values, cfg),
                "score_manual": priority_is_manual(values),
            })
        return render_template("leads.html", rows=rows, excel_path=cfg["excel_path"])

    @app.route("/leads/<int:row_idx>/suppress", methods=["POST"])
    def toggle_suppress(row_idx):
        _, store = get_config_and_store()
        current = store.get_row(row_idx).get("Suppressed")
        is_suppressed = str(current or "").strip().lower() in SUPPRESSED_TRUE_VALUES
        store.set_value(row_idx, "Suppressed", "" if is_suppressed else "yes")
        flash("Lead unsuppressed." if is_suppressed else "Lead suppressed.", "success")
        return redirect(url_for("leads"))

    @app.route("/send")
    def send_page():
        cfg, store = get_config_and_store()
        by_priority = priority_sort_key(cfg)
        return render_template(
            "send.html",
            cold=sorted(cold_candidates(store), key=by_priority),
            reminders=reminder_candidates(store, cfg_get(cfg, "reminder_window_hours")),
            followups=sorted(followup_candidates(store, cfg), key=by_priority),
            followup_enabled=cfg_get(cfg, "followup_enabled"),
            score_lead=lambda row: score_lead(row, cfg),
        )

    def _try_start_job(action):
        """Start the background runner unless one is already going.
        Returns (started: bool, job: dict)."""
        with _JOB_LOCK:
            if _JOB["status"] == "running":
                return False, dict(_JOB)
            _JOB.update(status="running", severity="running", action=action,
                        started=datetime.now().strftime("%H:%M:%S"),
                        finished=None, summary=None)
            job = dict(_JOB)
        threading.Thread(target=_run_job, args=(action,), daemon=True).start()
        return True, job

    def _sync_send_redirect(action):
        """Legacy /send/<action> endpoints: every real-email action is now async.
        Kick the same background job the dashboard uses and bounce back to Send."""
        started, _ = _try_start_job(action)
        if started:
            flash("Started in the background - watch the status panel on the Send page.", "success")
        else:
            flash("A job is already running - wait for it to finish, then try again.", "warning")
        return redirect(url_for("send_page"))

    @app.route("/send/cold", methods=["POST"])
    def send_cold_now():
        return _sync_send_redirect("cold")

    @app.route("/send/followups", methods=["POST"])
    def send_followups_now():
        return _sync_send_redirect("followups")

    @app.route("/send/reminders", methods=["POST"])
    def send_reminders_now():
        return _sync_send_redirect("reminders")

    # ---- Run now (background jobs) ---------------------------------------
    @app.route("/run/<action>", methods=["POST"])
    def run_action(action):
        if action not in _RUN_ACTIONS:
            return jsonify({"error": "unknown action"}), 404
        started, job = _try_start_job(action)
        if not started:
            return jsonify({"error": "a job is already running", "job": job}), 409
        return jsonify({"job": job})

    @app.route("/run/status")
    def run_status():
        with _JOB_LOCK:
            return jsonify(dict(_JOB))

    @app.route("/logs/tail")
    def logs_tail():
        try:
            lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
            return ("\n".join(lines[-200:]) or "(log is empty)"), 200, {"Content-Type": "text/plain; charset=utf-8"}
        except FileNotFoundError:
            return "(no log yet)", 200, {"Content-Type": "text/plain; charset=utf-8"}
        except OSError as e:
            return f"(log unavailable: {e})", 200, {"Content-Type": "text/plain; charset=utf-8"}

    @app.route("/activity")
    def activity():
        return jsonify(_activity_items())

    @app.route("/logs")
    def logs_page():
        return render_template("logs.html", items=_activity_items(limit=200))

    @app.route("/replies")
    def replies_page():
        return render_template("replies.html", items=reply_queue.pending())

    @app.route("/replies/<qid>/approve", methods=["POST"])
    def reply_approve(qid):
        item = reply_queue.get(qid)
        if not item or item.get("status") != "pending":
            flash("That reply action is no longer pending.", "warning")
            return redirect(url_for("replies_page"))
        try:
            result = reply_queue.approve(qid)
        except Exception as e:
            flash(f"Couldn't complete that action: {e}", "danger")
            return redirect(url_for("replies_page"))
        category = {"done": "success", "deferred": "warning"}.get(result.get("status"), "danger")
        flash(result.get("message", "Done."), category)
        return redirect(url_for("replies_page"))

    @app.route("/replies/<qid>/reject", methods=["POST"])
    def reply_reject(qid):
        reply_queue.reject(qid)
        flash("Reply action discarded.", "success")
        return redirect(url_for("replies_page"))

    @app.route("/history")
    def history():
        return render_template("history.html", entries=recent_history(200))

    @app.route("/diagnostics")
    def diagnostics_page():
        # The page shell renders instantly; the checks (live network round-trips)
        # are fetched from /diagnostics/run and filled in client-side.
        return render_template("diagnostics.html", check_names=CHECK_NAMES)

    @app.route("/diagnostics/run")
    def diagnostics_run():
        # Billable (Anthropic) + Google round-trips. Harmless to leave as GET for
        # the dashboard's own fetch, but reject an obvious cross-site <img>/fetch
        # that carries a foreign Referer.
        referer = request.headers.get("Referer")
        if referer and _host_only(referer.split("://", 1)[-1].split("/", 1)[0]) not in _ALLOWED_HOSTS:
            abort(403)
        return jsonify(run_checks(load_config()))

    @app.route("/blocklist")
    def blocklist_page():
        cfg = load_config()
        return render_template(
            "blocklist.html",
            domains=cfg.get("disallowed_domains", []),
            emails=cfg.get("disallowed_emails", []),
        )

    @app.route("/blocklist/domain", methods=["POST"])
    def add_domain():
        domain = request.form.get("domain", "").strip().lower()
        if domain:
            cfg = load_config()
            cfg.setdefault("disallowed_domains", [])
            if domain not in cfg["disallowed_domains"]:
                cfg["disallowed_domains"].append(domain)
                save_config(cfg)
                flash(f"Blocked domain: {domain}", "success")
        return redirect(url_for("blocklist_page"))

    @app.route("/blocklist/domain/<path:domain>/remove", methods=["POST"])
    def remove_domain(domain):
        cfg = load_config()
        if domain in cfg.get("disallowed_domains", []):
            cfg["disallowed_domains"].remove(domain)
            save_config(cfg)
            flash(f"Unblocked domain: {domain}", "success")
        return redirect(url_for("blocklist_page"))

    @app.route("/blocklist/email", methods=["POST"])
    def add_email():
        email = request.form.get("email", "").strip().lower()
        if email:
            cfg = load_config()
            cfg.setdefault("disallowed_emails", [])
            if email not in cfg["disallowed_emails"]:
                cfg["disallowed_emails"].append(email)
                save_config(cfg)
                flash(f"Blocked email: {email}", "success")
        return redirect(url_for("blocklist_page"))

    @app.route("/blocklist/email/<path:email>/remove", methods=["POST"])
    def remove_email(email):
        cfg = load_config()
        if email in cfg.get("disallowed_emails", []):
            cfg["disallowed_emails"].remove(email)
            save_config(cfg)
            flash(f"Unblocked email: {email}", "success")
        return redirect(url_for("blocklist_page"))

    @app.route("/settings", methods=["GET", "POST"])
    def settings():
        cfg = load_config()
        if request.method == "POST":
            for field in (
                "sender_name", "sender_company", "sender_phone", "sender_address", "sender_pitch",
                "cold_subject_template", "cold_body_template",
                "followup_subject_template", "followup_body_template",
                "followup_breakup_body_template",
                "reminder_subject_template", "reminder_body_template",
                "meeting_confirm_subject_template", "meeting_confirm_body_template",
                "propose_times_subject_template", "propose_times_body_template",
                "decline_ack_subject_template", "decline_ack_body_template",
            ):
                if field in request.form:
                    cfg[field] = request.form.get(field, cfg.get(field))
            for key in (
                "reminder_interval_hours",
                "reminder_window_hours",
                "max_reminders_per_run",
                "max_followups_per_run",
                "daily_send_cap",
                "meeting_duration_minutes",
                "scheduling_window_days",
                "min_notice_hours",
            ):
                raw = request.form.get(key)
                if raw:
                    try:
                        cfg[key] = int(raw)
                    except ValueError:
                        flash(f"Ignored invalid value for {key}.", "warning")

            if "followup_settings" in request.form:
                cfg["followup_enabled"] = request.form.get("followup_enabled") == "on"
                raw_offsets = request.form.get("followup_offsets_days", "")
                offsets = []
                for part in raw_offsets.replace(";", ",").split(","):
                    part = part.strip()
                    if not part:
                        continue
                    try:
                        n = int(float(part))
                    except ValueError:
                        flash(f"Ignored non-number in the follow-up cadence: '{part}'.", "warning")
                        continue
                    if n >= 1:
                        offsets.append(n)
                    else:
                        flash("Follow-up cadence must be whole days of 1 or more.", "warning")
                if offsets:
                    cfg["followup_offsets_days"] = sorted(offsets)

            if "timezone" in request.form:
                tz_raw = (request.form.get("timezone") or "").strip()
                if not tz_raw:
                    cfg["timezone"] = ""
                elif _is_valid_timezone(tz_raw):
                    cfg["timezone"] = tz_raw
                else:
                    flash(f"'{tz_raw}' is not a valid IANA time zone name - kept the previous value.",
                          "warning")

            lang = request.form.get("template_language")
            if lang in ("en", "ro"):
                cfg["template_language"] = lang

            if "scoring_keywords" in request.form:
                kws = [k.strip() for k in request.form["scoring_keywords"].split(",") if k.strip()]
                cfg["scoring_keywords"] = kws

            if any(f"col_{f}" in request.form for f in ("Name", "Company", "Email", "Phone", "Priority")):
                column_map = {}
                for logical in ("Name", "Company", "Email", "Phone", "Priority"):
                    choice = (request.form.get(f"col_{logical}") or "").strip()
                    # "" = auto-detect, "__none__" = the sheet doesn't have this field
                    if choice and choice != "__none__":
                        column_map[logical] = choice
                cfg["column_map"] = column_map

            new_key = (request.form.get("anthropic_api_key") or "").strip()
            if new_key:
                set_anthropic_key(new_key)
                flash("Anthropic API key saved.", "success")
            save_config(cfg)
            flash("Settings saved.", "success")
            return redirect(url_for("settings"))

        headers = sheet_headers(cfg["excel_path"])
        detected = detect_columns(headers)
        column_view = []
        for logical in ("Name", "Company", "Email", "Phone", "Priority"):
            configured = cfg.get("column_map", {}).get(logical)
            auto = detected.get(logical)
            column_view.append({
                "logical": logical,
                "configured": configured,
                "auto": auto,
                "effective": configured if configured is not None else auto,
            })
        return render_template(
            "settings.html",
            cfg=cfg,
            task=task_status(),
            reply_task=task_status(REPLY_TASK_NAME),
            anthropic_key_set=bool(get_anthropic_key()),
            reply_scan_enabled=cfg_get(cfg, "reply_scan_enabled"),
            followup_enabled=cfg_get(cfg, "followup_enabled"),
            sheet_headers=headers,
            column_view=column_view,
        )

    @app.route("/settings/browse-excel", methods=["POST"])
    def browse_excel():
        try:
            import tkinter
            from tkinter import filedialog

            root = tkinter.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            path = filedialog.askopenfilename(
                title="Select clients.xlsx",
                filetypes=[("Excel files", "*.xlsx")],
            )
            root.destroy()
        except Exception as e:
            flash(f"Couldn't open the file browser: {e}", "danger")
            return redirect(url_for("settings"))

        if path:
            cfg = load_config()
            cfg["excel_path"] = path
            save_config(cfg)
            flash(f"Excel file set to: {path}", "success")
        return redirect(url_for("settings"))

    @app.route("/settings/connect-gmail", methods=["POST"])
    def connect_gmail():
        # Blocks this one request while the real Google sign-in/consent screen is completed
        # in the browser - same accepted pattern as the tkinter file-picker route above.
        try:
            gmail_address = run_oauth_flow()
        except FileNotFoundError as e:
            flash(str(e), "danger")
            return redirect(url_for("settings"))
        except Exception as e:
            flash(f"Google sign-in didn't complete: {e}", "danger")
            return redirect(url_for("settings"))

        cfg = load_config()
        cfg["gmail_address"] = gmail_address
        save_config(cfg)
        flash(f"Connected Gmail account: {gmail_address}", "success")
        return redirect(url_for("settings"))

    @app.route("/settings/automation/enable", methods=["POST"])
    def automation_enable():
        cfg = load_config()
        ok, message = register_task(cfg_get(cfg, "reminder_interval_hours"))
        flash(message if message else ("Automatic reminders enabled." if ok else "Failed to enable."), "success" if ok else "danger")
        return redirect(url_for("settings"))

    @app.route("/settings/automation/disable", methods=["POST"])
    def automation_disable():
        ok, message = unregister_task()
        flash(message if message else ("Automatic reminders disabled." if ok else "Failed to disable."), "success" if ok else "danger")
        return redirect(url_for("settings"))

    @app.route("/settings/replies/enable", methods=["POST"])
    def replies_enable():
        cfg = load_config()
        if not get_anthropic_key():
            flash("Add an Anthropic API key first - reply reading needs it.", "warning")
            return redirect(url_for("settings"))
        interval = cfg_get(cfg, "reminder_interval_hours")
        ok, message = register_task(interval, REPLY_TASK_NAME, "--replies")
        if ok:
            cfg["reply_scan_enabled"] = True
            save_config(cfg)
        flash(
            message or ("Automatic reply checking enabled." if ok else "Failed to enable."),
            "success" if ok else "danger",
        )
        return redirect(url_for("settings"))

    @app.route("/settings/replies/disable", methods=["POST"])
    def replies_disable():
        cfg = load_config()
        ok, message = unregister_task(REPLY_TASK_NAME)
        cfg["reply_scan_enabled"] = False
        save_config(cfg)
        flash(
            message or ("Automatic reply checking disabled." if ok else "Failed to disable."),
            "success" if ok else "danger",
        )
        return redirect(url_for("settings"))

    @app.route("/settings/templates/reset", methods=["POST"])
    def reset_templates():
        cfg = load_config()
        lang = cfg_get(cfg, "template_language")
        cfg.update(templates.defaults(lang))
        save_config(cfg)
        flash(f"All templates reset to the {'Romanian' if lang == 'ro' else 'English'} defaults.", "success")
        return redirect(url_for("settings"))

    # ---- Find leads (BETA) ---------------------------------------------
    @app.route("/find-leads")
    def find_leads():
        return render_template("find_leads.html", results=None,
                               what=_LEADS_LAST["what"], where=_LEADS_LAST["where"],
                               scrape=_LEADS_LAST["scrape"])

    @app.route("/find-leads/search", methods=["POST"])
    def find_leads_search():
        cfg, store = get_config_and_store()
        what = (request.form.get("what") or "").strip()
        where = (request.form.get("where") or "").strip()
        scrape = request.form.get("scrape") == "on"
        if not what or not where:
            flash("Enter both a business type and a city / region.", "warning")
            return redirect(url_for("find_leads"))

        try:
            leads = lead_sourcing.search_businesses(what, where)
            lead_sourcing.enrich(leads, do_scrape=scrape)
        except Exception as e:  # noqa: BLE001 - sourcing is best-effort
            flash(f"Search failed: {e}", "danger")
            return redirect(url_for("find_leads"))

        _LEADS_LAST.update(what=what, where=where, scrape=scrape, leads=leads)
        existing = store.existing_emails()
        results = [
            {"lead": lead,
             "duplicate": bool(lead.get("Email")) and lead["Email"].lower() in existing}
            for lead in leads
        ]
        if not leads:
            flash("No businesses found. Try a broader type or a larger region.", "warning")
        return render_template("find_leads.html", results=results,
                               what=what, where=where, scrape=scrape)

    @app.route("/find-leads/import", methods=["POST"])
    def find_leads_import():
        _, store = get_config_and_store()
        picks = request.form.getlist("pick")
        leads = _LEADS_LAST["leads"]
        added = skipped = 0
        for raw in picks:
            try:
                lead = leads[int(raw)]
            except (ValueError, IndexError):
                continue
            if store.add_lead(lead) is not None:
                added += 1
            else:
                skipped += 1
        flash(f"Added {added} lead(s), skipped {skipped} (duplicates / no email).",
              "success" if added else "warning")
        return redirect(url_for("leads"))

    return app


def _pick_port(preferred=5000):
    """Use 5000 if free, otherwise let the OS hand us any open port."""
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    return preferred


def main():
    app = create_app()
    port = _pick_port()
    url = f"http://127.0.0.1:{port}"
    print(f"Freight Outreach dashboard running at {url}  (close this window to stop)")
    webbrowser.open(url)
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
