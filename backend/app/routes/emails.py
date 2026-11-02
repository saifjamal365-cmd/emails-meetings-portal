"""Email endpoints: lists for the High / Low / All pages, and the reply actions."""

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from app.agents import email_agent, linker
from app.db import DbSession
from app.models import ActivityLog, Email, EmailAnalysis, EmailMeetingLink
from app.services import google_client, mail_client, tasks
from app.services.llm_client import LLMError

router = APIRouter(prefix="/emails", tags=["emails"])

CLOSED = ("Sent", "Skipped", "Archived")


class EmailItem(BaseModel):
    id: int
    sender: str
    sender_name: str
    subject: str
    snippet: str
    received_at: datetime
    is_read: bool
    language: str | None
    priority: str | None
    category: str | None
    reason: str | None
    reply_status: str | None
    deadline: date | None
    warning: str = ""  # a sender I never wrote to asks for money, bank details or a password
    meeting_label: str | None = None  # "Weekly Sales Meeting (25 Sep)" if linked


class MeetingLinkOut(BaseModel):
    id: int
    meeting_id: int
    label: str
    matched_keywords: list[str]
    score: float
    confirmed_by_llm: bool


class EmailDetail(EmailItem):
    body: str
    draft_reply: str
    meeting_links: list[MeetingLinkOut]


def _item(email: Email, detail: bool = False) -> EmailItem:
    a = email.analysis
    data = {
        "id": email.id,
        "sender": email.sender,
        "sender_name": email.sender_name,
        "subject": email.subject,
        "snippet": " ".join((email.body or "").split())[:160],
        "received_at": email.received_at,
        "is_read": email.is_read,
        "language": email.language,
        "priority": a.priority if a else None,
        "category": a.category if a else None,
        "reason": a.reason if a else None,
        "reply_status": a.reply_status if a else None,
        "deadline": a.deadline if a else None,
        "warning": (a.warning or "") if a else "",
    }
    links = linker.active_links(email)
    if links:
        data["meeting_label"] = linker.label(links[0].meeting)
    if detail:
        return EmailDetail(
            **data,
            body=email.body,
            draft_reply=a.draft_reply if a else "",
            meeting_links=[
                MeetingLinkOut(
                    id=link.id,
                    meeting_id=link.meeting_id,
                    label=linker.label(link.meeting),
                    matched_keywords=link.matched_keywords or [],
                    score=link.score,
                    confirmed_by_llm=bool(link.confirmed_by_llm),
                )
                for link in links
            ],
        )
    return EmailItem(**data)


def _get(db: DbSession, email_id: int) -> Email:
    email = db.get(Email, email_id)
    if email is None:
        raise HTTPException(404, "Email not found.")
    return email


def _gmail_error(e: Exception) -> HTTPException:
    if isinstance(e, google_client.GoogleNotConnected):
        return HTTPException(409, str(e))
    return HTTPException(502, f"Gmail error: {e}")


# ---- Lists -------------------------------------------------------------------


@router.get("", response_model=list[EmailItem])
def list_emails(
    db: DbSession,
    view: Literal["high", "low", "all"] = "all",
    q: str = "",
    show_done: bool = False,
) -> list[EmailItem]:
    query = select(Email).outerjoin(EmailAnalysis)
    if view in ("high", "low"):
        query = query.where(EmailAnalysis.priority == view.capitalize())
        if not show_done:
            query = query.where(Email.is_read.is_(False), EmailAnalysis.reply_status.not_in(CLOSED))
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.where(
            or_(Email.subject.ilike(like), Email.sender.ilike(like), Email.body.ilike(like))
        )
    if view == "high":
        # Emails with a deadline first (soonest first), then newest.
        query = query.order_by(
            EmailAnalysis.deadline.is_(None), EmailAnalysis.deadline, Email.received_at.desc()
        )
    else:
        query = query.order_by(Email.received_at.desc())
    return [_item(e) for e in db.scalars(query.limit(200)).all()]


@router.get("/counts")
def counts(db: DbSession) -> dict:
    def open_count(priority: str) -> int:
        return db.scalar(
            select(func.count())
            .select_from(EmailAnalysis)
            .join(Email)
            .where(
                EmailAnalysis.priority == priority,
                Email.is_read.is_(False),
                EmailAnalysis.reply_status.not_in(CLOSED),
            )
        )

    today = datetime.combine(date.today(), datetime.min.time())
    return {
        "unread": db.scalar(
            select(func.count()).select_from(Email).where(Email.is_read.is_(False))
        ),
        "high": open_count("High"),
        "low": open_count("Low"),
        "sent_today": db.scalar(
            select(func.count())
            .select_from(EmailAnalysis)
            .where(EmailAnalysis.reply_status == "Sent", EmailAnalysis.sent_at >= today)
        ),
    }


# ---- Sync --------------------------------------------------------------------


def _sync_status() -> dict:
    p = email_agent.progress
    return {
        "running": p.running,
        "stage": p.stage,
        "to_analyze": p.to_analyze,
        "error": p.error,
        "finished_at": p.finished_at,
        **p.result.__dict__,
    }


