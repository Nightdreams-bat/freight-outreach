import pytest

from outreach.lead_fields import (
    derive_company,
    derive_name,
    lead_company,
    lead_name,
    valid_email,
)


@pytest.mark.parametrize("addr,ok", [
    ("john.doe@example.com", True),
    ("a+b%c-d_e@sub.example.co.uk", True),
    ("UPPER@Example.COM", True),
    ("has space@example.com", False),
    ("no-tld@example", False),
    ("trailing.dot@example.com.", False),
    ("double@@example.com", False),
    ("naïve@example.com", False),
    ("", False),
    ("@example.com", False),
    ("john@.com", False),
])
def test_valid_email_truth_table(addr, ok):
    assert valid_email(addr) is ok


def test_valid_email_rejects_overlong():
    assert valid_email("a" * 250 + "@example.com") is False


def test_derive_name_from_dotted_local_part():
    assert derive_name("john.doe@example.com") == "John"
    assert derive_name("j.doe@acme-freight.com") == "Doe"


def test_derive_name_strips_digits():
    assert derive_name("anna23@example.com") == "Anna"


def test_derive_name_role_account_is_none():
    assert derive_name("sales@example.com") is None
    assert derive_name("info@example.com") is None


def test_derive_name_unusable_is_none():
    assert derive_name("x@example.com") is None
    assert derive_name("") is None


def test_derive_company_from_domain():
    assert derive_company("j.doe@acme-freight.com") == "Acme Freight"
    assert derive_company("a@example.com") == "Example"


def test_derive_company_handles_second_level_tld():
    assert derive_company("a@acme.co.uk") == "Acme"


def test_derive_company_generic_domain_is_none():
    assert derive_company("someone@gmail.com") is None
    assert derive_company("someone@outlook.com") is None


def test_lead_name_prefers_real_value():
    assert lead_name({"Name": "Pat Real", "Email": "sales@acme.com"}) == "Pat Real"


def test_lead_name_falls_back_then_derives_then_default():
    assert lead_name({"Name": "", "Email": "john.doe@x.com"}) == "John"
    assert lead_name({"Email": "sales@x.com"}) == "there"
    assert lead_name({}) == "there"


def test_lead_company_prefers_real_value_then_derives():
    assert lead_company({"Company": "Real Co", "Email": "a@acme.com"}) == "Real Co"
    assert lead_company({"Email": "a@acme-freight.com"}) == "Acme Freight"
    assert lead_company({"Email": "a@gmail.com"}) == "your company"
