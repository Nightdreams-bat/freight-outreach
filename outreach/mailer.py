import base64
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from outreach.gmail_oauth import get_credentials

_UNSET = object()  # "caller didn't say" - distinct from an explicit None (= no header)


class Mailer:
    def __init__(self, gmail_address, sender_name=None, sender_company=None, retries=2, retry_delay=5):
        self.gmail_address = gmail_address
        self.sender_name = sender_name
        self.sender_company = sender_company
        self.retries = retries
        self.retry_delay = retry_delay

    def _from_header(self):
        if self.sender_name and self.sender_company:
            display_name = f"{self.sender_name} - {self.sender_company}"
        else:
            display_name = self.sender_name or self.sender_company or ""
        return formataddr((display_name, self.gmail_address)) if display_name else self.gmail_address

    def send(self, to_addr, subject, body, unsubscribe_mailto=_UNSET):
        # Default the one-click unsubscribe address to the sender's own mailbox;
        # pass unsubscribe_mailto=None to omit the headers entirely.
        if unsubscribe_mailto is _UNSET:
            unsubscribe_mailto = self.gmail_address

        msg = MIMEMultipart()
        msg["From"] = self._from_header()
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg["Reply-To"] = self.gmail_address
        # One-click list-unsubscribe (Gmail bulk-sender requirement / spam signal
        # when absent). Points at the sender's own mailbox with a parseable
        # subject - there is no hosted endpoint for this local tool.
        if unsubscribe_mailto:
            msg["List-Unsubscribe"] = f"<mailto:{unsubscribe_mailto}?subject=unsubscribe>"
            msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
        # A real mail client always sets these; their absence is itself a spam
        # signal, so we set them explicitly rather than leaving it to chance.
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain=self.gmail_address.split("@")[-1])
        msg.attach(MIMEText(body, "plain", "utf-8"))
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

        creds = get_credentials(self.gmail_address)
        service = build("gmail", "v1", credentials=creds)

        last_error = None
        for attempt in range(1, self.retries + 1):
            try:
                service.users().messages().send(userId="me", body={"raw": raw}).execute()
                return
            except HttpError as e:
                if e.resp.status in (400, 403, 404):
                    raise  # bad request / permissions / bad address - retrying won't help
                last_error = e
                if attempt < self.retries:
                    time.sleep(self.retry_delay)
        raise last_error
