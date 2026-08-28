"""Free lead sourcing (BETA).

We can't *find* leads - they're hand-typed into clients.xlsx. This searches the web
(DuckDuckGo, via the `ddgs` library - no key, no billing) for "<category> <city>",
keeps the results that look like a company's own website, and scrapes a contact
email off each one.

Yield is modest and depends on a business ranking on the first page or two: expect
a handful of usable leads per search, best with a specific category ("distribuitor
ambalaje", not "trading"). But it costs nothing and nothing gets rate-limited hard.

Network calls go through injectable callables (`searcher=` / `fetch=`) so tests
never touch the real network.
"""

import re
import time
import urllib.parse
import urllib.request
from urllib.parse import urlparse

from outreach.lead_fields import valid_email
from outreach.logging_setup import get_logger

log = get_logger("lead_sourcing")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FreightOutreach/1.0"

# Cap on a single page fetch - a hostile / misconfigured server can otherwise
# stream unbounded bytes into memory.
MAX_HTML_BYTES = 2_000_000

CONTACT_PATHS = ("/contact", "/contacte", "/contact-us", "/despre-noi")

# Whole-run wall-clock budget for enrich()'s site scraping. The search itself is
# quick; scraping N sites x M pages with per-request timeouts is what used to make
# a search hang for minutes with no result. Past this many seconds we stop
# scraping and return whatever emails we already have.
SCRAPE_BUDGET_SECONDS = 40

# Result hosts that are directories / social / marketplaces - never a company's
# own site, so they're no use as a lead even though they rank well.
_SKIP_HOSTS = (
    "facebook.", "instagram.", "linkedin.", "twitter.", "x.com", "youtube.",
    "tiktok.", "pinterest.", "wikipedia.", "google.", "goo.gl", "maps.",
    "yelp.", "tripadvisor.", "yellowpages.", "paginiaurii.ro", "cylex",
    "listafirme.", "firme.info", "firmania.ro", "topfirme.com", "mfinante.ro",
    "anaf.ro", "termene.ro", "targetare.ro", "cautarefirme.ro", "clubafaceri.ro",
    "doingbusiness.ro", "kompass.com", "ghidul.ro", "einformatii.ro", "ccib.ro",
    "europages.", "clutch.co", "glassdoor.", "indeed.", "jooble.", "olx.",
    "ebay.", "amazon.", "trustpilot.", "crunchbase.", "bloomberg.", "reddit.",
    "medium.com", "wordpress.com", "blogspot.", "github.", "t.me", "zf.ro",
    "bizz.club", "agendaconstructiilor.ro", "bizoo.ro", "wixsite.com",
    "afacerist.ro", "anunturi", "bizcaf.ro", "wlw.", "b2b-market.",
)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Matches the email regex but is never a real address.
_EMAIL_JUNK = ("wixpress", "sentry", "example.", "@2x", ".png", ".jpg", ".jpeg",
               ".gif", ".webp", ".svg", "@sha", "core-js", "@babel", "@types",
               "your-email", "email@", "@domain", "@example", "user@", "name@")

_TITLE_SEPS = (" | ", " – ", " — ", " - ", " · ", " :: ", " » ")

# Which DuckDuckGo region to search. Romanian city / county hints -> ro-ro.
_RO_HINTS = ("romania", "românia", "bucharest", "bucuresti", "bucurești", "ilfov",
             "cluj", "timis", "timiș", "iasi", "iași", "constanta", "constanța",
             "brasov", "brașov", "sibiu", "craiova", "oradea", "arad", "galati",
             "galați", "ploiesti", "ploiești", "pitesti", "pitești", "moldova",
             "chisinau", "chișinău")


def _http_get(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        if resp.headers.get_content_type() not in ("text/html", "application/xhtml+xml", ""):
            return ""
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read(MAX_HTML_BYTES).decode(charset, errors="replace")


def _ddgs_search(query, *, max_results, region):
    """The real web search. Imported lazily so the module loads without `ddgs`."""
    from ddgs import DDGS

    with DDGS() as ddgs:
        return list(ddgs.text(query, region=region, max_results=max_results))


def _region_for(where):
    w = (where or "").lower()
    return "ro-ro" if any(h in w for h in _RO_HINTS) else "wt-wt"


def _host_of(url):
    host = (urlparse(url).netloc or "").lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host


def _company_from_title(title, fallback):
    for sep in _TITLE_SEPS:
        if sep in title:
            title = title.split(sep)[0]
    title = title.strip(" -–—·|")
    return title[:120] if title else fallback


def search_businesses(what, where, *, limit=25, searcher=_ddgs_search):
    """Company websites for "<what> <where>", de-duplicated by domain.

    Returns a list of dicts: Name, Company, Email, Phone, Website, Address, Source.
    Email / Phone / Address start blank - enrich() fills the email from the site.
    """
    what = (what or "").strip()
    where = (where or "").strip()
    if not what or not where:
        return []

    region = _region_for(where)
    queries = [f"{what} {where}", f"{what} {where} contact"]

    rows = []
    for i, query in enumerate(queries):
        if i:
            time.sleep(1)  # be gentle between searches
        try:
            rows += searcher(query, max_results=limit * 2, region=region)
        except Exception as e:  # noqa: BLE001 - search is best-effort
            log.warning(f"Web search for {query!r} failed: {e}")

    leads, seen = [], set()
    for row in rows:
        href = (row.get("href") or row.get("url") or row.get("link") or "").strip()
        if not href:
            continue
        host = _host_of(href)
        if not host or host in seen or any(s in host for s in _SKIP_HOSTS):
            continue
        seen.add(host)
        scheme = urlparse(href).scheme or "https"
        leads.append({
            "Name": "",
            "Company": _company_from_title(row.get("title") or "", host),
            "Email": "",
            "Phone": "",
            "Website": f"{scheme}://{host}",
            "Address": "",
            "Source": "web",
        })
        if len(leads) >= limit:
            break

    log.info(f"Lead search '{what}' / '{where}': {len(rows)} results -> {len(leads)} company sites")
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


def scrape_site_emails(url, *, fetch=_http_get, deadline=None):
    """Best-effort contact emails from a company website. Never raises - [] on any error.

    `deadline` is an optional time.monotonic() value; we stop trying more pages
    once it passes so one slow site can't stall the whole search.
    """
    if not url:
        return []
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    try:
        host = urlparse(url).netloc
    except ValueError:
        return []

    base = url.rstrip("/")
    candidates = [url] + [base + p for p in CONTACT_PATHS]

    for i, page in enumerate(candidates):
        if deadline is not None and time.monotonic() > deadline:
            break
        if i:
            time.sleep(0.4)
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
    deadline = time.monotonic() + SCRAPE_BUDGET_SECONDS
    for biz in businesses:
        if biz.get("Email") or not biz.get("Website"):
            continue
        if time.monotonic() > deadline:
            log.info("enrich: scrape budget reached, leaving remaining sites unenriched")
            break
        hits = scrape_site_emails(biz["Website"], fetch=fetch, deadline=deadline)
        if hits:
            biz["Email"] = hits[0]
    return businesses
