"""Lead sourcing (BETA) - all network calls are injected, nothing hits the wire."""

import json

from outreach import lead_sourcing

NOMINATIM_JSON = json.dumps([{"lat": "47.01", "lon": "28.86"}])

OVERPASS_JSON = json.dumps({
    "elements": [
        {"type": "node", "tags": {
            "name": "Acme Transport SRL", "office": "logistics",
            "phone": "+373 22 000000", "website": "https://acme-transport.md",
            "addr:street": "Str. Exemplu", "addr:housenumber": "10", "addr:city": "Chisinau"}},
        {"type": "node", "tags": {
            "name": "Beta Warehouse", "industrial": "warehouse",
            "contact:email": "office@beta-wh.md"}},
        {"type": "node", "tags": {"industrial": "yes"}},  # no name -> dropped
    ]
})


def _overpass_fetch(url, data, timeout=25):
    assert "nwr" in data["data"]
    return OVERPASS_JSON


def _geo_fetch(url, timeout=15):
    assert "nominatim" in url
    return NOMINATIM_JSON


def test_search_businesses_parses_elements(monkeypatch):
    monkeypatch.setattr(lead_sourcing.time, "sleep", lambda *_: None)
    leads = lead_sourcing.search_businesses(
        "", "Chisinau", fetch=_overpass_fetch, geocode_fetch=_geo_fetch)
    assert [l["Company"] for l in leads] == ["Acme Transport SRL", "Beta Warehouse"]
    acme = leads[0]
    assert acme["Phone"] == "+373 22 000000"
    assert acme["Website"] == "https://acme-transport.md"
    assert acme["Address"] == "Str. Exemplu, 10, Chisinau"
    assert acme["Source"] == "OSM"
    assert acme["Email"] == ""
    assert leads[1]["Email"] == "office@beta-wh.md"


def test_search_free_text_filter(monkeypatch):
    monkeypatch.setattr(lead_sourcing.time, "sleep", lambda *_: None)
    leads = lead_sourcing.search_businesses(
        "warehouse", "Chisinau", fetch=_overpass_fetch, geocode_fetch=_geo_fetch)
    assert [l["Company"] for l in leads] == ["Beta Warehouse"]


def test_search_returns_empty_when_geocode_fails(monkeypatch):
    monkeypatch.setattr(lead_sourcing.time, "sleep", lambda *_: None)
    leads = lead_sourcing.search_businesses(
        "x", "Nowhere", fetch=_overpass_fetch, geocode_fetch=lambda *a, **k: "[]")
    assert leads == []


HTML = """
<a href="mailto:hello@acme-transport.md">write us</a>
background:url(logo@2x.png); img/spacer.png
sentry-key@o123.ingest.sentry.io
also: sales@othersite.com
"""


def test_scrape_site_emails_filters_junk_and_prefers_host():
    got = lead_sourcing.scrape_site_emails(
        "https://acme-transport.md", fetch=lambda url: HTML)
    assert got[0] == "hello@acme-transport.md"
    assert "sales@othersite.com" in got
    assert all("sentry" not in a and "2x" not in a for a in got)


def test_scrape_site_emails_swallows_network_errors():
    def boom(url):
        raise OSError("connection reset")
    assert lead_sourcing.scrape_site_emails("https://acme-transport.md", fetch=boom) == []


def test_scrape_site_emails_blank_url():
    assert lead_sourcing.scrape_site_emails("", fetch=lambda url: HTML) == []


def test_enrich_fills_missing_email(monkeypatch):
    monkeypatch.setattr(lead_sourcing.time, "sleep", lambda *_: None)
    biz = [{"Company": "Acme", "Email": "", "Website": "https://acme-transport.md"}]
    lead_sourcing.enrich(biz, do_scrape=True, fetch=lambda url: HTML)
    assert biz[0]["Email"] == "hello@acme-transport.md"


def test_enrich_noop_when_disabled():
    biz = [{"Company": "Acme", "Email": "", "Website": "https://acme-transport.md"}]
    lead_sourcing.enrich(biz, do_scrape=False, fetch=lambda url: HTML)
    assert biz[0]["Email"] == ""
