"""Figure out which spreadsheet column is the name / company / email / phone,
whatever the client happened to call their headers.

The client never describes their file. `detect()` takes the header row and
returns a mapping from our logical field names to the actual header text (or, for
a first-name + last-name pair, to a list of two headers that get joined with a
space). Anything it can't place is simply left out - callers treat a missing
logical field as "this sheet doesn't have that".
"""

import re

# Order matters: logicals are resolved in this order, and a header claimed by an
# earlier field can't be reused by a later one.
SYNONYMS = {
    "Email": [
        "email", "e mail", "email address", "e mail address", "mail",
        "email id", "work email", "contact email",
    ],
    "Company": [
        "company", "company name", "organization", "organisation", "org",
        "business", "business name", "account", "account name", "firm",
        "employer",
    ],
    "Name": [
        "name", "full name", "fullname", "contact", "contact name", "lead",
        "lead name", "person", "contact person", "client", "client name",
        "customer",
    ],
    "Phone": [
        "phone", "phone number", "phone no", "tel", "telephone", "mobile",
        "mobile number", "cell", "cell phone", "contact number",
    ],
}

FIRST_NAME_SYNS = ["first name", "firstname", "first", "given name", "givenname"]
LAST_NAME_SYNS = ["last name", "lastname", "surname", "family name", "familyname"]


def _norm(text) -> str:
    """Lowercase, keep only a-z0-9, so 'E-mail Address' == 'email address' == 'EmailAddress'."""
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def _headers(headers):
    return [(_norm(h), h) for h in headers if h is not None and str(h).strip()]


def _exact(normed, synonyms, claimed):
    syn_norms = {_norm(s) for s in synonyms}
    for nh, raw in normed:
        if raw not in claimed and nh in syn_norms:
            return raw
    return None


def _fuzzy(normed, synonyms, claimed):
    """A header counts as a match when a synonym is a prefix or suffix of it -
    'emailaddress' starts with 'email', 'fullname' ends with 'name' - without the
    false hits a plain substring test causes ('lname' inside 'fullname')."""
    syn_norms = [_norm(s) for s in synonyms if len(_norm(s)) >= 4]
    for syn in syn_norms:
        for nh, raw in normed:
            if raw not in claimed and (nh.startswith(syn) or nh.endswith(syn)):
                return raw
    return None


def _find(normed, synonyms, claimed):
    return _exact(normed, synonyms, claimed) or _fuzzy(normed, synonyms, claimed)


def detect(headers):
    """headers: the spreadsheet's first row. Returns {logical: header | [h1, h2]}."""
    normed = _headers(headers)
    claimed = set()
    mapping = {}

    # First/last-name columns are resolved up front so a "First Name" header
    # isn't mistaken for the whole name by the generic "Name" match below.
    first = _find(normed, FIRST_NAME_SYNS, claimed)
    last = _find(normed, LAST_NAME_SYNS, claimed)

    for logical, synonyms in SYNONYMS.items():
        if logical == "Name":
            reserved = claimed | {h for h in (first, last) if h}
            hit = _find(normed, synonyms, reserved)
            if hit is None and first and last and first != last:
                mapping["Name"] = [first, last]
                claimed.update([first, last])
            elif hit is None and first:
                mapping["Name"] = first
                claimed.add(first)
            elif hit is not None:
                mapping["Name"] = hit
                claimed.add(hit)
            continue

        hit = _find(normed, synonyms, claimed)
        if hit is not None:
            mapping[logical] = hit
            claimed.add(hit)

    return mapping
