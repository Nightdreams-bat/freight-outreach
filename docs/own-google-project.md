# Use your own Google project

## Why

Kairo signs in to Gmail and Google Calendar through a real Google OAuth flow, and
one of the scopes it requests (`gmail.readonly`, for reading lead replies) is a
*restricted* scope. Google caps a shared, unaudited OAuth app at 100 users and
expires every sign-in after 7 days unless the app passes a paid third-party
security audit (CASA).

Running Kairo against **your own** Google Cloud project sidesteps all of that:
you are the owner, so there is no user cap, no security audit, and — once you
publish the project to production — sign-ins no longer expire. Setup takes about
ten minutes and you only do it once.

## Steps

1. Go to `console.cloud.google.com` and create a new project (any name, e.g.
   "Kairo").
2. APIs & Services → Library → enable **Gmail API** and **Google Calendar API**.
3. APIs & Services → OAuth consent screen → choose **External** → fill in App
   name ("Kairo"), your email for support and developer contact → Save and
   continue through the steps.
4. Back on the OAuth consent screen, click **Publish app** → confirm "push to
   production". (This stops sign-ins from expiring every 7 days.)
5. APIs & Services → Credentials → **Create credentials → OAuth client ID** →
   Application type: **Desktop app** → Create → **Download JSON**.
6. In Kairo: Settings → Gmail account → **Advanced — use your own Google
   project** → upload that JSON file and click Save, then click **Connect
   Gmail**.
7. Google will warn "Google hasn't verified this app" — click **Advanced**, then
   **Go to Kairo (unsafe)**, then allow the permissions. This is expected for
   your own private app.

To go back to the bundled app later, use **Switch back to the shared app** in the
same panel.
