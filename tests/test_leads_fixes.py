"""Follow-up fixes to the Leads / Find-leads flow:

* a deleted leads file is never silently recreated (error surfaces instead)
* the Find-leads limit is configurable
* Diagnostics reports what changed since the last run
"""

import openpyxl
import pytest

from kairo import config, diag_state, diagnostics
from kairo.excel_store import ExcelFileMissing, ExcelStore


# --- deleted leads file is not recreated ---------------------------------

def test_excelstore_raises_when_missing_and_not_allowed_to_create(tmp_path):
    missing = tmp_path / "gone.xlsx"
    with pytest.raises(ExcelFileMissing):
        ExcelStore(missing, create_if_missing=False)
    assert not missing.exists()  # and it did not create one as a side effect


def test_excelstore_still_creates_by_default(tmp_path):
    p = tmp_path / "fresh.xlsx"
    ExcelStore(p)
    assert p.exists()


def test_diagnostics_flags_a_missing_leads_file(tmp_path):
    cfg = {"excel_path": str(tmp_path / "nope.xlsx")}
    result = diagnostics._check_excel(cfg, None)
    assert result["status"] == "fail"
    assert "not found" in result["detail"].lower()
    assert "recreate" in result["detail"].lower()


def test_first_run_seeds_a_leads_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DEFAULT_EXCEL_PATH", tmp_path / "clients.xlsx")
    cfg = config.load_config()
    assert (tmp_path / "config.json").exists()
    assert cfg["excel_path"] == str(tmp_path / "clients.xlsx")
    assert (tmp_path / "clients.xlsx").exists()  # seeded once, on first run
    headers = [c.value for c in openpyxl.load_workbook(tmp_path / "clients.xlsx").active[1]]
    assert "Email" in headers


# --- configurable Find-leads limit -------------------------------------

def test_lead_search_limit_clamps():
    from kairo.web.app import _lead_search_limit

    assert _lead_search_limit({"find_leads_limit": 200}) == 75
    assert _lead_search_limit({"find_leads_limit": 1}) == 5
    assert _lead_search_limit({"find_leads_limit": 40}) == 40
    assert _lead_search_limit({"find_leads_limit": "oops"}) == 25
    assert _lead_search_limit({}) == 25  # falls back to the DEFAULTS value


def test_default_config_has_find_leads_limit():
    assert config.DEFAULTS["find_leads_limit"] == 25


# --- blocklist is checked before a search's results are kept ------------

def test_drop_blocked_filters_by_email_and_domain():
    from kairo import lead_sourcing

    leads = [
        {"Company": "OK", "Email": "hi@good.test", "Website": "https://good.test"},
        {"Company": "BadEmail", "Email": "x@good.test", "Website": "https://good.test"},
        {"Company": "BadDomain", "Email": "", "Website": "https://spam.test"},
        {"Company": "BadSub", "Email": "a@mail.spam.test", "Website": ""},
    ]
    kept = lead_sourcing.drop_blocked(
        leads, disallowed_emails=["x@good.test"], disallowed_domains=["spam.test"]
    )
    assert [l["Company"] for l in kept] == ["OK"]


def test_drop_blocked_noop_without_a_blocklist():
    from kairo import lead_sourcing

    leads = [{"Company": "A", "Email": "a@b.test", "Website": ""}]
    assert lead_sourcing.drop_blocked(leads) == leads


# --- Diagnostics change notification ----------------------------------

@pytest.fixture
def diag_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(diag_state, "DIAG_STATE_PATH", tmp_path / "diag.json")
    return tmp_path / "diag.json"


def test_first_diag_run_reports_no_changes(diag_snapshot):
    meta = diag_state.diff_and_record([{"name": "Gmail", "status": "ok", "detail": ""}])
    assert meta["changes"] == []
    assert meta["previous_run"] is None
    assert diag_snapshot.exists()


def test_diag_run_reports_status_flips(diag_snapshot):
    diag_state.diff_and_record([
        {"name": "Gmail", "status": "ok", "detail": ""},
        {"name": "Calendar", "status": "ok", "detail": ""},
    ])
    meta = diag_state.diff_and_record([
        {"name": "Gmail", "status": "fail", "detail": "token expired"},
        {"name": "Calendar", "status": "ok", "detail": ""},
    ])
    assert meta["changes"] == [{"name": "Gmail", "from": "ok", "to": "fail"}]
    assert meta["previous_run"] is not None


def test_diag_run_ignores_brand_new_checks(diag_snapshot):
    diag_state.diff_and_record([{"name": "Gmail", "status": "ok", "detail": ""}])
    meta = diag_state.diff_and_record([
        {"name": "Gmail", "status": "ok", "detail": ""},
        {"name": "New Check", "status": "warn", "detail": ""},
    ])
    assert meta["changes"] == []
