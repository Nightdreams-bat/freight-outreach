import openpyxl
import pytest

from outreach.excel_store import DATA_COLUMNS, STATE_COLUMNS, ExcelStore, sheet_headers


def _make(path, headers, *rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(list(r))
    wb.save(path)
    return path


def test_auto_detects_aliased_headers(tmp_path):
    p = _make(tmp_path / "leads.xlsx",
              ["Full Name", "Organisation", "E-mail Address", "Mobile"],
              ["Jane Roe", "Acme", "jane@acme.test", "555-1"])
    store = ExcelStore(p)
    rows = list(store.rows())
    assert len(rows) == 1
    _, v = rows[0]
    assert v["Name"] == "Jane Roe"
    assert v["Company"] == "Acme"
    assert v["Email"] == "jane@acme.test"
    assert v["Phone"] == "555-1"


def test_combined_first_last_name(tmp_path):
    p = _make(tmp_path / "leads.xlsx",
              ["First Name", "Last Name", "Email"],
              ["Jane", "Roe", "jane@acme.test"])
    store = ExcelStore(p)
    _, v = list(store.rows())[0]
    assert v["Name"] == "Jane Roe"


def test_explicit_map_overrides_detection(tmp_path):
    p = _make(tmp_path / "leads.xlsx",
              ["Contact", "Alt Contact", "Email"],
              ["Wrong", "Right", "x@acme.test"])
    store = ExcelStore(p, column_map={"Name": "Alt Contact"})
    _, v = list(store.rows())[0]
    assert v["Name"] == "Right"


def test_missing_email_column(tmp_path):
    p = _make(tmp_path / "leads.xlsx", ["Name", "Company"], ["Jane", "Acme"])
    store = ExcelStore(p)
    assert store.email_column_missing is True
    assert list(store.rows()) == []
    assert list(store.all_rows()) == []


def test_email_only_sheet_still_works(tmp_path):
    p = _make(tmp_path / "leads.xlsx", ["Email"], ["jane@acme.test"])
    store = ExcelStore(p)
    _, v = list(store.rows())[0]
    assert v["Email"] == "jane@acme.test"
    assert "Name" not in v  # not mapped -> not read


def test_client_data_columns_never_appended(tmp_path):
    p = _make(tmp_path / "leads.xlsx", ["Full Name", "E-mail Address"],
              ["Jane", "jane@acme.test"])
    ExcelStore(p)
    headers = {c.value for c in openpyxl.load_workbook(p).active[1]}
    # No Phone/Company column was invented for the client...
    assert "Phone" not in headers
    assert "Company" not in headers
    # ...but our own state columns were appended.
    for col in STATE_COLUMNS:
        assert col in headers


def test_set_value_refuses_data_column(tmp_path):
    p = _make(tmp_path / "leads.xlsx", ["Name", "Email"], ["Jane", "jane@acme.test"])
    store = ExcelStore(p)
    store.set_value(2, "ReplyStatus", "yes")  # state column: fine
    with pytest.raises(ValueError):
        store.set_value(2, "Name", "Hacked")


def test_sheet_headers_helper(tmp_path):
    p = _make(tmp_path / "leads.xlsx", ["Full Name", "Email", ""], ["a", "b", ""])
    assert sheet_headers(p) == ["Full Name", "Email"]
    assert sheet_headers(tmp_path / "nope.xlsx") == []


def test_add_lead_appends_and_returns_index(tmp_path):
    p = _make(tmp_path / "leads.xlsx", ["Name", "Company", "Email", "Phone"],
              ["Jane", "Acme", "jane@acme.test", "1"])
    store = ExcelStore(p)
    idx = store.add_lead({"Name": "New", "Company": "NewCo", "Email": "new@newco.test"})
    assert idx == 3
    reopened = ExcelStore(p)
    emails = {v["Email"] for _, v, _ in reopened.all_rows()}
    assert "new@newco.test" in emails


def test_add_lead_rejects_duplicate_and_invalid(tmp_path):
    p = _make(tmp_path / "leads.xlsx", ["Name", "Company", "Email", "Phone"],
              ["Jane", "Acme", "jane@acme.test", "1"])
    store = ExcelStore(p)
    assert store.add_lead({"Company": "X", "Email": "JANE@acme.test"}) is None  # dup, case-insensitive
    assert store.add_lead({"Company": "X", "Email": "not-an-email"}) is None
    assert store.add_lead({"Company": "X", "Email": ""}) is None


def test_add_lead_writes_website_address_only_when_mapped(tmp_path):
    p = _make(tmp_path / "leads.xlsx", ["Name", "Company", "Email", "Phone"],
              ["Jane", "Acme", "jane@acme.test", "1"])
    store = ExcelStore(p)
    store.add_lead({"Company": "NoWeb", "Email": "a@noweb.test",
                    "Website": "https://noweb.test", "Address": "Somewhere"})
    headers = [c.value for c in openpyxl.load_workbook(p).active[1]]
    assert "Website" not in headers and "Address" not in headers

    p2 = _make(tmp_path / "leads2.xlsx", ["Company", "Email", "Website", "Address"],
               ["Acme", "jane@acme.test", "", ""])
    store2 = ExcelStore(p2)
    idx = store2.add_lead({"Company": "WithWeb", "Email": "b@withweb.test",
                           "Website": "https://withweb.test", "Address": "Main St"})
    assert idx is not None
    ws = openpyxl.load_workbook(p2).active
    written = {c.value for c in ws[idx]}
    assert "https://withweb.test" in written and "Main St" in written


def test_data_and_state_column_split_is_exhaustive():
    from outreach.excel_store import LOGICAL_COLUMNS
    assert set(DATA_COLUMNS) | set(STATE_COLUMNS) == set(LOGICAL_COLUMNS)
    assert not (set(DATA_COLUMNS) & set(STATE_COLUMNS))
