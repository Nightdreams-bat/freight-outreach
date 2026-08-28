"""Lead sourcing (BETA) - all network calls are injected, nothing hits the wire."""

from kairo import lead_sourcing


# A fake DuckDuckGo: real company sites mixed with directories and a dupe.
FAKE_RESULTS = [
    {"title": "Acme Transport SRL | Transport marfa Bucuresti", "href": "https://www.acme-transport.ro/"},
    {"title": "Beta Logistica - Depozitare si distributie", "href": "http://beta-logistica.ro/servicii"},
    {"title": "Top firme transport Bucuresti", "href": "https://listafirme.eu/bucuresti/j1.htm"},
    {"title": "Companii - Bucuresti | Kompass", "href": "https://ro.kompass.com/r/bucuresti/"},
    {"title": "Acme Transport - Contact", "href": "https://acme-transport.ro/contact"},  # dupe host
    {"title": "", "href": ""},  # junk
]


def _fake_searcher(query, *, max_results, region):
    assert region == "ro-ro"
    return FAKE_RESULTS


def test_search_keeps_company_sites_drops_directories(monkeypatch):
    monkeypatch.setattr(lead_sourcing.time, "sleep", lambda *_: None)
    leads = lead_sourcing.search_businesses("transport", "Bucuresti", searcher=_fake_searcher)

    assert [l["Website"] for l in leads] == [
        "https://acme-transport.ro", "http://beta-logistica.ro"]
    assert leads[0]["Company"] == "Acme Transport SRL"
    assert leads[0]["Source"] == "web"
    assert leads[0]["Email"] == "" and leads[0]["Phone"] == ""


def test_search_needs_both_terms():
    assert lead_sourcing.search_businesses("", "Bucuresti", searcher=_fake_searcher) == []
    assert lead_sourcing.search_businesses("transport", "", searcher=_fake_searcher) == []


def test_search_swallows_search_errors(monkeypatch):
    monkeypatch.setattr(lead_sourcing.time, "sleep", lambda *_: None)

    def boom(query, *, max_results, region):
        raise RuntimeError("ddg down")

    assert lead_sourcing.search_businesses("x", "Paris", searcher=boom) == []


def test_search_respects_limit(monkeypatch):
    monkeypatch.setattr(lead_sourcing.time, "sleep", lambda *_: None)
    many = [{"title": f"Co {i}", "href": f"https://co{i}.example"} for i in range(50)]
    leads = lead_sourcing.search_businesses(
        "x", "London", limit=5, searcher=lambda *a, **k: many)
    assert len(leads) == 5


HTML = """
<a href="mailto:hello@acme-transport.ro">write us</a>
background:url(logo@2x.png); img/spacer.png
sentry-key@o123.ingest.sentry.io
also: sales@othersite.com
"""


def test_scrape_site_emails_filters_junk_and_prefers_host():
    got = lead_sourcing.scrape_site_emails(
        "https://acme-transport.ro", fetch=lambda url: HTML)
    assert got[0] == "hello@acme-transport.ro"
    assert "sales@othersite.com" in got
    assert all("sentry" not in a and "2x" not in a for a in got)


def test_scrape_site_emails_swallows_network_errors():
    def boom(url):
        raise OSError("connection reset")
    assert lead_sourcing.scrape_site_emails("https://acme-transport.ro", fetch=boom) == []


def test_scrape_site_emails_blank_url():
    assert lead_sourcing.scrape_site_emails("", fetch=lambda url: HTML) == []


def test_enrich_fills_missing_email(monkeypatch):
    monkeypatch.setattr(lead_sourcing.time, "sleep", lambda *_: None)
    biz = [{"Company": "Acme", "Email": "", "Website": "https://acme-transport.ro"}]
    lead_sourcing.enrich(biz, do_scrape=True, fetch=lambda url: HTML)
    assert biz[0]["Email"] == "hello@acme-transport.ro"


def test_enrich_noop_when_disabled():
    biz = [{"Company": "Acme", "Email": "", "Website": "https://acme-transport.ro"}]
    lead_sourcing.enrich(biz, do_scrape=False, fetch=lambda url: HTML)
    assert biz[0]["Email"] == ""
