"""Run the dashboard as a native desktop window.

This is what a plain double-click / `python -m outreach` does. Flask runs on a
localhost port in a background thread; a native window (pywebview, using the
WebView2 runtime that ships with Windows 11 - no bundled browser) shows it.

Closing the window ends the process - the Flask thread is a daemon.

If pywebview can't load for any reason, we fall back to a chromeless
Edge/Chrome "--app" window, and finally to a normal browser tab.
"""

import ctypes
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

from outreach.logging_setup import get_logger
from outreach.paths import data_dir

log = get_logger("desktop")

WINDOW_TITLE = "Freight Outreach"
WIN_W, WIN_H = 1280, 860
MIN_W, MIN_H = 960, 640
FROZEN = getattr(sys, "frozen", False)


def _start_server():
    """Start Flask in a daemon thread; return (thread, url)."""
    from outreach.web.app import _pick_port, create_app

    app = create_app()
    port = _pick_port()
    url = f"http://127.0.0.1:{port}"

    def _serve():
        app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)

    thread = threading.Thread(target=_serve, daemon=True, name="flask")
    thread.start()
    return thread, url


def _wait_until_up(url, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)  # noqa: S310 - localhost only
            return True
        except Exception:  # noqa: BLE001
            time.sleep(0.15)
    return False


def _hide_console():
    """Hide the black console window in GUI mode. CLI invocations keep theirs."""
    if os.name != "nt" or not FROZEN:
        return
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:  # noqa: BLE001
        pass


def _find_browser():
    for name in ("msedge", "chrome"):
        path = shutil.which(name)
        if path:
            return path
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    return next((p for p in candidates if os.path.exists(p)), None)


def _open_app_mode(url):
    """Chromeless browser window - the pywebview fallback."""
    browser = _find_browser()
    if not browser:
        return False
    profile = str(data_dir() / "webview-profile")
    try:
        subprocess.Popen([  # noqa: S603
            browser,
            f"--app={url}",
            f"--window-size={WIN_W},{WIN_H}",
            f"--user-data-dir={profile}",
        ])
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("app-mode launch failed: %s", e)
        return False


def _maybe_create_shortcuts():
    if not FROZEN:
        return
    marker = data_dir() / ".shortcuts_created"
    if marker.exists():
        return
    try:
        from outreach.shortcut import create_shortcuts

        create_shortcuts(sys.executable)
        marker.write_text("1", encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log.info("shortcut creation skipped: %s", e)


def run_desktop():
    thread, url = _start_server()
    # Hide the console straight away - the server thread is up, and waiting on the
    # HTTP poll below can take several seconds on a cold start (black window flash).
    _hide_console()
    if not _wait_until_up(url):
        log.error("Dashboard server didn't come up in time.")
    _maybe_create_shortcuts()

    if _try_native_window(url):
        return  # window opened and was then closed -> exit; daemon thread dies with us

    # Native window unavailable (no WebView2, headless session, ...) - fall back.
    log.warning("Native window unavailable - opening a browser window instead.")
    _show_console()
    if not _open_app_mode(url):
        webbrowser.open(url)
    print(f"Freight Outreach is running at {url}  -  close this window to stop it.")
    try:
        thread.join()
    except KeyboardInterrupt:
        pass


def _try_native_window(url):
    """Open the pywebview window. Returns True only if it actually rendered."""
    try:
        import webview
    except Exception as e:  # noqa: BLE001
        log.info("pywebview not available: %s", e)
        return False

    loaded = {"ok": False}
    try:
        window = webview.create_window(
            WINDOW_TITLE, url,
            width=WIN_W, height=WIN_H,
            min_size=(MIN_W, MIN_H),
        )
        try:
            window.events.loaded += lambda: loaded.__setitem__("ok", True)
        except Exception:  # noqa: BLE001 - older pywebview: skip the probe
            loaded["ok"] = True
        t0 = time.time()
        webview.start()  # blocks until the window is closed
    except Exception as e:  # noqa: BLE001
        log.info("pywebview failed to start: %s", e)
        return False
    # If start() blocked for a while the user had a real window and closed it -
    # don't pop a browser window behind them. Only fall back when start()
    # returned almost immediately (the window never actually opened).
    if time.time() - t0 > 5:
        return True
    return loaded["ok"]


def _show_console():
    if os.name != "nt" or not FROZEN:
        return
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 5)  # SW_SHOW
    except Exception:  # noqa: BLE001
        pass
