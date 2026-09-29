"""Database tables - the 8 tables from the plan, plus the activity log.

Lists (keywords, action items, attendees ...) are stored as JSON columns for now.
"""

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _now() -> datetime:
    return datetime.now()


class Email(Base):
    __tablename__ = "emails"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(255), unique=True)  # id in Gmail / Outlook
    thread_id: Mapped[str | None] = mapped_column(String(255))  # to reply in the same thread
    message_id_header: Mapped[str | None] = mapped_column(String(1000))  # "Message-ID" header
    sender: Mapped[str] = mapped_column(String(320))  # email address only
    sender_name: Mapped[str] = mapped_column(String(320), default="")
    sender_domain: Mapped[str] = mapped_column(String(255), index=True)
    subject: Mapped[str] = mapped_column(String(1000), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    received_at: Mapped[datetime] = mapped_column(DateTime)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    labels: Mapped[list[str]] = mapped_column(JSON, default=list)  # Gmail labels
    language: Mapped[str | None] = mapped_column(String(10))  # "ar", "en"

    analysis: Mapped["EmailAnalysis | None"] = relationship(back_populates="email")
    meeting_links: Mapped[list["EmailMeetingLink"]] = relationship(back_populates="email")


class EmailAnalysis(Base):
    __tablename__ = "email_analysis"

    id: Mapped[int] = mapped_column(primary_key=True)
    email_id: Mapped[int] = mapped_column(ForeignKey("emails.id"), unique=True)
    priority: Mapped[str] = mapped_column(String(10))  # "High" / "Low"
    category: Mapped[str] = mapped_column(String(50))
    reason: Mapped[str] = mapped_column(Text, default="")
    draft_reply: Mapped[str] = mapped_column(Text, default="")
    # New -> Draft ready -> Edited -> Sent / Skipped
    reply_status: Mapped[str] = mapped_column(String(20), default="New")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    # "rule" / "llm" / "user" / "meeting" (made High by a meeting link)
    decided_by: Mapped[str] = mapped_column(String(10), default="llm")
    deadline: Mapped[date | None] = mapped_column(Date)  # if the email asks for a date
    analyzed_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    email: Mapped[Email] = relationship(back_populates="analysis")


class OAuthToken(Base):
    """A connected account (Google now; Microsoft/Zoom later). The token is encrypted."""

    __tablename__ = "oauth_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(20), unique=True)  # "google"
    account_email: Mapped[str] = mapped_column(String(320), default="")
    account_name: Mapped[str | None] = mapped_column(String(320))
    scopes: Mapped[list[str] | None] = mapped_column(JSON)  # permissions the user allowed
    token_encrypted: Mapped[str] = mapped_column(Text)
    connected_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(20))  # "meet" / "zoom" / "teams" / "upload"
    # Calendar event id + start time (a repeating meeting has one row per day).
    provider_meeting_id: Mapped[str] = mapped_column(String(255), unique=True)
    title: Mapped[str] = mapped_column(String(500))
    date: Mapped[datetime] = mapped_column(DateTime)
    end_time: Mapped[datetime | None] = mapped_column(DateTime)
    meeting_code: Mapped[str | None] = mapped_column(String(50))  # "abc-mnop-xyz"
    conference_record: Mapped[str | None] = mapped_column(String(255))  # Meet API record name
    owner: Mapped[str | None] = mapped_column(String(320))  # organizer
    attendees: Mapped[list[str]] = mapped_column(JSON, default=list)
    transcript_text: Mapped[str | None] = mapped_column(Text)
    # "ready" / "waiting" (meeting ended, transcript not ready yet) / "none"
    # "recording" / "transcribing" (recorded on this PC) -> "ready"
    transcript_status: Mapped[str] = mapped_column(String(20), default="waiting")
    # The people who joined the Google Meet call (Meet API): helps to name the voices
    participants: Mapped[list[str] | None] = mapped_column(JSON, default=list)

    summary: Mapped["MeetingSummary | None"] = relationship(back_populates="meeting")


