import socket
import webbrowser

from flask import Flask, flash, redirect, render_template, request, url_for

from outreach import reply_queue
from outreach.config import get as cfg_get
from outreach.config import load_config, save_config
from outreach.credentials import get_anthropic_key, set_anthropic_key
from outreach.paths import resource_path
from outreach.core import (
    apply_daily_cap,
    build_mailer,
    cold_candidates,
    reminder_candidates,
    send_cold_batch,
    send_reminder_batch,
)
from outreach.excel_store import ExcelFileLocked, ExcelStore, sheet_headers
from outreach.column_map import detect as detect_columns
from outreach.gmail_oauth import run_oauth_flow
from outreach.schedule_task import (
    REPLY_TASK_NAME,
    register_task,
    task_status,
    unregister_task,
)
from outreach.send_tracker import recent_history, remaining_today, sent_today

SUPPRESSED_TRUE_VALUES = ("1", "true", "yes", "y")


def create_app():
    app = Flask(
        __name__,
        template_folder=str(resource_path("outreach/web/templates")),
        static_folder=str(resource_path("outreach/web/static")),
    )
    # Local single-user tool: the key only needs to survive this process's lifetime,
    # it's not protecting anything beyond flash-message cookies.
    app.secret_key = "freight-outreach-local-dashboard"

    @app.context_processor
    def inject_active():
        endpoint_to_active = {
            "dashboard": "dashboard",
            "leads": "leads",
            "send_page": "send",
            "replies_page": "replies",
            "history": "history",
            "blocklist_page": "blocklist",
            "settings": "settings",
        }
        active = endpoint_to_active.get(request.endpoint)
        # The nav badge needs the count on every page, cheap to read.
        try:
            pending_replies = len(reply_queue.pending())
        except Exception:
            pending_replies = 0
        return {"active": active, "pending_replies": pending_replies}

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
        daily_cap = cfg.get("daily_send_cap", 150)
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
            "reminders_due": len(reminder_candidates(store, cfg.get("reminder_window_hours", 2))),
            "blocklist_count": len(cfg.get("disallowed_domains", [])) + len(cfg.get("disallowed_emails", [])),
            "pending_replies": len(reply_queue.pending()),
        }
        return render_template("dashboard.html", stats=stats, cfg=cfg, setup_todo=setup_todo)

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
        return render_template(
            "send.html",
            cold=cold_candidates(store),
            reminders=reminder_candidates(store, cfg.get("reminder_window_hours", 2)),
        )

    @app.route("/send/cold", methods=["POST"])
    def send_cold_now():
        cfg, store = get_config_and_store()
        candidates, _, deferred = apply_daily_cap(
            cold_candidates(store), cfg.get("daily_send_cap", 150)
        )
        if not candidates:
            flash("Nothing to send - empty queue or today's send cap already reached.", "warning")
            return redirect(url_for("send_page"))

        mailer = build_mailer(cfg)
        result = send_cold_batch(cfg, store, mailer, candidates, dry_run=False)

        msg = f"Sent {result['sent']} cold intro email(s)."
        if deferred:
            msg += f" {deferred} deferred to the next run (daily cap)."
        if result["errors"]:
            msg += f" {len(result['errors'])} error(s) - check outreach.log."
        flash(msg, "warning" if result["errors"] else "success")
        return redirect(url_for("send_page"))

    @app.route("/send/reminders", methods=["POST"])
    def send_reminders_now():
        cfg, store = get_config_and_store()
        candidates = reminder_candidates(store, cfg.get("reminder_window_hours", 2))
        max_per_run = cfg.get("max_reminders_per_run", 25)
        if len(candidates) > max_per_run:
            flash(
                f"{len(candidates)} reminders matched, over the safety cap of {max_per_run}. "
                f"Sent none - check clients.xlsx for a data problem.",
                "danger",
            )
            return redirect(url_for("send_page"))

        candidates, _, deferred = apply_daily_cap(
            candidates, cfg.get("daily_send_cap", 150), sort_key=lambda c: c[2]
        )
        if not candidates:
            flash("Nothing to send - empty queue or today's send cap already reached.", "warning")
            return redirect(url_for("send_page"))

        mailer = build_mailer(cfg)
        result = send_reminder_batch(cfg, store, mailer, candidates, dry_run=False)

        msg = f"Sent {result['sent']} reminder(s)."
        if deferred:
            msg += f" {deferred} could NOT be sent (daily cap) - raise daily_send_cap if this matters."
        flash(msg, "warning" if (result["errors"] or deferred) else "success")
        return redirect(url_for("send_page"))

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
                "sender_name", "sender_company", "sender_phone", "sender_pitch",
                "cold_subject_template", "cold_body_template",
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
            if any(f"col_{f}" in request.form for f in ("Name", "Company", "Email", "Phone")):
                column_map = {}
                for logical in ("Name", "Company", "Email", "Phone"):
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
        for logical in ("Name", "Company", "Email", "Phone"):
            configured = cfg.get("column_map", {}).get(logical)
            auto = detected.get(logical)
            column_view.append({
                "logical": logical,
                "configured": configured,
                "auto": auto,
                # what's actually in force right now
                "effective": configured if configured is not None else auto,
            })
        return render_template(
            "settings.html",
            cfg=cfg,
            task=task_status(),
            reply_task=task_status(REPLY_TASK_NAME),
            anthropic_key_set=bool(get_anthropic_key()),
            reply_scan_enabled=cfg_get(cfg, "reply_scan_enabled"),
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
        ok, message = register_task(cfg.get("reminder_interval_hours", 2))
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
        interval = cfg.get("reminder_interval_hours", 2)
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
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
