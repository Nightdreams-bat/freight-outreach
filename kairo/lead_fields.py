"""Fill in a usable name / company when a lead row only gave us an email.

The client's leads file is often sparse - sometimes a row is nothing but an
address. Rather than emailing "Hi there" at "your company", we guess:

    j.doe@acme-freight.com   ->  name "Doe",  company "Acme Freight"
    john.doe@example.com     ->  name "John", company "Example"
    sales@example.com        ->  role account: no name guess

Real values in the sheet always win; these are only used to fill a blank.
"""

import re

GENERIC_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com",
    "msn.com", "yahoo.com", "ymail.com", "aol.com", "icloud.com", "me.com",
    "mac.com", "proton.me", "protonmail.com", "gmx.com", "mail.com",
    "zoho.com", "yandex.com", "hey.com",
}

# Local parts that are a department, not a person.
ROLE_LOCALPARTS = {
    "info", "sales", "contact", "admin", "support", "office", "team",
    "dispatch", "hello", "hi", "enquiries", "inquiries", "accounts",
    "billing", "help", "service", "marketing", "hr", "jobs", "careers",
    "noreply", "no-reply", "webmaster", "postmaster",
}

# Second-level labels that aren't the company name (example.co.uk, example.com.au).
_SECOND_LEVEL = {"co", "com", "org", "net", "gov", "edu", "ac"}

_SPLIT_RE = re.compile(r"[.\-_+]+")

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def clean_email(addr):
    """Strip the cruft that clings to an address copied off a web page or a
    "mailto:" link: the scheme, angle brackets, a "?subject=..." tail, and any
    trailing junk after the first address in a list. Case is left alone.

        "mailto:sales@acme.com?subject=Hi"  -> "sales@acme.com"
        "<john@acme.com>"                   -> "john@acme.com"
    """
    text = str(addr or "").strip().strip("<>").strip()
    if text.lower().startswith("mailto:"):
        text = text[len("mailto:"):]
    text = text.split("?", 1)[0]          # drop ?subject=/&body=
    text = re.split(r"[,;\s]", text, 1)[0]  # first address of a list
    return text.strip().strip("<>").strip()


def valid_email(addr):
    """Syntactic-only check (no network / MX lookup). Lower-cases the domain.
    Tolerates a mailto: / angle-bracket wrapper via clean_email()."""
    text = clean_email(addr)
    if not text or len(text) > 254 or "@" not in text:
        return False
    local, _, domain = text.rpartition("@")
    return bool(_EMAIL_RE.match(f"{local}@{domain.lower()}"))


def derive_name(email):
    """Best-effort first name from an email's local part, or None."""
    local = str(email or "").split("@", 1)[0].strip().lower()
    if not local or local in ROLE_LOCALPARTS:
        return None
    tokens = [re.sub(r"\d+", "", t) for t in _SPLIT_RE.split(local)]
    tokens = [t for t in tokens if len(t) >= 2 and t.isalpha()]
    if not tokens:
        return None
    return tokens[0].title()


def derive_company(email):
    """Best-effort company name from an email's domain, or None for webmail."""
    domain = str(email or "").split("@", 1)[-1].strip().lower()
    if not domain or "." not in domain or domain in GENERIC_EMAIL_DOMAINS:
        return None
    labels = [l for l in domain.split(".") if l]
    labels = labels[:-1]  # drop the TLD
    if len(labels) >= 2 and labels[-1] in _SECOND_LEVEL:
        labels = labels[:-1]
    if not labels:
        return None
    core = labels[-1].replace("-", " ").replace("_", " ").strip()
    if not core:
        return None
    return core.title()


def _present(value):
    text = str(value).strip() if value is not None else ""
    return text or None


def lead_name(row):
    return _present(row.get("Name")) or derive_name(row.get("Email")) or "there"


def lead_company_or_none(row):
    """The real or email-derived company, or None when we have neither.

    Use this anywhere the value stands on its own - an email subject, a queue
    label - where the "your company" fallback from `lead_company()` would read as
    a literal placeholder. `lead_company()` keeps that fallback for in-sentence
    body copy ("worth connecting with your company").
    """
    return _present(row.get("Company")) or derive_company(row.get("Email"))


def lead_company(row):
    return lead_company_or_none(row) or "your company"
