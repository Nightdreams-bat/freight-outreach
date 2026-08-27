import jinja2

# Templates are Jinja2 text - {{ var }} to insert a value, {% if var %}...{% endif %} to
# skip a whole line/sentence cleanly when a field is empty (e.g. no Phone on that lead),
# rather than leaving a dangling blank space.
#
# Available variables:
#   Cold intro:      name, company, phone, sender_name, sender_company, sender_phone, sender_pitch
#   Follow-up:       name, company, phone, sender_name, sender_company, sender_phone, sender_pitch, stage, is_last
#   Reminder:        name, company, phone, sender_name, sender_company, sender_phone, meeting_time
#   Meeting confirm: name, company, sender_name, sender_company, sender_phone, meeting_time
#   Propose times:   name, company, sender_name, sender_company, sender_phone, slots (list of strings)
#   Decline ack:     name, company, sender_name, sender_company

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

FOLLOWUP_SUBJECT = "Following up - {{ company }} freight"

FOLLOWUP_BODY = """Hi {{ name }},

Circling back on my earlier note about {{ company }}'s freight. I know inboxes get busy, so no pressure - just wanted to make sure it didn't slip through.

If a short call would be useful, I'm happy to work around your schedule. And if it's not the right time, let me know and I'll stop here.

Best,
{{ sender_name }}
{{ sender_company }}
{% if sender_phone %}{{ sender_phone }}{% endif %}
"""

FOLLOWUP_BREAKUP_BODY = """Hi {{ name }},

I've reached out a couple of times about {{ company }}'s freight without hearing back, so I'll leave it here and won't keep filling your inbox.

If things change down the line, you're always welcome to reach out - I'd be glad to help.

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


MEETING_CONFIRM_SUBJECT = "Confirmed - our call {{ meeting_time }}"

MEETING_CONFIRM_BODY = """Hi {{ name }},

Great - I've put us down for {{ meeting_time }} and sent a calendar invite so it's on both our schedules.

Looking forward to talking through {{ company }}'s freight needs then. If anything changes on your end, just let me know.

Best,
{{ sender_name }}
{{ sender_company }}
{% if sender_phone %}{{ sender_phone }}{% endif %}
"""

PROPOSE_TIMES_SUBJECT = "A few times that work - {{ company }}"

PROPOSE_TIMES_BODY = """Hi {{ name }},

Glad you're open to a call. Here are a few times that work on my end:

{% for slot in slots %}  - {{ slot }}
{% endfor %}
Let me know which one suits you and I'll send a calendar invite. If none of these fit, tell me roughly when you're free and I'll work around it.

Best,
{{ sender_name }}
{{ sender_company }}
{% if sender_phone %}{{ sender_phone }}{% endif %}
"""

DECLINE_ACK_SUBJECT = "Thanks for the reply - {{ company }}"

DECLINE_ACK_BODY = """Hi {{ name }},

Understood, and thanks for letting me know. I won't follow up again.

If {{ company }}'s freight needs change down the line, feel free to reach out any time.

Best,
{{ sender_name }}
{{ sender_company }}
"""


_JINJA_ENV = jinja2.Environment(trim_blocks=True, lstrip_blocks=True)


def render(template_text, **kwargs):
    """Renders Jinja2 template text. Raises jinja2.TemplateError on a broken template."""
    return _JINJA_ENV.from_string(template_text).render(**kwargs)
