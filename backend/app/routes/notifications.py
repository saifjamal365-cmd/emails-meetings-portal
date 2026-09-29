"""Notifications for the bell in the side menu."""

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select, update

from app.db import DbSession
from app.models import Notification

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: int
    time: datetime
    kind: str
    title: str
    body: str
    link: str | None
    read: bool


class NotificationList(BaseModel):
    unread: int
    items: list[NotificationOut]


@router.get("", response_model=NotificationList)
def list_notifications(db: DbSession) -> NotificationList:
    items = db.scalars(select(Notification).order_by(Notification.id.desc()).limit(30)).all()
    unread = db.scalar(
        select(func.count()).select_from(Notification).where(Notification.read.is_(False))
    )
    return NotificationList(
        unread=unread,
        items=[
            NotificationOut(
                id=n.id,
                time=n.time,
                kind=n.kind,
                title=n.title,
                body=n.body or "",
                link=n.link,
                read=n.read,
            )
            for n in items
        ],
    )


@router.post("/read-all")
def read_all(db: DbSession) -> dict:
    db.execute(update(Notification).where(Notification.read.is_(False)).values(read=True))
    db.commit()
    return {"ok": True}


@router.post("/{notification_id}/read")
def read_one(notification_id: int, db: DbSession) -> dict:
    item = db.get(Notification, notification_id)
    if item is None:
        raise HTTPException(404, "Notification not found.")
    item.read = True
    db.commit()
    return {"ok": True}
