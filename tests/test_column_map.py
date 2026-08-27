from outreach.column_map import detect


def test_exact_standard_headers():
    m = detect(["Name", "Company", "Email", "Phone"])
    assert m == {"Name": "Name", "Company": "Company", "Email": "Email", "Phone": "Phone"}


def test_aliased_headers():
    m = detect(["Full Name", "Organisation", "E-mail Address", "Mobile"])
    assert m["Name"] == "Full Name"
    assert m["Company"] == "Organisation"
    assert m["Email"] == "E-mail Address"
    assert m["Phone"] == "Mobile"


def test_first_and_last_name_combine():
    m = detect(["First Name", "Surname", "Company", "Email"])
    assert m["Name"] == ["First Name", "Surname"]


def test_only_first_name():
    m = detect(["First Name", "Email"])
    assert m["Name"] == "First Name"


def test_email_only_sheet():
    m = detect(["Email"])
    assert m == {"Email": "Email"}


def test_unknown_headers_ignored():
    m = detect(["Region", "Notes", "Email"])
    assert set(m) == {"Email"}


def test_exact_match_wins_over_fuzzy():
    # "Company Name" would fuzzily match Name; the exact "Name" header must win.
    m = detect(["Name", "Company Name", "Email"])
    assert m["Name"] == "Name"
    assert m["Company"] == "Company Name"


def test_a_header_is_not_claimed_twice():
    m = detect(["Contact", "Email"])
    # "Contact" maps to Name; it must not also come back as Phone ("contact number").
    assert m.get("Name") == "Contact"
    assert "Phone" not in m


def test_blank_and_none_headers_skipped():
    m = detect([None, "", "  ", "Email"])
    assert m == {"Email": "Email"}
