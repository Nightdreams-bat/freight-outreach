import jinja2
import jinja2.sandbox

# Templates are Jinja2 text - {{ var }} to insert a value, {% if var %}...{% endif %} to
# skip a whole line/sentence cleanly when a field is empty (e.g. no Phone on that lead),
# rather than leaving a dangling blank space.
#
# Every body also gets `sender_address` (the operator's postal address, required
# on commercial email by anti-spam law) and `unsubscribe_line` (a rendered
# one-line opt-out instruction) - both appended to the signature footer and both
# skipped cleanly when empty.
#
# Available variables:
#   Cold intro:      name, company, phone, sender_name, sender_company, sender_phone, sender_pitch, sender_address, unsubscribe_line
#   Follow-up:       name, company, phone, sender_name, sender_company, sender_phone, sender_pitch, sender_address, unsubscribe_line, stage, is_last
#   Reminder:        name, company, phone, sender_name, sender_company, sender_phone, sender_address, unsubscribe_line, meeting_time
#   Meeting confirm: name, company, sender_name, sender_company, sender_phone, sender_address, unsubscribe_line, meeting_time
#   Propose times:   name, company, sender_name, sender_company, sender_phone, sender_address, unsubscribe_line, slots (list of strings), declined_their_time (bool), their_proposed_time (string)
#   Decline ack:     name, company, sender_name, sender_company, sender_address, unsubscribe_line

# Human-readable meeting time shown in reminder emails, the scheduling module,
# and the reply-queue display helpers. One source of truth.
MEETING_TIME_DISPLAY_FMT = "%A, %b %d at %I:%M %p"

COLD_INTRO_SUBJECT = "Quick question about your freight"

COLD_INTRO_BODY = """Hi {{ name }},

{% if hook %}{{ hook }}

{% endif %}{{ sender_name }} here, with {{ sender_company }}. {{ sender_pitch }}

I thought {{ company }} might be worth connecting with - happy to share more if you're open to a short call sometime this week.

If this isn't useful to you right now, no worries at all, just let me know and I won't follow up again.

Best,
{{ sender_name }}
{{ sender_company }}
{% if sender_phone %}{{ sender_phone }}
{% endif %}{% if sender_address %}{{ sender_address }}
{% endif %}{% if unsubscribe_line %}{{ unsubscribe_line }}
{% endif %}"""

FOLLOWUP_SUBJECT = "Following up on your freight"

FOLLOWUP_BODY = """Hi {{ name }},

Circling back on my earlier note about {{ company }}'s freight. I know inboxes get busy, so no pressure - just wanted to make sure it didn't slip through.

If a short call would be useful, I'm happy to work around your schedule. And if it's not the right time, let me know and I'll stop here.

Best,
{{ sender_name }}
{{ sender_company }}
{% if sender_phone %}{{ sender_phone }}
{% endif %}{% if sender_address %}{{ sender_address }}
{% endif %}{% if unsubscribe_line %}{{ unsubscribe_line }}
{% endif %}"""

FOLLOWUP_BREAKUP_BODY = """Hi {{ name }},

I've reached out a couple of times about {{ company }}'s freight without hearing back, so I'll leave it here and won't keep filling your inbox.

If things change down the line, you're always welcome to reach out - I'd be glad to help.

Best,
{{ sender_name }}
{{ sender_company }}
{% if sender_phone %}{{ sender_phone }}
{% endif %}{% if sender_address %}{{ sender_address }}
{% endif %}{% if unsubscribe_line %}{{ unsubscribe_line }}
{% endif %}"""


REMINDER_SUBJECT = "Our call {{ meeting_time }}"

REMINDER_BODY = """Hi {{ name }},

Just a quick reminder that we've got a call scheduled for {{ meeting_time }}. Looking forward to speaking with you about {{ company }}'s freight needs.

Let me know if anything's changed on your end.

Best,
{{ sender_name }}
{{ sender_company }}
{% if sender_phone %}{{ sender_phone }}
{% endif %}{% if sender_address %}{{ sender_address }}
{% endif %}{% if unsubscribe_line %}{{ unsubscribe_line }}
{% endif %}"""