@router.post("/sync")
def sync(db: DbSession) -> dict:
    """The Refresh button: start reading Gmail + analyzing in the background.

    It returns at once; the page asks GET /emails/sync-status for the progress.
    """
    if google_client.account(db) is None:
        raise HTTPException(409, "Google is not connected. Open Settings and click Connect Google.")
    email_agent.start_sync_in_background()
    return {**_sync_status(), "running": True}


@router.get("/sync-status")
def sync_status() -> dict:
    return _sync_status()


@router.get("/{email_id}", response_model=EmailDetail)
def get_email(email_id: int, db: DbSession) -> EmailDetail:
    return _item(_get(db, email_id), detail=True)


# ---- Actions on one email ----------------------------------------------------


class DraftBody(BaseModel):
    draft_reply: str


class RegenerateBody(BaseModel):
    note: str = ""


class SendBody(BaseModel):
    reply: str


class PriorityBody(BaseModel):
    priority: Literal["High", "Low"]
    remember: bool = False  # also put the sender in the Always High / Always Low list


def _analysis(db: DbSession, email: Email) -> EmailAnalysis:
    if email.analysis is None:
        email.analysis = EmailAnalysis(email_id=email.id, priority="High", category="Other")
        db.flush()
    return email.analysis


@router.put("/{email_id}/draft", response_model=EmailDetail)
def save_draft(email_id: int, body: DraftBody, db: DbSession) -> EmailDetail:
    email = _get(db, email_id)
    a = _analysis(db, email)
    a.draft_reply = body.draft_reply
    a.reply_status = "Edited"
    db.commit()
    return _item(email, detail=True)


@router.post("/{email_id}/regenerate", response_model=EmailDetail)
def regenerate(email_id: int, body: RegenerateBody, db: DbSession) -> EmailDetail:
    email = _get(db, email_id)
    try:
        reply = email_agent.regenerate_reply(db, email, body.note)
    except LLMError as e:
        raise HTTPException(502, str(e)) from e
    a = _analysis(db, email)
    a.draft_reply = reply
    a.reply_status = "Draft ready"
    db.commit()
    return _item(email, detail=True)


@router.post("/{email_id}/send", response_model=EmailDetail)
def send(email_id: int, body: SendBody, db: DbSession) -> EmailDetail:
    email = _get(db, email_id)
    if not body.reply.strip():
        raise HTTPException(400, "The reply is empty.")
    try:
        mail_client.send_reply(db, email, body.reply)
    except Exception as e:
        raise _gmail_error(e) from e
    _analysis(db, email)
    email_agent.mark_sent(email, body.reply)
    db.add(ActivityLog(agent="email", action="reply_sent", details={"email_id": email.id}))
    db.commit()
    return _item(email, detail=True)


@router.post("/{email_id}/priority", response_model=EmailDetail)
def change_priority(email_id: int, body: PriorityBody, db: DbSession) -> EmailDetail:
    email = _get(db, email_id)
    a = _analysis(db, email)
    a.priority = body.priority
    a.decided_by = "user"
    a.reason = f"Changed to {body.priority} by you."
    if body.remember:
        address = email_agent.remember_sender(db, email, body.priority)
        a.reason += f" New emails from {address} go to {body.priority} too (Settings)."
    db.commit()
    return _item(email, detail=True)


@router.post("/{email_id}/skip", response_model=EmailDetail)
def skip(email_id: int, db: DbSession) -> EmailDetail:
    email = _get(db, email_id)
    _analysis(db, email).reply_status = "Skipped"
    db.commit()
    return _item(email, detail=True)


@router.post("/{email_id}/task")
def add_task(email_id: int, db: DbSession) -> dict:
    task, created = tasks.create_from_email(db, _get(db, email_id))
    db.commit()
    return {"task_id": task.id, "title": task.title, "created": created}


@router.delete("/{email_id}/links/{link_id}", response_model=EmailDetail)
def remove_meeting_link(email_id: int, link_id: int, db: DbSession) -> EmailDetail:
    """The user says "this email is not about that meeting"."""
    email = _get(db, email_id)
    link = db.get(EmailMeetingLink, link_id)
    if link is None or link.email_id != email.id:
        raise HTTPException(404, "Link not found.")
    linker.remove_link(db, link)
    db.commit()
    return _item(email, detail=True)


# ---- Bulk actions (Low page) -------------------------------------------------


class BulkBody(BaseModel):
    ids: list[int]
    action: Literal["mark_read", "archive"]


@router.post("/bulk")
def bulk(body: BulkBody, db: DbSession) -> dict:
    emails = db.scalars(select(Email).where(Email.id.in_(body.ids))).all()
    provider_ids = [e.provider_id for e in emails]
    try:
        if body.action == "archive":
            mail_client.archive(db, provider_ids)
        else:
            mail_client.mark_read(db, provider_ids)
    except Exception as e:
        raise _gmail_error(e) from e
    for email in emails:
        email.is_read = True
        if body.action == "archive":
            _analysis(db, email).reply_status = "Archived"
    db.commit()
    return {"updated": len(emails)}
