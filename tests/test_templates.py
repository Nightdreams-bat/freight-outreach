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
