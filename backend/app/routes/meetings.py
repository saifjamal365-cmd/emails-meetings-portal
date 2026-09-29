"""Meeting endpoints: the meeting list, Refresh, one-click Summarize, uploads and past summaries."""

from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.agents import meeting_agent
from app.agents.meeting_agent import OutputLanguage
from app.db import DbSession
from app.models import ActivityLog, EmailMeetingLink, Meeting, MeetingSummary, Task
from app.services import google_client
from app.services.llm_client import LLMError

router = APIRouter(prefix="/meetings", tags=["meetings"])


class MeetingItem(BaseModel):
    id: int
    title: str
    date: datetime
    end_time: datetime | None
    platform: str
    owner: str | None
    attendees: list[str]
    transcript_status: str
    has_summary: bool
    overview: str | None


class SummaryOut(BaseModel):
    overview: str | None
    detected_language: str | None
    action_items: list[dict]
    decisions: list[str]
    risks: list[str]
    blockers: list[str]
    keywords: list[str]
    key_facts: list[str]
    output_language: str
    created_at: datetime


class LogOut(BaseModel):
    time: datetime
    action: str
    details: dict


class TaskOut(BaseModel):
    id: int
    title: str
    status: str
    due_date: str | None


class LinkedEmailOut(BaseModel):
    email_id: int
    sender: str
    subject: str
    priority: str | None
    matched_keywords: list[str]


class MeetingDetail(MeetingItem):
    transcript_text: str | None
    summary: SummaryOut | None
    logs: list[LogOut]  # "Integration logs"
    tasks: list[TaskOut]
    linked_emails: list[LinkedEmailOut]


def _item(m: Meeting) -> MeetingItem:
    return MeetingItem(
        id=m.id,
        title=m.title,
        date=m.date,
        end_time=m.end_time,
        platform=m.platform,
        owner=m.owner,
        attendees=m.attendees or [],
        transcript_status=m.transcript_status,
        has_summary=m.summary is not None,
        overview=m.summary.overview if m.summary else None,
    )


def _detail(db: DbSession, m: Meeting) -> MeetingDetail:
    logs = [
        LogOut(time=log.time, action=log.action, details=log.details)
        for log in db.scalars(
            select(ActivityLog)
            .where(ActivityLog.agent == "meeting")
            .order_by(ActivityLog.time.desc(), ActivityLog.id.desc())
            .limit(500)
        )
        if (log.details or {}).get("meeting_id") == m.id
    ]
    tasks = [
        TaskOut(
            id=t.id,
            title=t.title,
            status=t.status,
            due_date=t.due_date.isoformat() if t.due_date else None,
        )
        for t in db.scalars(
            select(Task).where(Task.source_type == "meeting", Task.source_id == m.id)
        )
    ]
    linked_emails = [
        LinkedEmailOut(
            email_id=link.email.id,
            sender=link.email.sender_name or link.email.sender,
            subject=link.email.subject,
            priority=link.email.analysis.priority if link.email.analysis else None,
            matched_keywords=link.matched_keywords or [],
        )
        for link in db.scalars(
            select(EmailMeetingLink).where(
                EmailMeetingLink.meeting_id == m.id, EmailMeetingLink.removed.is_not(True)
            )
        )
    ]
    s = m.summary
    return MeetingDetail(
        **_item(m).model_dump(),
        transcript_text=m.transcript_text,
        summary=SummaryOut(
            overview=s.overview,
            detected_language=s.detected_language,
            action_items=s.action_items or [],
            decisions=s.decisions or [],
            risks=s.risks or [],
            blockers=s.blockers or [],
            keywords=s.keywords or [],
            key_facts=s.key_facts or [],
            output_language=s.output_language,
            created_at=s.created_at,
        )
        if s
        else None,
        logs=logs,
        tasks=tasks,
        linked_emails=linked_emails,
    )


