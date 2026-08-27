"""Single entry point for both the source checkout (`python -m outreach`) and the
frozen build.

What decides the mode:
  * If the running .exe is named Setup.exe  -> the first-time setup wizard.
  * Otherwise, no args                      -> open the dashboard in the browser
                                               (this is what a double-click does).
  * Explicit flags override both:
        --setup       first-time setup wizard
        --cold        send the cold-intro batch now (headless)
        --reminders   run the reminder scan now (headless; used by the scheduled task)
        --selfcheck   verify a freshly built .exe has everything it needs
"""

import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)


def _mode_from_exe_name():
    """Setup.exe -> 'setup'. Any other frozen exe name -> None (fall through to args)."""
    if not FROZEN:
        return None
    if Path(sys.executable).stem.strip().lower() == "setup":
        return "setup"
    return None


def _pause_if_frozen():
    """Keep a double-clicked console window open so the user can read the output."""
    if FROZEN:
        try:
            input("\nPress Enter to close this window.")
        except EOFError:
            pass


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    # Downstream mains parse their own args with argparse; hide our dispatch flags from them.
    dispatch_flags = {"--setup", "--cold", "--reminders", "--selfcheck"}
    sys.argv = [sys.argv[0]] + [a for a in argv if a not in dispatch_flags]

    mode = _mode_from_exe_name()
    if "--selfcheck" in argv:
        _selfcheck()
        return
    elif "--setup" in argv or mode == "setup":
        from outreach.setup import main as run
        run()
        _pause_if_frozen()
        return
    elif "--cold" in argv:
        from outreach.send_cold import main as run
        run()
        _pause_if_frozen()
        return
    elif "--reminders" in argv:
        from outreach.send_reminders import main as run
        run()
        return  # scheduled task: no one is watching, don't pause
    else:
        from outreach.web.app import main as run
        run()


def _selfcheck():
    """Verifies the frozen build has everything it needs. Run once after building."""
    ok = True

    import keyring
    backend = keyring.get_keyring()
    print(f"keyring backend: {backend.__class__.__module__}.{backend.__class__.__name__}")
    try:
        keyring.set_password("freight-outreach-selfcheck", "probe", "value")
        assert keyring.get_password("freight-outreach-selfcheck", "probe") == "value"
        keyring.delete_password("freight-outreach-selfcheck", "probe")
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

    from outreach.paths import resource_path
    for res in ("outreach/web/templates/base.html", "outreach/web/static/style.css"):
        exists = resource_path(res).exists()
        ok = ok and exists
        print(f"resource {res}: {'OK' if exists else 'MISSING'}")

    print("\nSELF-CHECK", "PASSED" if ok else "FAILED")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
