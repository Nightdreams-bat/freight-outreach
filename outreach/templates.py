import jinja2

# Templates are Jinja2 text - {{ var }} to insert a value, {% if var %}...{% endif %} to
# skip a whole line/sentence cleanly when a field is empty (e.g. no Phone on that lead),
# rather than leaving a dangling blank space.
#
# Available variables:
#   Cold intro:  name, company, phone, sender_name, sender_company, sender_phone, sender_pitch
#   Reminder:    name, company, phone, sender_name, sender_company, sender_phone, meeting_time

COLD_INTRO_SUBJECT = "{{ company }} freight - quick question"

COLD_INTRO_BODY = """Hi {{ name }},

{{ sender_name }} here, with {{ sender_company }}. {{ sender_pitch }}

I thought {{ company }} might be worth connecting with - happy to share more if you're open to a short call sometime this week.

If this isn't useful to you right now, no worries at all, just let me know and I won't follow up again.

Best,
{{ sender_name }}
{{ sender_company }}
{% if sender_phone %}{{ sender_phone }}{% endif %}
"""

REMINDER_SUBJECT = "Our call {{ meeting_time }}"

REMINDER_BODY = """Hi {{ name }},

Just a quick reminder that we've got a call scheduled for {{ meeting_time }}. Looking forward to speaking with you about {{ company }}'s freight needs.

Let me know if anything's changed on your end.

Best,
{{ sender_name }}
{{ sender_company }}
{% if sender_phone %}{{ sender_phone }}{% endif %}
"""


_JINJA_ENV = jinja2.Environment(trim_blocks=True, lstrip_blocks=True)


def render(template_text, **kwargs):
    """Renders Jinja2 template text. Raises jinja2.TemplateError on a broken template."""
    return _JINJA_ENV.from_string(template_text).render(**kwargs)
