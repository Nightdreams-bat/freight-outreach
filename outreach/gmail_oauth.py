import json

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from outreach.credentials import get_oauth_token, set_oauth_token
from outreach.paths import CLIENT_SECRET_PATH

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",       # read lead replies
    "https://www.googleapis.com/auth/calendar.events",      # create meeting invites
    "https://www.googleapis.com/auth/calendar.freebusy",    # check the client's calendar for conflicts
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]


def run_oauth_flow():
    """Opens the real Google sign-in/consent screen in the default browser.

    Returns the connected Gmail address. Raises FileNotFoundError if
    client_secret.json hasn't been set up yet (see README).
    """
    if not CLIENT_SECRET_PATH.exists():
        raise FileNotFoundError(
            f"{CLIENT_SECRET_PATH} not found. This is the one-time Google Cloud OAuth "
            f"Client file - see README for how to create it."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
    creds = flow.run_local_server(port=0)

    # Look up the authorized address so the user never has to type it themselves.
    # (Gmail's own getProfile needs a broader scope than gmail.send grants - the
    # lightweight userinfo endpoint is the right tool for "who just signed in".)
    userinfo = build("oauth2", "v2", credentials=creds).userinfo().get().execute()
    gmail_address = userinfo["email"]

    set_oauth_token(gmail_address, creds.to_json())
    return gmail_address


def get_credentials(gmail_address):
    """Loads the stored token for gmail_address, refreshing it if expired."""
    token_json = get_oauth_token(gmail_address)
    creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        set_oauth_token(gmail_address, creds.to_json())

    return creds
