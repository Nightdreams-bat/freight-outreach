"""The app version is surfaced in the UI, the diagnostics checks and the CLI."""

from kairo import __version__, __main__ as entry
from kairo import diagnostics
from kairo.web import app as web_app
from tests.test_web_replies import BASE_CFG, FakeQueue


def _client(monkeypatch, tmp_path):
    cfg = dict(BASE_CFG)
    cfg["excel_path"] = str(tmp_path / "leads.xlsx")
    monkeypatch.setattr(web_app, "reply_queue", FakeQueue())
    monkeypatch.setattr(web_app, "load_config", lambda: dict(cfg))

    from tests.test_web_leads import FakeStore

    monkeypatch.setattr(web_app, "ExcelStore", lambda *a, **k: FakeStore())
    application = web_app.create_app()
    application.config.update(TESTING=True)
    return application.test_client()


def test_base_layout_renders_the_version(monkeypatch, tmp_path):
    html = _client(monkeypatch, tmp_path).get("/").get_data(as_text=True)
    assert f"Kairo v{__version__}" in html


def test_diagnostics_checks_include_the_version():
    assert "Kairo version" in diagnostics.CHECK_NAMES
    row = diagnostics._check_version({}, None)
    assert row["status"] == "ok"
    assert __version__ in row["detail"]


def test_diagnostics_run_reports_the_version(monkeypatch):
    monkeypatch.setattr(diagnostics, "_CHECKS", [diagnostics._check_version])
    results = diagnostics.run_checks({})
    assert results[0]["name"] == "Kairo version"
    assert __version__ in results[0]["detail"]


def test_cli_version_flag_prints_and_exits(capsys):
    entry.main(["--version"])
    assert capsys.readouterr().out.strip() == f"Kairo {__version__}"
