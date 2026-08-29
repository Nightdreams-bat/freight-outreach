"""Desktop shell: native window, fallbacks, shortcuts, and the --web route."""

import sys
import types

import pytest

from kairo import desktop


@pytest.fixture(autouse=True)
def _no_server(monkeypatch):
    """Never start a real Flask server or hide a real console during tests."""
    fake_thread = types.SimpleNamespace(join=lambda: None)
    monkeypatch.setattr(desktop, "_start_server", lambda: (fake_thread, "http://127.0.0.1:5999"))
    monkeypatch.setattr(desktop, "_wait_until_up", lambda url, timeout=10.0: True)
    monkeypatch.setattr(desktop, "_hide_console", lambda: None)
    monkeypatch.setattr(desktop, "_maybe_create_shortcuts", lambda: None)


class _Events:
    def __init__(self):
        self.loaded = _Signal()


class _Signal:
    def __init__(self):
        self._handlers = []

    def __iadd__(self, fn):
        self._handlers.append(fn)
        return self

    def fire(self):
        for fn in self._handlers:
            fn()


class _Window:
    def __init__(self):
        self.events = _Events()


def _fake_webview(record):
    mod = types.ModuleType("webview")
    win = _Window()

    def create_window(*a, **k):
        record["create"] = (a, k)
        return win

    def start(*a, **k):
        record["start"] = True
        win.events.loaded.fire()  # a real window fires 'loaded'

    mod.create_window = create_window
    mod.start = start
    return mod


def test_native_window_is_used_when_webview_imports(monkeypatch):
    record = {}
    monkeypatch.setitem(sys.modules, "webview", _fake_webview(record))
    desktop.run_desktop()
    (title, url), kw = record["create"]
    assert title == desktop.WINDOW_TITLE
    assert url.startswith("http://127.0.0.1:")
    assert kw["width"] == desktop.WIN_W and kw["min_size"] == (desktop.MIN_W, desktop.MIN_H)
    assert record["start"] is True


def test_falls_back_to_app_mode_when_webview_missing(monkeypatch):
    # simulate: `import webview` raises
    bad = types.ModuleType("webview")
    def _boom(*a, **k):
        raise RuntimeError("no WebView2")
    bad.create_window = _boom
    monkeypatch.setitem(sys.modules, "webview", bad)
    calls = {}
    monkeypatch.setattr(desktop, "_open_app_mode", lambda url: calls.setdefault("app_mode", url) or True)
    monkeypatch.setattr(desktop.webbrowser, "open", lambda url: calls.setdefault("browser", url))
    desktop.run_desktop()
    assert "app_mode" in calls
    assert "browser" not in calls  # app-mode succeeded, no need for the last resort


def test_falls_back_to_browser_when_app_mode_also_fails(monkeypatch):
    bad = types.ModuleType("webview")
    monkeypatch.setitem(sys.modules, "webview", bad)  # no create_window attr -> AttributeError
    calls = {}
    monkeypatch.setattr(desktop, "_open_app_mode", lambda url: False)
    monkeypatch.setattr(desktop.webbrowser, "open", lambda url: calls.setdefault("browser", url))
    desktop.run_desktop()
    assert calls["browser"].startswith("http://127.0.0.1:")


def test_open_app_mode_launches_a_browser(monkeypatch, tmp_path):
    monkeypatch.setattr(desktop, "_find_browser", lambda: str(tmp_path / "msedge.exe"))
    monkeypatch.setattr(desktop, "data_dir", lambda: tmp_path)
    seen = {}
    monkeypatch.setattr(
        desktop.win_subprocess.subprocess, "Popen",
        lambda argv, *a, **k: seen.setdefault("argv", argv),
    )
    assert desktop._open_app_mode("http://127.0.0.1:5000") is True
    assert any(a.startswith("--app=") for a in seen["argv"])


def test_open_app_mode_returns_false_with_no_browser(monkeypatch):
    monkeypatch.setattr(desktop, "_find_browser", lambda: None)
    assert desktop._open_app_mode("http://x") is False


def test_create_shortcuts_swallows_a_broken_host(monkeypatch):
    from kairo import shortcut

    monkeypatch.setattr(shortcut, "_shell", lambda: (_ for _ in ()).throw(RuntimeError("no COM")))
    assert shortcut.create_shortcuts(r"C:\x\Kairo.exe") == []


def test_web_flag_routes_to_browser_app(monkeypatch):
    from kairo import __main__ as entry

    called = {}
    monkeypatch.setattr("kairo.web.app.main", lambda: called.setdefault("web", True))
    entry.main(["--web"])
    assert called.get("web") is True
