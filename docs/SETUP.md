# Kairo — full setup guide

This is the complete walkthrough, written so someone who has never seen the tool
can get it running from nothing. It has two parts:

- **Part A — one-time developer setup** (Google Cloud + Anthropic). Done once, by
  whoever installs the tool. The client never touches this.
- **Part B — the client's setup**, entirely on the dashboard's **Settings** page.

At the end there is a **Troubleshooting** section covering every error the
Diagnostics page can show.

---

## Part A — one-time developer setup

### A1. Install (source checkout only — skip if you have the `.exe`)

```
pip install -r requirements.txt
python -m kairo          # starts the dashboard
```

For the packaged build, see `BUILD.md`.

### A2. Google Cloud project

Everything the tool does with email and calendars goes through Google's APIs, so
Google needs to know about the app. This is a free, one-time setup.

1. Go to <https://console.cloud.google.com/> and **create a project** (any name,
   e.g. "Kairo").

2. **Enable both APIs** the tool uses — they are separate and *both* are
   required:
   - Gmail API → <https://console.cloud.google.com/apis/library/gmail.googleapis.com>
   - Google Calendar API → <https://console.cloud.google.com/apis/library/calendar-json.googleapis.com>

   Click **Enable** on each. If you only enable Gmail, the reply-handling
   booking flow fails with *"Google Calendar API has not been used in project …
   before or it is disabled"* (see Troubleshooting).

