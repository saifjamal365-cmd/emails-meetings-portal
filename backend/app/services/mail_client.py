"""Gmail API client: read unread emails, send replies, mark as read and archive.
Also reads the Sent folder (who I wrote to) and whether I already wrote in a conversation.

The Google login itself lives in services/google_client.py.
"""

import base64
import html
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.utils import getaddresses, parseaddr, parsedate_to_datetime

from sqlalchemy.orm import Session

from app.models import Email
from app.services import google_client


def _gmail(db: Session):
    return google_client.service(db, "gmail", "v1")


# ---- Reading emails ----------------------------------------------------------


@dataclass
class FetchedEmail:
    provider_id: str
    thread_id: str
    message_id_header: str
    sender: str
    sender_name: str
    subject: str
    body: str
    received_at: datetime
    labels: list[str] = field(default_factory=list)
    to_addrs: list[str] = field(default_factory=list)
    cc_addrs: list[str] = field(default_factory=list)
    bulk_header: str = ""

    @property
    def sender_domain(self) -> str:
        return self.sender.rsplit("@", 1)[-1].lower() if "@" in self.sender else ""


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def _html_to_text(text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", text)).strip()


def _body(payload: dict) -> str:
    """Prefer the plain-text part; fall back to the HTML part converted to text."""
    plain: list[str] = []
    html_parts: list[str] = []

    def walk(part: dict) -> None:
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data and mime == "text/plain":
            plain.append(_decode(data))
        elif data and mime == "text/html":
            html_parts.append(_decode(data))
        for sub in part.get("parts", []) or []:
            walk(sub)

    walk(payload)
    if plain:
        return "\n".join(plain).strip()
    return _html_to_text("\n".join(html_parts))


def _addresses(value: str) -> list[str]:
    return [a.lower() for _, a in getaddresses([value]) if "@" in a]


def bulk_header(headers: dict[str, str]) -> str:
    """The first header that marks bulk or automatic mail, or "".

    Auto-Submitted is the standard for automatic mail (RFC 3834); List-Unsubscribe and
    List-Id are on newsletters and mailing lists (RFC 2369, RFC 2919); Precedence is old
    but still common.
    """
    if headers.get("auto-submitted", "no").strip().lower() != "no":
        return "auto-submitted"
    for name in ("list-unsubscribe", "list-id"):
        if headers.get(name):
            return name
    if headers.get("precedence", "").strip().lower() in ("bulk", "list", "junk"):
        return "precedence"
    return ""


def _parse(message: dict) -> FetchedEmail:
    headers = {h["name"].lower(): h["value"] for h in message["payload"].get("headers", [])}
    name, address = parseaddr(headers.get("from", ""))
    try:
        received = parsedate_to_datetime(headers["date"]).astimezone().replace(tzinfo=None)
    except (KeyError, TypeError, ValueError):
        received = datetime.fromtimestamp(int(message.get("internalDate", "0")) / 1000)
    return FetchedEmail(
        provider_id=message["id"],
        thread_id=message.get("threadId", ""),
        message_id_header=headers.get("message-id", ""),
        sender=address.lower(),
        sender_name=name,
        subject=headers.get("subject", ""),
        body=_body(message["payload"]),
        received_at=received,
        labels=message.get("labelIds", []),
        to_addrs=_addresses(headers.get("to", "")),
        cc_addrs=_addresses(headers.get("cc", "")),
        bulk_header=bulk_header(headers),
    )


def fetch_unread(db: Session, max_results: int = 50) -> list[FetchedEmail]:
    """Unread emails in the inbox, newest first."""
    gmail = _gmail(db)
    listing = (
        gmail.users()
        .messages()
        .list(userId="me", q="is:unread in:inbox", maxResults=max_results)
        .execute()
    )
    result = []
    for item in listing.get("messages", []):
        message = gmail.users().messages().get(userId="me", id=item["id"], format="full").execute()
        result.append(_parse(message))
    return result


def thread_has_my_message(db: Session, thread_id: str) -> bool:
    """True if I already wrote in this Gmail conversation (a message there has SENT)."""
    thread = _gmail(db).users().threads().get(userId="me", id=thread_id, format="minimal").execute()
    return any("SENT" in m.get("labelIds", []) for m in thread.get("messages", []))


def sent_recipients(
    db: Session, since: datetime | None, max_results: int = 300
) -> list[tuple[str, datetime]]:
    """(address, sent time) for each To/Cc person in my Sent folder. First time: 1 year."""
    since = since or datetime.now() - timedelta(days=365)
    gmail = _gmail(db)
    query = f"in:sent after:{int(since.timestamp())}"
    result: list[tuple[str, datetime]] = []
    listing = gmail.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    for item in listing.get("messages", []):
        message = (
            gmail.users()
            .messages()
            .get(userId="me", id=item["id"], format="metadata", metadataHeaders=["To", "Cc"])
            .execute()
        )
        headers = {h["name"].lower(): h["value"] for h in message["payload"].get("headers", [])}
        sent_at = datetime.fromtimestamp(int(message.get("internalDate", "0")) / 1000)
        for address in _addresses(headers.get("to", "")) + _addresses(headers.get("cc", "")):
            result.append((address, sent_at))
    return result


# ---- Actions -----------------------------------------------------------------


def send_reply(db: Session, email: Email, reply_text: str) -> None:
    """Send a reply in the same Gmail thread, then mark the original as read."""
    message = MIMEText(reply_text, "plain", "utf-8")
    message["To"] = email.sender
    subject = email.subject or ""
    message["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    if email.message_id_header:
        message["In-Reply-To"] = email.message_id_header
        message["References"] = email.message_id_header
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    gmail = _gmail(db)
    body: dict = {"raw": raw}
    if email.thread_id:
        body["threadId"] = email.thread_id
    gmail.users().messages().send(userId="me", body=body).execute()
    mark_read(db, [email.provider_id])


def mark_read(db: Session, provider_ids: list[str]) -> None:
    if provider_ids:
        _gmail(db).users().messages().batchModify(
            userId="me", body={"ids": provider_ids, "removeLabelIds": ["UNREAD"]}
        ).execute()


def archive(db: Session, provider_ids: list[str]) -> None:
    """Remove from the inbox (the email is kept in Gmail under All Mail)."""
    if provider_ids:
        _gmail(db).users().messages().batchModify(
            userId="me", body={"ids": provider_ids, "removeLabelIds": ["INBOX", "UNREAD"]}
        ).execute()
