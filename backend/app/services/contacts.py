"""Contacts: the people I wrote to, read from my Gmail Sent folder once a day.

An email from a contact is High without asking the LLM ("You wrote to this person before").
Only addresses, counts and dates are kept, on this computer.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Contact
from app.services import google_client, mail_client
from app.services.app_settings import get_app_settings

log = logging.getLogger(__name__)
REFRESH_EVERY = timedelta(hours=24)


def known(db: Session) -> set[str]:
    return set(db.scalars(select(Contact.address)))


def refresh(db: Session) -> int:
    """Add the people from new Sent emails. Returns how many new contacts were added."""
    settings = get_app_settings(db)
    me = (google_client.account(db) or ("", ""))[0].lower()
    since = settings.contacts_synced_at
    started = datetime.now()
    added = 0
    for address, sent_at in mail_client.sent_recipients(db, since):
        if address == me:
            continue
        contact = db.scalar(select(Contact).where(Contact.address == address))
        if contact is None:
            db.add(Contact(address=address, sent_count=1, last_sent_at=sent_at))
            db.flush()
            added += 1
        else:
            contact.sent_count += 1
            if contact.last_sent_at is None or sent_at > contact.last_sent_at:
                contact.last_sent_at = sent_at
    settings.contacts_synced_at = started
    db.commit()
    return added


def refresh_if_due(db: Session) -> None:
    """Refresh once a day. A problem here never stops the email sync."""
    last = get_app_settings(db).contacts_synced_at
    if last and datetime.now() - last < REFRESH_EVERY:
        return
    try:
        added = refresh(db)
        log.info("Contacts refreshed: %s new", added)
    except Exception:
        db.rollback()
        log.exception("Could not read the Sent folder for contacts")
