"""Create in-portal notifications (the bell in the side menu)."""

from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Notification

Kind = Literal["email", "meeting", "plan", "problem"]


def notify(
    db: Session, kind: Kind, title: str, body: str = "", link: str | None = None
) -> Notification | None:
    """Add a notification. The caller commits.

    A notification with the same title that is still unread is not added again, so a
    repeated problem (like an expired Google login) does not fill the list.
    """
    duplicate = db.scalar(
        select(Notification).where(Notification.title == title, Notification.read.is_(False))
    )
    if duplicate:
        return None
    item = Notification(kind=kind, title=title, body=body, link=link)
    db.add(item)
    db.flush()  # so the duplicate check above sees it before the caller commits
    return item