class MeetingSummary(Base):
    __tablename__ = "meeting_summaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"), unique=True)
    overview: Mapped[str | None] = mapped_column(Text)  # 3-5 sentence summary
    detected_language: Mapped[str | None] = mapped_column(String(10))  # ar / en / mixed
    action_items: Mapped[list[dict]] = mapped_column(JSON, default=list)
    decisions: Mapped[list[str]] = mapped_column(JSON, default=list)
    risks: Mapped[list[str]] = mapped_column(JSON, default=list)
    blockers: Mapped[list[str]] = mapped_column(JSON, default=list)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    key_facts: Mapped[list[str] | None] = mapped_column(JSON, default=list)  # budget, amounts
    # Who each separated voice is: {"label": "Speaker 1", "name": "Omar", "clue": "..."}
    speakers: Mapped[list[dict] | None] = mapped_column(JSON, default=list)
    output_language: Mapped[str] = mapped_column(String(10), default="same")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    meeting: Mapped[Meeting] = relationship(back_populates="summary")


class EmailMeetingLink(Base):
    __tablename__ = "email_meeting_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    email_id: Mapped[int] = mapped_column(ForeignKey("emails.id"))
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"))
    matched_keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    score: Mapped[float] = mapped_column(Float, default=0)
    confirmed_by_llm: Mapped[bool] = mapped_column(Boolean, default=False)
    # The priority before the link made it High, so removing a wrong link can undo it.
    previous_priority: Mapped[str | None] = mapped_column(String(10))
    removed: Mapped[bool | None] = mapped_column(Boolean, default=False)  # user said "wrong link"
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=_now)

    email: Mapped[Email] = relationship(back_populates="meeting_links")
    meeting: Mapped["Meeting"] = relationship()


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    source_type: Mapped[str] = mapped_column(String(20), default="manual")  # email/meeting/manual
    source_id: Mapped[int | None] = mapped_column(Integer)
    owner: Mapped[str | None] = mapped_column(String(320))
    due_date: Mapped[date | None] = mapped_column(Date)
    priority: Mapped[str] = mapped_column(String(10), default="Medium")  # High/Medium/Low
    status: Mapped[str] = mapped_column(String(20), default="To do")  # To do/In progress/Done
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)  # when it became "Done"


class DailyReport(Base):
    """The morning plan and the end-of-day summary (one of each per day)."""

    __tablename__ = "daily_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    type: Mapped[str] = mapped_column(String(10))  # "morning" / "evening"
    content: Mapped[str] = mapped_column(Text)
    edited_by_user: Mapped[bool] = mapped_column(Boolean, default=False)
    made_by: Mapped[str | None] = mapped_column(String(10))  # "llm" / "basic" (no LLM)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=_now)


class AppSettings(Base):
    """One row of user settings (the Settings page)."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    high_domains: Mapped[list[str]] = mapped_column(JSON, default=list)
    low_domains: Mapped[list[str]] = mapped_column(
        JSON,
        default=lambda: [
            "facebook.com",
            "facebookmail.com",
            "meta.com",
            "instagram.com",
            "linkedin.com",
            "x.com",
        ],
    )
    stop_words: Mapped[list[str]] = mapped_column(
        JSON, default=lambda: ["meeting", "update", "project", "اجتماع", "مشروع"]
    )
    auto_summarize: Mapped[bool] = mapped_column(Boolean, default=False)
    # Record meetings from the calendar on this computer (mic + speakers) and transcribe them
    auto_record: Mapped[bool | None] = mapped_column(Boolean, default=False)
    # Names and words that come up in meetings (people, clients, projects, terms):
    # hints for Whisper and the summary, so they are heard and written correctly.
    meeting_words: Mapped[list[str] | None] = mapped_column(JSON, default=list)
    connected_accounts: Mapped[list[str]] = mapped_column(JSON, default=list)


class ActivityLog(Base):
    """Integration logs: what each agent did, and every LLM call."""

    __tablename__ = "activity_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    time: Mapped[datetime] = mapped_column(DateTime, default=_now)
    agent: Mapped[str] = mapped_column(String(50))
    action: Mapped[str] = mapped_column(String(100))
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class Notification(Base):
    """Something the user should see: new High emails, a summary made, a plan ready, a problem."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    time: Mapped[datetime] = mapped_column(DateTime, default=_now)
    kind: Mapped[str] = mapped_column(String(20))  # "email" / "meeting" / "plan" / "problem"
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str | None] = mapped_column(String(300))  # a page in the portal, e.g. "/high"
    read: Mapped[bool] = mapped_column(Boolean, default=False)
