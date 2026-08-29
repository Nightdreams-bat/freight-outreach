"""Single entry point for both the source checkout (`python -m kairo`) and the
frozen build.

  * No args (a double-click) -> open the dashboard in a native app window.
    Everything is configured on the dashboard's Settings page; there is no wizard.
  * Explicit flags:
        --web         open the dashboard in the default browser instead of a window
        --cold        send the cold-intro batch now (headless)
        --followup    send due follow-up nudges now (headless; opt-in via config)
        --reminders   run the reminder + follow-up scan now (headless; scheduled task)
        --replies     scan for lead replies and draft actions (headless; scheduled task)
        --selfcheck   verify a freshly built .exe has everything it needs
"""

import os
import sys

FROZEN = getattr(sys, "frozen", False)


def _ensure_std_streams():
    """A windowed (console=False) frozen build has sys.stdout/stderr set to None;
    any stray print() - Flask's startup banner, a library warning - then raises
    'lost sys.stdout'. Point them at the null device so the GUI never crashes on
    output. The console build (kairo-cli.exe) has real streams and is untouched."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            try:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8", errors="replace"))
            except OSError:
                pass


def _pause_if_frozen():
    """Keep a double-clicked console window open so the user can read the output."""
    if FROZEN:
        try:
            input("\nPress Enter to close this window.")
        except EOFError:
            pass


def main(argv=None):
    _ensure_std_streams()
    argv = list(sys.argv[1:] if argv is None else argv)

    # Downstream mains parse their own args with argparse; hide our dispatch flags from them.
    dispatch_flags = {"--web", "--cold", "--followup", "--reminders", "--replies", "--selfcheck"}
    sys.argv = [sys.argv[0]] + [a for a in argv if a not in dispatch_flags]

    if "--selfcheck" in argv:
        _selfcheck()
        return
    elif "--web" in argv:
        from kairo.web.app import main as run
        run()
        return
    elif "--cold" in argv:
        from kairo.send_cold import main as run
        run()
        _pause_if_frozen()
        return
    elif "--followup" in argv:
        from kairo.send_followups import main as run
        run()
        _pause_if_frozen()
        return
    elif "--reminders" in argv:
        # The hourly scheduled task runs both scans - reminders first, then any
        # due follow-up nudges (which self-gate on followup_enabled).
        from kairo.send_reminders import main as run_reminders
        from kairo.send_followups import main as run_followups
        run_reminders()
        run_followups()
        return  # scheduled task: no one is watching, don't pause
    elif "--replies" in argv:
        from kairo.process_replies import main as run
        run()
        return  # scheduled task: no one is watching, don't pause
    else:
        from kairo.desktop import run_desktop
        run_desktop()


def _selfcheck():
    """Verifies the frozen build has everything it needs. Run once after building."""
    ok = True

    import keyring
    backend = keyring.get_keyring()
    print(f"keyring backend: {backend.__class__.__module__}.{backend.__class__.__name__}")
    try:
        keyring.set_password("kairo-selfcheck", "probe", "value")
        assert keyring.get_password("kairo-selfcheck", "probe") == "value"
        keyring.delete_password("kairo-selfcheck", "probe")
        print("  credential store read/write: OK")
    except Exception as e:
        ok = False
        print(f"  credential store FAILED: {e}")

    for mod in ("openpyxl", "jinja2", "flask", "googleapiclient.discovery",
                "google_auth_oauthlib.flow", "google.oauth2.credentials"):
        try:
            __import__(mod)
            print(f"import {mod}: OK")
        except Exception as e:
            ok = False
            print(f"import {mod}: FAILED - {e}")

    # Reply-handling is optional - a missing anthropic package or unset key is a
    # warning, not a self-check failure.
    try:
        __import__("anthropic")
        print("import anthropic: OK")
    except Exception as e:
        print(f"import anthropic: MISSING (reply classification disabled) - {e}")

    # The native window is optional too - a missing/broken pywebview falls back
    # to a chromeless browser window, so it's info, not a failure.
    try:
        __import__("webview")
        print("import webview (native window): OK")
    except Exception as e:
        print(f"import webview: MISSING (will use a browser window instead) - {e}")

    try:
        from kairo.config import get as cfg_get
        from kairo.config import load_config
        from kairo.credentials import get_anthropic_key
        print(f"  Anthropic API key: {'set' if get_anthropic_key() else 'not set'}")
        cfg = load_config()  # creates config.json on a fresh install
        print(f"  reply_scan_enabled: {cfg_get(cfg, 'reply_scan_enabled')}")
    except Exception as e:
        print(f"  reply-handling config check skipped - {e}")

    from kairo.paths import resource_path
    for res in ("kairo/web/templates/base.html", "kairo/web/static/style.css"):
        exists = resource_path(res).exists()
        ok = ok and exists
        print(f"resource {res}: {'OK' if exists else 'MISSING'}")

    try:
        from kairo import templates as _t
        from kairo.templates import render as _render
        _dummy = dict(name="A", company="B", sender_name="C", sender_company="D",
                      sender_phone="", sender_address="", unsubscribe_line="Reply STOP.",
                      meeting_time="Mon", slots=["Mon 9am", "Tue 2pm"],
                      stage=1, is_last=False, phone="", sender_pitch="")
        for tname in ("MEETING_CONFIRM_BODY", "PROPOSE_TIMES_BODY", "DECLINE_ACK_BODY",
                      "FOLLOWUP_BODY", "FOLLOWUP_BREAKUP_BODY"):
            _render(getattr(_t, tname), **_dummy)
        print("scheduling + follow-up templates render: OK")
    except Exception as e:
        ok = False
        print(f"scheduling + follow-up templates render: FAILED - {e}")

    try:
        from kairo.config import load_config
        from kairo.diagnostics import run_checks
        print("\nConnection checks:")
        for c in run_checks(load_config()):
            print(f"  [{c['status'].upper():>4}] {c['name']} - {c['detail']}")
    except Exception as e:
        print(f"  connection checks skipped - {e}")

    print("\nSELF-CHECK", "PASSED" if ok else "FAILED")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