MEETING_CONFIRM_SUBJECT = "Confirmed - our call {{ meeting_time }}"

MEETING_CONFIRM_BODY = """Hi {{ name }},

Great - I've put us down for {{ meeting_time }} and sent a calendar invite so it's on both our schedules.

Looking forward to talking through {{ company }}'s freight needs then. If anything changes on your end, just let me know.

Best,
{{ sender_name }}
{{ sender_company }}
{% if sender_phone %}{{ sender_phone }}
{% endif %}{% if sender_address %}{{ sender_address }}
{% endif %}{% if unsubscribe_line %}{{ unsubscribe_line }}
{% endif %}"""

PROPOSE_TIMES_SUBJECT = "A few times that work"

PROPOSE_TIMES_BODY = """Hi {{ name }},

{% if declined_their_time %}Thanks for the reply. {{ their_proposed_time }} doesn't work on my end, but here are a few that do:{% else %}Glad you're open to a call. Here are a few times that work on my end:{% endif %}

{% for slot in slots %}  - {{ slot }}
{% endfor %}
Let me know which one suits you and I'll send a calendar invite. If none of these fit, tell me roughly when you're free and I'll work around it.

Best,
{{ sender_name }}
{{ sender_company }}
{% if sender_phone %}{{ sender_phone }}
{% endif %}{% if sender_address %}{{ sender_address }}
{% endif %}{% if unsubscribe_line %}{{ unsubscribe_line }}
{% endif %}"""

DECLINE_ACK_SUBJECT = "Thanks for the reply"

DECLINE_ACK_BODY = """Hi {{ name }},

Understood, and thanks for letting me know. I won't follow up again.

If {{ company }}'s freight needs change down the line, feel free to reach out any time.

Best,
{{ sender_name }}
{{ sender_company }}
{% if sender_address %}{{ sender_address }}
{% endif %}{% if unsubscribe_line %}{{ unsubscribe_line }}
{% endif %}"""


# --- Romanian template set ------------------------------------------------
# The tool is used mainly in Romanian. Same Jinja variables and {% if sender_phone %}
# guards as the English constants above; natural business Romanian.

COLD_INTRO_SUBJECT_RO = "O întrebare scurtă despre transportul dumneavoastră"

COLD_INTRO_BODY_RO = """Bună ziua {{ name }},

{% if hook %}{{ hook }}

{% endif %}Sunt {{ sender_name }}, de la {{ sender_company }}. {{ sender_pitch }}

M-am gândit că ar putea fi util să discutăm despre transportul {{ company }} - vă pot oferi mai multe detalii dacă sunteți deschis unui apel scurt săptămâna aceasta.

Dacă acest lucru nu vă este util acum, nicio problemă, spuneți-mi și nu voi mai reveni.

Cu stimă,
{{ sender_name }}
{{ sender_company }}
{% if sender_phone %}{{ sender_phone }}
{% endif %}{% if sender_address %}{{ sender_address }}
{% endif %}{% if unsubscribe_line %}{{ unsubscribe_line }}
{% endif %}"""

FOLLOWUP_SUBJECT_RO = "Revin la mesajul meu anterior"

FOLLOWUP_BODY_RO = """Bună ziua {{ name }},

Revin la mesajul meu anterior despre transportul {{ company }}. Știu că inboxul se aglomerează, așa că nu vă presez - am vrut doar să mă asigur că mesajul nu s-a pierdut.

Dacă un apel scurt v-ar fi util, mă adaptez programului dumneavoastră. Iar dacă nu este momentul potrivit, spuneți-mi și mă opresc aici.

Cu stimă,
{{ sender_name }}
{{ sender_company }}
{% if sender_phone %}{{ sender_phone }}
{% endif %}{% if sender_address %}{{ sender_address }}
{% endif %}{% if unsubscribe_line %}{{ unsubscribe_line }}
{% endif %}"""

