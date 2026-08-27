"""Free lead sourcing (BETA).

We have no way to *find* leads - they're hand-typed into clients.xlsx. This pulls
businesses from OpenStreetMap via the Overpass API (no key, no billing) and,
optionally, scrapes a contact email off the company homepage. Lower yield than a
paid Places + Hunter.io path, but $0.

Pure functions, stdlib only. Every network call goes through an injectable
`fetch=` so tests never touch the real network.
"""

import json
import re
import time
import urllib.parse
import urllib.request

from outreach.lead_fields import valid_email
from outreach.logging_setup import get_logger

log = get_logger("lead_sourcing")

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "FreightOutreach/1.0 (lead sourcing; contact via app)"

CONTACT_PATHS = ("/contact", "/contact-us", "/contacts", "/despre", "/contact.html")

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Junk that matches the email regex but never is one.
_EMAIL_JUNK = ("wixpress", "sentry", "example.", "@2x", ".png", ".jpg", ".jpeg",
               ".gif", ".webp", ".svg", "@sha", "core-js", "@babel", "@types")

# Broad tag whitelist - the user types the category, this just keeps the query
# from returning the whole map.
_OSM_FILTERS = (
    '["office"="logistics"]',
    '["office"="company"]',
    '["industrial"]',
    '["landuse"="industrial"]',
    '["shop"="trade"]',
    '["amenity"="courier"]',
)


def _http_get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def _http_post(url, data, timeout=25):
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.read().decode("utf-8", errors="replace")


def _geocode(where, *, fetch):
    q = urllib.parse.urlencode({"format": "json", "limit": 1, "q": where})
    try:
        rows = json.loads(fetch(f"{NOMINATIM_URL}?{q}"))
    except Exception as e:  # noqa: BLE001
        log.warning(f"Geocoding '{where}' failed: {e}")
        return None
    if not rows:
        return None
    try:
        return float(rows[0]["lat"]), float(rows[0]["lon"])
    except (KeyError, ValueError, TypeError):
        return None


def _build_query(lat, lon, *, radius_m=15000, limit=60):
    around = f"(around:{radius_m},{lat},{lon})"
    parts = [f"nwr{f}{around};" for f in _OSM_FILTERS]
    return f"[out:json][timeout:25];({''.join(parts)});out center {int(limit)};"


def _compose_address(tags):
    order = ("addr:street", "addr:housenumber", "addr:postcode", "addr:city")
    bits = [str(tags[k]).strip() for k in order if tags.get(k)]
    return ", ".join(bits)


def _element_to_lead(el):
    tags = el.get("tags") or {}
    name = (tags.get("name") or "").strip()
    if not name:
        return None
    email = (tags.get("email") or tags.get("contact:email") or "").strip()
    return {
        "Name": "",
        "Company": name,
        "Email": email if valid_email(email) else "",
        "Phone": (tags.get("phone") or tags.get("contact:phone") or "").strip(),
        "Website": (tags.get("website") or tags.get("contact:website") or "").strip(),
        "Address": _compose_address(tags),
        "Source": "OSM",
    }


def _matches(lead, what):
    """Free-text filter over name/address - the user's category is the source of truth."""
    if not what:
        return True
    hay = f"{lead['Company']} {lead['Address']}".lower()
    return all(term in hay for term in what.lower().split())


def search_businesses(what, where, *, limit=60, fetch=_http_post, geocode_fetch=_http_get):
    """Businesses near `where` (city / region), loosely filtered by `what`.

    Returns a list of dicts: Name, Company, Email, Phone, Website, Address, Source.
    """
    coords = _geocode(where, fetch=geocode_fetch)
    if not coords:
        log.warning(f"Could not geocode '{where}' - no results")
        return []
    time.sleep(1)  # politeness between the two services

    query = _build_query(coords[0], coords[1], limit=limit)
    try:
        payload = json.loads(fetch(OVERPASS_URL, {"data": query}))
    except Exception as e:  # noqa: BLE001
        log.warning(f"Overpass query failed: {e}")
        return []

    leads = []
    seen = set()
    for el in payload.get("elements", []):
        lead = _element_to_lead(el)
        if lead is None or not _matches(lead, what):
            continue
        key = lead["Company"].lower()
        if key in seen:
            continue
        seen.add(key)
        leads.append(lead)
        if len(leads) >= limit:
            break
    return leads


def _clean_emails(text, site_host=None):
    found = []
    for raw in _EMAIL_RE.findall(text or ""):
        addr = raw.strip(".").lower()
        if any(j in addr for j in _EMAIL_JUNK) or not valid_email(addr):
            continue
        if addr not in found:
            found.append(addr)
    if site_host:
        host = site_host.lower()
        if host.startswith("www."):
            host = host[4:]
        found.sort(key=lambda a: 0 if a.split("@")[-1].endswith(host) else 1)
    return found[:3]


def scrape_site_emails(url, *, fetch=_http_get):
    """Best-effort contact emails from a company website. Never raises - [] on any error."""
    if not url:
        return []
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    try:
        host = urllib.parse.urlparse(url).netloc
    except ValueError:
        return []

    candidates = [url]
    base = url.rstrip("/")
    candidates += [base + p for p in CONTACT_PATHS]

    for i, page in enumerate(candidates):
        if i:
            time.sleep(1)
        try:
            html = fetch(page)
        except Exception:  # noqa: BLE001 - fragile by nature; caller must never see it
            continue
        emails = _clean_emails(html, host)
        if emails:
            return emails
    return []


def enrich(businesses, *, do_scrape, fetch=_http_get):
    """Fill a missing Email by scraping the Website, when do_scrape is on."""
    if not do_scrape:
        return businesses
    for biz in businesses:
        if biz.get("Email") or not biz.get("Website"):
            continue
        hits = scrape_site_emails(biz["Website"], fetch=fetch)
        if hits:
            biz["Email"] = hits[0]
    return businesses
