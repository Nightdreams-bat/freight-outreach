"""Every built-in template renders cleanly in both languages."""

import pytest

from outreach import templates
from outreach.core import _DUMMY_CONTEXT


@pytest.mark.parametrize("lang", ["en", "ro"])
def test_all_defaults_render(lang):
    for key, text in templates.defaults(lang).items():
        templates.render(text, **_DUMMY_CONTEXT)  # must not raise


def test_language_dicts_have_identical_keys():
    assert set(templates.defaults("en")) == set(templates.defaults("ro"))
    # unknown language falls back to English
    assert templates.defaults("xx") == templates.defaults("en")


def test_romanian_differs_from_english():
    en, ro = templates.defaults("en"), templates.defaults("ro")
    assert en["cold_body_template"] != ro["cold_body_template"]
    assert "Bună ziua" in ro["cold_body_template"]


def test_phone_guard_present_in_romanian():
    ro = templates.defaults("ro")
    no_phone = templates.render(ro["cold_body_template"], **{**_DUMMY_CONTEXT, "sender_phone": ""})
    with_phone = templates.render(ro["cold_body_template"], **{**_DUMMY_CONTEXT, "sender_phone": "555"})
    assert "555" in with_phone and "555" not in no_phone


@pytest.mark.parametrize("lang", ["en", "ro"])
def test_footer_carries_address_and_optout(lang):
    ctx = {**_DUMMY_CONTEXT,
           "sender_address": "12 Dock Rd, Chisinau, MD",
           "unsubscribe_line": templates.unsubscribe_line(lang)}
    for key, text in templates.defaults(lang).items():
        if not key.endswith("body_template"):
            continue
        out = templates.render(text, **ctx)
        assert "12 Dock Rd, Chisinau, MD" in out
        assert templates.unsubscribe_line(lang) in out


def test_footer_fields_skip_cleanly_when_blank():
    ctx = {**_DUMMY_CONTEXT, "sender_address": "", "unsubscribe_line": ""}
    out = templates.render(templates.defaults("ro")["cold_body_template"], **ctx)
    assert "STOP" not in out
    assert out.rstrip().endswith(_DUMMY_CONTEXT["sender_company"]) or "555-0100" in out


def test_sandbox_blocks_ssti_payload():
    from outreach import templates as t
    payload = "{{ cycler.__init__.__globals__ }}"
    with pytest.raises(Exception):
        t.render(payload, **_DUMMY_CONTEXT)


def test_check_template_catches_non_template_errors():
    from outreach.core import _check_template
    # {{1/0}} raises ZeroDivisionError, not a jinja2.TemplateError - must still be
    # caught pre-flight rather than aborting a batch mid-run.
    assert _check_template("ok", "{{ 1/0 }}") is not None
    assert _check_template("ok", "hello {{ name }}") is None