FOLLOWUP_BREAKUP_BODY_RO = """Bună ziua {{ name }},

V-am contactat de câteva ori în legătură cu transportul {{ company }} fără să primesc un răspuns, așa că mă opresc aici și nu vă voi mai încărca inboxul.

Dacă situația se schimbă pe viitor, îmi puteți scrie oricând - v-aș ajuta cu plăcere.

Cu stimă,
{{ sender_name }}
{{ sender_company }}
{% if sender_phone %}{{ sender_phone }}
{% endif %}{% if sender_address %}{{ sender_address }}
{% endif %}{% if unsubscribe_line %}{{ unsubscribe_line }}
{% endif %}"""

REMINDER_SUBJECT_RO = "Apelul nostru {{ meeting_time }}"

REMINDER_BODY_RO = """Bună ziua {{ name }},

Un scurt memento că avem un apel programat pentru {{ meeting_time }}. Aștept cu interes să discutăm despre nevoile de transport ale {{ company }}.

Spuneți-mi dacă s-a schimbat ceva între timp.

Cu stimă,
{{ sender_name }}
{{ sender_company }}
{% if sender_phone %}{{ sender_phone }}
{% endif %}{% if sender_address %}{{ sender_address }}
{% endif %}{% if unsubscribe_line %}{{ unsubscribe_line }}
{% endif %}"""

MEETING_CONFIRM_SUBJECT_RO = "Confirmat - apelul nostru {{ meeting_time }}"

MEETING_CONFIRM_BODY_RO = """Bună ziua {{ name }},

Perfect - am rezervat {{ meeting_time }} și am trimis o invitație în calendar, ca să fie în agenda amândurora.

Aștept cu interes să discutăm despre nevoile de transport ale {{ company }}. Dacă se schimbă ceva în programul dumneavoastră, spuneți-mi.

Cu stimă,
{{ sender_name }}
{{ sender_company }}
{% if sender_phone %}{{ sender_phone }}
{% endif %}{% if sender_address %}{{ sender_address }}
{% endif %}{% if unsubscribe_line %}{{ unsubscribe_line }}
{% endif %}"""

PROPOSE_TIMES_SUBJECT_RO = "Câteva intervale disponibile"

PROPOSE_TIMES_BODY_RO = """Bună ziua {{ name }},

{% if declined_their_time %}Vă mulțumesc pentru răspuns. {{ their_proposed_time }} nu îmi este posibil, însă iată câteva intervale care îmi convin:{% else %}Mă bucur că sunteți deschis unui apel. Iată câteva intervale care îmi convin:{% endif %}

{% for slot in slots %}  - {{ slot }}
{% endfor %}
Spuneți-mi care vă convine și trimit o invitație în calendar. Dacă niciunul nu se potrivește, spuneți-mi aproximativ când sunteți disponibil și mă adaptez.

Cu stimă,
{{ sender_name }}
{{ sender_company }}
{% if sender_phone %}{{ sender_phone }}
{% endif %}{% if sender_address %}{{ sender_address }}
{% endif %}{% if unsubscribe_line %}{{ unsubscribe_line }}
{% endif %}"""

DECLINE_ACK_SUBJECT_RO = "Vă mulțumesc pentru răspuns"

DECLINE_ACK_BODY_RO = """Bună ziua {{ name }},

Am înțeles și vă mulțumesc că mi-ați spus. Nu voi mai reveni.

Dacă nevoile de transport ale {{ company }} se schimbă pe viitor, îmi puteți scrie oricând.

Cu stimă,
{{ sender_name }}
{{ sender_company }}
{% if sender_address %}{{ sender_address }}
{% endif %}{% if unsubscribe_line %}{{ unsubscribe_line }}
{% endif %}"""