def _get(db: DbSession, meeting_id: int) -> Meeting:
    meeting = db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(404, "Meeting not found.")
    return meeting


@router.get("", response_model=list[MeetingItem])
def list_meetings(db: DbSession, q: str = "", summarized: bool = False) -> list[MeetingItem]:
    """All meetings, newest first. summarized=true -> the past summaries ("Legacy summaries")."""
    query = select(Meeting).outerjoin(MeetingSummary)
    if summarized:
        query = query.where(MeetingSummary.id.is_not(None))
    meetings = db.scalars(query.order_by(Meeting.date.desc()).limit(500)).all()

    # Search in Python: keywords are a JSON list (Arabic is stored escaped there).
    words = q.strip().lower()
    if words:

        def matches(m: Meeting) -> bool:
            s = m.summary
            texts = [m.title, m.transcript_text or ""]
            if s:
                texts += [s.overview or "", *(s.keywords or [])]
            return any(words in t.lower() for t in texts)

        meetings = [m for m in meetings if matches(m)]
    return [_item(m) for m in meetings[:200]]


@router.post("/refresh")
def refresh(db: DbSession) -> dict:
    """Find finished meetings in the calendar and download their transcripts."""
    try:
        result = meeting_agent.refresh(db)
    except google_client.GoogleNotConnected as e:
        raise HTTPException(409, str(e)) from e
    except Exception as e:
        raise HTTPException(502, f"Google error: {e}") from e
    return result.__dict__


class UploadBody(BaseModel):
    title: str
    date: datetime | None = None
    text: str


@router.post("/upload", response_model=MeetingDetail)
def upload(body: UploadBody, db: DbSession) -> MeetingDetail:
    try:
        meeting = meeting_agent.add_uploaded(db, body.title, body.date or datetime.now(), body.text)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _detail(db, meeting)


class RecorderStatus(BaseModel):
    running: bool
    meeting_id: int | None
    title: str
    started_at: datetime | None
    until: datetime | None
    seconds: int
    error: str


def _recorder_status() -> RecorderStatus:
    s = meeting_agent.recorder.state
    return RecorderStatus(
        running=meeting_agent.recorder.running,
        meeting_id=s.meeting_id,
        title=s.title,
        started_at=s.started_at,
        until=s.until,
        seconds=s.seconds,
        error=s.error,
    )


@router.get("/recorder", response_model=RecorderStatus)
def recorder_status() -> RecorderStatus:
    return _recorder_status()


class RecordBody(BaseModel):
    title: str = ""
    minutes: int = 120  # safety stop if nobody clicks Stop


@router.post("/record", response_model=RecorderStatus)
def record_now(body: RecordBody, db: DbSession) -> RecorderStatus:
    """ "Record now": for a meeting that is not in the calendar. Stop it with /record/stop."""
    until = datetime.now() + timedelta(minutes=max(1, min(body.minutes, 480)))
    try:
        meeting_agent.start_recording(db, body.title, until)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(409, str(e)) from e
    return _recorder_status()


@router.post("/record/stop", response_model=RecorderStatus)
def stop_recording() -> RecorderStatus:
    """Stop now; the transcript and the summary are made in the background."""
    if meeting_agent.stop_recording() is None:
        raise HTTPException(409, "No recording is running.")
    return _recorder_status()


@router.get("/{meeting_id}", response_model=MeetingDetail)
def get_meeting(meeting_id: int, db: DbSession) -> MeetingDetail:
    return _detail(db, _get(db, meeting_id))


class SummarizeBody(BaseModel):
    output_language: OutputLanguage = "same"


@router.post("/{meeting_id}/summarize", response_model=MeetingDetail)
def summarize(meeting_id: int, body: SummarizeBody, db: DbSession) -> MeetingDetail:
    meeting = _get(db, meeting_id)
    try:
        meeting_agent.summarize(db, meeting, body.output_language)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except LLMError as e:
        raise HTTPException(502, str(e)) from e
    return _detail(db, meeting)
