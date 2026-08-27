"""Single entry point for both the source checkout (`python -m outreach`) and the
frozen build (`FreightOutreach.exe`).

    (no args)     open the dashboard in the browser  <- what a double-click does
    --setup       run the first-time setup wizard
    --cold        send the cold-intro batch now (headless, for a shortcut/task)
    --reminders   run the reminder scan now (headless, used by the scheduled task)
"""

import sys


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    # Downstream mains parse their own args with argparse; hide the dispatch flag from them.
    dispatch_flags = {"--setup", "--cold", "--reminders", "--selfcheck"}
    sys.argv = [sys.argv[0]] + [a for a in argv if a not in dispatch_flags]

    if "--selfcheck" in argv:
        _selfcheck()
        return
    elif "--setup" in argv:
        from outreach.setup import main as run
    elif "--cold" in argv:
        from outreach.send_cold import main as run
    elif "--reminders" in argv:
        from outreach.send_reminders import main as run
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
