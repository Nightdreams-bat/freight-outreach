# End-to-end test results — 2026-08-27

Live test across two real Gmail accounts:

- **Sender** (connected in the app): `goddgd5@gmail.com`
- **Test lead** (recipient): `gargaundarius1@gmail.com` (and `gargaundarius1+bump@gmail.com` for the follow-up)
- Anthropic: real Claude Haiku 4.5 API calls
- Google Calendar: real event created and deleted on the sender's primary calendar

Everything below was exercised for real, not mocked.

## Connection diagnostics

| Check | Result |
|---|---|
| Business details | ✅ OK |
| Leads spreadsheet | ✅ OK |
| Gmail — account & token (send) | ✅ OK — authorised as goddgd5@gmail.com |
| Gmail — read replies (`gmail.readonly`) | ✅ OK |
| Google Calendar — free/busy | ✅ OK (after enabling the Calendar API in the Cloud project) |
| Anthropic API | ✅ OK — key valid, model reachable (after replacing the invalid key) |
| Scheduled tasks | ⚠️ not registered — optional; enable in Settings → Automation when going live |

## Feature tests

| # | Feature | What was tested | Result |
|---|---|---|---|
| 1 | **Cold intro send** | `goddgd5 → gargaundarius1`, real send | ✅ Delivered to **Inbox** (not spam). `ColdEmailSentAt` stamped, History row written, daily counter incremented. |
| 2 | **Priority score** | Computed from Notes keyword ("urgent lane") + phone | ✅ Correct score; Send queue ordered by it. |
| 3 | **Reply read + classify** | Real reply "Yes… Monday Sept 1 at 2 PM" → Claude | ✅ Classified `intent=yes`, proposed time parsed to `2026-09-01T14:00`, summary accurate. |
| 4 | **Calendar conflict check** | free/busy lookup on the proposed slot | ✅ Slot free → action `book`. |
| 5 | **Approval → booking** | Approved the queued action | ✅ Real Google Calendar event created (`Tue 1 Sept 14:00–14:30 GMT+3`), correct timezone. `MeetingDateTime` + `MeetingEventId` + `ReplyStatus=booked` written to the sheet. |
| 6 | **Confirmation email** | Sent on approval | ✅ Delivered to Inbox: "Confirmed - our call Tuesday, Sep 01 at 02:00 PM". |
| 7 | **Calendar invite email** | Google's own invitation | ✅ Delivered to Inbox with working Yes/No/Maybe buttons. |
| 8 | **24h reminder** | Meeting set ~24h out, reminder scan run | ✅ Delivered to Inbox: "Our call Friday, Aug 28 at 05:35 PM". `ReminderSentAt` stamped. |
| 9 | **Follow-up drip — send** | Lead cold-emailed 5 days ago, no reply → `--followup` | ✅ Nudge #1 delivered to Inbox. `FollowupStage=1`, `FollowupSentAt` stamped, History "followup" row. |
| 10 | **Follow-up drip — auto-stop** | Set a reply status on the lead, re-scan | ✅ Lead immediately dropped from the follow-up queue. Also stops on a booked meeting (verified separately). |
| 11 | **Blocklist** | Added a domain via the dashboard | ✅ Saved and shown; blocked addresses drop out of the send queue. |
| 12 | **Suppression** | `Suppressed=yes` on a lead | ✅ Excluded from every send flow. |
| 13 | **Dashboard "Run now" panel** | Triggered each action over HTTP | ✅ `idle → running → success` with a summary; log tail updates; a second job while one runs returns HTTP 409. |
| 14 | **Every dashboard route** | GET all 8 pages + `/run/status` + `/logs/tail` | ✅ All 200, no errors. |
| 15 | **Offline styling** | Dashboard with no internet | ✅ Fully styled (no CDN dependency). Light + dark. |
| 16 | **Automated test suite** | `pytest` | ✅ 188 passed (network-free). |

## Notes / things the client should know

- **A second, conflicting reply after a booking is not auto-rescheduled.** During the test a
  second reply ("let's do Friday 3pm") arrived after the meeting was already booked. The app
  correctly left it alone (the lead's status was already `booked`). If a lead reschedules by
  email after booking, that's handled manually — reply in Gmail and update `MeetingDateTime`
  in the sheet.
- **Emails landed in Inbox, not spam**, sending from a brand-new Gmail with no reputation.
  The 3-second gap between sends and the real `Date` / `Message-ID` headers the app sets are
  doing their job. Sending volume should still be ramped up gradually on a fresh account.
- **Two one-time Google Cloud steps** were needed and are now documented in `SETUP.md`:
  enable the **Google Calendar API** (separate from the Gmail API), and use a **valid
  Anthropic API key** from `console.anthropic.com` (not a Claude subscription).

## Cleanup done

Calendar event deleted, test spreadsheet removed, trackers cleared, `config.json` restored,
blocklist test entry removed. The test emails were left in the inbox as evidence — safe to
delete.