# config key -> (English, Romanian). One source of truth for config.py seeding,
# core.py's fallback, and the Settings "reset templates" action.
_TEMPLATE_KEYS = {
    "cold_subject_template": (COLD_INTRO_SUBJECT, COLD_INTRO_SUBJECT_RO),
    "cold_body_template": (COLD_INTRO_BODY, COLD_INTRO_BODY_RO),
    "followup_subject_template": (FOLLOWUP_SUBJECT, FOLLOWUP_SUBJECT_RO),
    "followup_body_template": (FOLLOWUP_BODY, FOLLOWUP_BODY_RO),
    "followup_breakup_body_template": (FOLLOWUP_BREAKUP_BODY, FOLLOWUP_BREAKUP_BODY_RO),
    "reminder_subject_template": (REMINDER_SUBJECT, REMINDER_SUBJECT_RO),
    "reminder_body_template": (REMINDER_BODY, REMINDER_BODY_RO),
    "meeting_confirm_subject_template": (MEETING_CONFIRM_SUBJECT, MEETING_CONFIRM_SUBJECT_RO),
    "meeting_confirm_body_template": (MEETING_CONFIRM_BODY, MEETING_CONFIRM_BODY_RO),
    "propose_times_subject_template": (PROPOSE_TIMES_SUBJECT, PROPOSE_TIMES_SUBJECT_RO),
    "propose_times_body_template": (PROPOSE_TIMES_BODY, PROPOSE_TIMES_BODY_RO),
    "decline_ack_subject_template": (DECLINE_ACK_SUBJECT, DECLINE_ACK_SUBJECT_RO),
    "decline_ack_body_template": (DECLINE_ACK_BODY, DECLINE_ACK_BODY_RO),
}


# One-line opt-out instruction rendered into every body's footer (as the
# `unsubscribe_line` context value). Kept short and plain so it reads as a
# sentence, not boilerplate.
_UNSUBSCRIBE_LINE = {
    "en": "Reply STOP to this email and I won't contact you again.",
    "ro": "Răspundeți cu STOP la acest e-mail și nu vă voi mai contacta.",
}


def unsubscribe_line(lang="en"):
    return _UNSUBSCRIBE_LINE["ro" if lang == "ro" else "en"]


# Short freight-broker opening lines - the default seed for the carrier/shipper
# hook-snippet library. Plain text (not Jinja); the user edits these on Settings.
# Carrier- and shipper-oriented lines mixed; they're only defaults.
HOOK_SNIPPETS = {
    "en": [
        "Noticed you run lanes in and out of the region and figured our capacity might line up.",
        "We move a steady volume of reefer and dry van freight and are short on trucks this quarter.",
        "Helping a few shippers your size cover overflow loads without leaning on the load boards.",
        "If you're carrying your own freight right now, we can take the lanes that don't fit your fleet.",
    ],
    "ro": [
        "Am văzut că aveți curse regulate în zonă și m-am gândit că am putea colabora pe capacitate.",
        "Mișcăm constant marfă în regim frigorific și prelată și ne lipsesc camioane în acest trimestru.",
        "Ajutăm câțiva expeditori de mărimea dumneavoastră să acopere curse suplimentare fără burse de transport.",
        "Dacă vă transportați singuri marfa acum, putem prelua cursele care nu se potrivesc flotei dumneavoastră.",
    ],
}


def hook_snippets(lang="en"):
    """The default opening-line snippets for the given language (a fresh list)."""
    return list(HOOK_SNIPPETS["ro" if lang == "ro" else "en"])


def defaults(lang="en"):
    """{config_key: template_text} for every template key, in the given language."""
    idx = 1 if lang == "ro" else 0
    return {key: pair[idx] for key, pair in _TEMPLATE_KEYS.items()}


# Sandboxed: template text is user-authored (Settings page) and rendered on every
# send, so a payload like {{ cycler.__init__.__globals__ }} must not reach real
# attributes.
_JINJA_ENV = jinja2.sandbox.SandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)


def render(template_text, **kwargs):
    """Renders Jinja2 template text. Raises jinja2.TemplateError on a broken template."""
    return _JINJA_ENV.from_string(template_text).render(**kwargs)