3. **OAuth consent screen** (APIs & Services → OAuth consent screen):
   - User type: **External**.
   - Fill in the app name, your support email, developer email. Nothing else is
     required.
   - **Publishing status: set it to "In production" / Published.** You do *not*
     need to complete Google's verification for your own account's use — the
     "unverified app" warning screen stays (just click through it, see step 7
     below), but **refresh tokens stop expiring**. In "Testing" mode, refresh
     tokens die after 7 days, so the sending account silently stops working every
     week and every scheduled run fails until someone clicks "Connect Gmail"
     again. Publishing removes that. (If you keep it in "Testing", add **every**
     Gmail address that will ever click "Connect Gmail" as a Test user, or
     sign-in fails with *"Access blocked: … has not completed the Google
     verification process"*.)
   - **Test users:** add **every Gmail address that will ever click "Connect
     Gmail"** — the sending account, and yours if different. Without this, sign-in
     fails with *"Access blocked: … has not completed the Google verification
     process"*.

4. **Scopes** — the app requests these automatically; you don't list them
   anywhere, but you should know what the consent screen will show the user:
   | Scope | Why |
   |---|---|
   | `gmail.send` | send the cold / follow-up / reminder emails |
   | `gmail.readonly` | read lead replies |
   | `calendar.events` | create the meeting invite when a booking is approved |
   | `calendar.freebusy` | check the calendar for conflicts before proposing times |
   | `openid`, `userinfo.email` | learn which address just signed in |

5. **Credentials → Create credentials → OAuth client ID:**
   - Application type: **Desktop app**.
   - Download the JSON, rename it to **`client_secret.json`**, and put it:
     - source checkout: in the project root (next to `kairo/`)
     - packaged build: next to `Kairo.exe`

### A3. Anthropic API key (only needed for reply handling)

Reply classification (yes / no / maybe / question, and pulling a proposed time
out of a reply) uses Claude. This needs an **API key**, which is **not** the same
as a Claude.ai subscription — it is billed separately, pay-as-you-go.

1. Go to <https://console.anthropic.com/settings/keys> and **Create Key**. Copy
   the whole string — it starts `sk-ant-api03-` and is about 100 characters.
2. Go to **Billing** → add a payment method / buy credits. Minimum top-up is $5.
3. Cost in practice: the tool uses **Claude Haiku 4.5** ($1 per million input
   tokens, $5 per million output). One reply classified ≈ **$0.001**. A $5
   top-up covers thousands of replies.

The key is entered by the client on the Settings page (Part B); it is stored in
the Windows Credential Manager, never in a file, and never displayed again.

**Data processing note.** When reply handling is on, the **full text of every
inbound reply** — names, phone numbers, quoted rates, signatures — is sent to
Anthropic to be classified. Anthropic acts as a data processor. Review and sign
[Anthropic's DPA](https://www.anthropic.com/legal/commercial-terms) and look at
their [zero-retention](https://privacy.anthropic.com/) options before enabling
this. **The operator must disclose this processing in their own privacy notice.**
The always-on keyword opt-out scan (below) does not use any LLM and sends nothing
to Anthropic.

---

## Part B — client setup (Settings page)

Start the tool (`python -m kairo`, or double-click `Kairo.exe`). The
browser opens `http://127.0.0.1:5000` — localhost only, nothing is exposed to the
network. The dashboard shows a short checklist until the essentials are filled in.

Go to **Settings** and do these, top to bottom:

1. **Excel file** — click **Browse…** and point it at your leads spreadsheet
   anywhere on the PC. If you don't have one yet, leave it: a blank
   `clients.xlsx` with the standard columns is created on first send.

2. **Lead spreadsheet columns** — the app reads your headers and guesses which
   column is Name / Company / Email / Phone / Priority. It handles things like
   *Surname*, *Organisation*, *E-mail Address*, a split first/last name. Check the
   guesses; use the dropdowns to fix any it got wrong. A row with only an email
   still works (the name is derived from the address, the company from the
   domain).

3. **Gmail account** — click **Connect Gmail**. The real Google sign-in page
   opens. Sign in with the **sending account** (a dedicated Gmail is fine — it
   does not have to be a personal address; it does have to be Gmail or Google
   Workspace, **not** Outlook / Proton / etc., because the tool uses Google's
   APIs). On the "Google hasn't verified this app" screen click **Advanced → Go
   to … (unsafe)** — that is expected for a testing-mode app that is yours.
   Tick **all** the permission boxes and click **Continue**. Nothing is typed
   into this app — no password ever touches it.

4. **Follow-up drip** (optional) — turn on to send up to 3 spaced nudges to cold
   leads who haven't replied. Default cadence: 3, 7, 14 days after the cold
   intro; the last one is a soft "I'll stop here". It stops the instant a lead
   replies or a meeting is booked.

5. **Reply handling & auto-scheduling** (optional) — paste the **Anthropic API
   key** (Part A3) into the box, then scroll to the bottom and click **Save
   settings**. The label changes to "configured". Then click **Enable automatic
   reply checking**.

6. **Business details** — your name, company, phone, one-line pitch, and
   **postal address**. The address is **required by anti-spam law on every
   commercial email** (street, city, country is enough); it is added to the
   signature footer of every message and Diagnostics warns until it is set. The
   From-line preview updates live.

7. **Email templates** — the actual emails, written by you. Every "Send now" uses
   exactly this text with each lead's details merged in. Variables and the
   `{% if phone %}…{% endif %}` skip-a-blank-line trick are documented right on
   the page.

8. **Sending limits** — the numeric caps (daily send cap, reminder window, etc.),
   each with an explanation of what it protects against.

### Verify it all works

Go to **Diagnostics** (left menu, or the button on Settings). It actively tests
every connection and shows OK / WARN / FAIL per check. **WARN** = optional and
not configured (e.g. no Anthropic key, automation off). **FAIL** = something that
will stop a real send or booking — fix those before going live. Re-run it after
any change.

---

## Compliance & deliverability

Cold email is regulated — CAN-SPAM (US), GDPR / PECR (EU). **The operator is
responsible for compliance, not this tool.**

What the tool now does for you:

- Every email carries a **postal address** and a **one-line opt-out** ("Reply
  STOP …") in the footer, plus `List-Unsubscribe` headers. Set the address in
  **Settings → Business details**.
- On every reminder run, an **always-on keyword scan** (no Anthropic key needed,
  works with reply handling off) reads inbound replies and **permanently
  blocklists** any lead who writes "stop / unsubscribe / remove me / opt out" in
  English or Romanian. That address is added to the disallowed list and never
  contacted again by any batch (cold, follow-up or reminder).

What you must still do yourself:

- **Do not send cold outreach from a consumer `@gmail.com` account.** It breaks
  Google's bulk-sender and consumer-Gmail policies and can get the account
  suspended without warning. Use **Google Workspace on a domain you own**.
- Configure **SPF, DKIM and DMARC** for that domain (your DNS provider + the
  Workspace admin console).
- **Keep the daily send cap low and warm the mailbox up:** ~20/day for the first
  week on a new account, then raise it gradually over 2–3 weeks while watching
  bounce and spam-complaint rates. Pause on any spike.
- Make sure you have a lawful basis to contact each lead, and honour opt-outs
  across every future spreadsheet import.

---

## How the app runs day to day

- **Dashboard → Run now** buttons trigger cold / follow-ups / reminders / reply
  scan on demand, with a live status line and a log tail.
- **Send** page lists everything queued and lets you send a batch.
- **Replies** page shows drafted actions from lead replies — **nothing is sent or
  booked until you click Approve**.
- **Automation** (Settings) registers a Windows scheduled task that runs the
  reminder + follow-up scan every couple of hours, whether or not the dashboard
  is open. Reply checking is a second task, enabled separately.

---

## Troubleshooting (Diagnostics failures)

### "Google Calendar — FAIL: … Calendar API has not been used in project … or it is disabled"

The Google Calendar API is not enabled in your Cloud project. It is separate from
the Gmail API. Fix:
<https://console.cloud.google.com/apis/library/calendar-json.googleapis.com> →
**Enable**. Wait 2–3 minutes for it to propagate, then re-run Diagnostics. You do
**not** need to reconnect Gmail for this one (the scopes were already granted).

### "Gmail — read replies — FAIL" or "Google Calendar — FAIL: insufficient scope"

The connected token doesn't carry the newer permissions (this happens if the
account was first connected when the app only asked for `gmail.send`). Fix: click
**Connect Gmail** again and approve all the boxes.

### "Anthropic API — FAIL: 401 … invalid x-api-key"

Anthropic rejected the key. This is the key itself, not a billing problem
(insufficient credit gives a different message). Causes, in order of likelihood:
- The key was **saved but a character was dropped/added** on paste. Re-copy the
  whole string.
- You **created a new key and deleted the old one**, but the app still has the
  old (now dead) one — the app only picks up a new key when you paste it and
  click **Save settings** (the button at the very bottom of the page, not "Save
  follow-up settings").
- The key belongs to a different Anthropic org than the one with credit.

Fix: <https://console.anthropic.com/settings/keys> → create a fresh key → copy
all of it → **Settings → Anthropic API key** → paste → **Save settings** at the
bottom → re-run Diagnostics.

### "Anthropic API — FAIL: 400 … credit balance is too low"

The key is valid but the org has no credits. **Billing** → buy credits (min $5).

### "Access blocked: Kairo has not completed the Google verification process" during Connect Gmail

The account you're signing in with isn't on the test-user list. Add it: Google
Cloud Console → APIs & Services → OAuth consent screen → **Test users → Add
users**. Then retry.

### "client_secret.json not found"

The one-time Google OAuth file (Part A2, step 5) isn't in place. Source checkout:
project root. Packaged build: next to `Kairo.exe`.

### The dashboard looks unstyled / plain text

Old cached version. The current build ships all styling locally and needs no
internet — hard-refresh the page (Ctrl+F5). If it persists, the `.exe` build is
stale; rebuild per `BUILD.md`.

### "Your leads spreadsheet is locked"

`clients.xlsx` is open in Excel. Close it there and reload the page.
