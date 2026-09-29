"""Agent 1 - Email Priority Agent.

For every unread email:
  1. Rule check (fast, free): sender lists in Settings, "no-reply" senders, Gmail's
     Social / Promotions tabs.
  2. Meeting keyword check: keywords from meetings in the last 7 days (agents/linker.py).
  3. LLM check: priority, category, reason, deadline and a draft reply (structured JSON).
  4. Save the result in email_analysis. A meeting link makes the email High and adds the
     label "Connected to meeting". The email now shows on the High or Low page.

The agent never sends anything by itself. The user always clicks Send.
"""

import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import linker
from app.config import get_settings
from app.models import ActivityLog, Email, EmailAnalysis
from app.services import mail_client, tasks
from app.services.app_settings import get_app_settings
from app.services.llm_client import LLMError, ask, ask_json
from app.services.notify import notify

log = logging.getLogger(__name__)
PROMPT = (Path(__file__).parent.parent / "prompts" / "email_priority.txt").read_text("utf-8")

Category = Literal[
    "Client", "Partner", "Product", "Internal", "Meeting-related", "Social", "Newsletter", "Other"
]


class EmailDecision(BaseModel):
    """What the LLM returns for one email."""

    priority: Literal["High", "Low"]
    category: Category
    reason: str = Field(description="One short sentence that explains the priority.")
    language: Literal["ar", "en", "mixed"]
    needs_reply: bool
    deadline: str = Field(description="YYYY-MM-DD if the email asks for a date, else empty")
    draft_reply: str


@dataclass
class SyncResult:
    fetched: int = 0
    new: int = 0
    analyzed: int = 0
    high: int = 0
    low: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class SyncProgress:
    """What the running sync is doing now - shown live next to the Refresh button."""

    running: bool = False
    stage: str = ""  # "fetching" (reading Gmail) / "analyzing" / "done"
    to_analyze: int = 0
    result: SyncResult = field(default_factory=SyncResult)
    error: str = ""
    finished_at: datetime | None = None


# Only one sync at a time (the background job and the Refresh button can overlap).
_sync_lock = threading.Lock()
progress = SyncProgress()

NO_REPLY = re.compile(r"^(no-?reply|do-?not-?reply|notifications?|mailer-daemon|bounce)", re.I)
ARABIC = re.compile(r"[؀-ۿ]")


def _domain_in(domain: str, domains: list[str]) -> bool:
    """True if domain is in the list, or is a sub-domain of one (mail.facebook.com)."""
    domain = domain.lower()
    return any(domain == d.lower() or domain.endswith("." + d.lower()) for d in domains if d)


def _guess_language(text: str) -> str:
    return "ar" if ARABIC.search(text) else "en"


def rule_check(email: Email, high_domains: list[str], low_domains: list[str]) -> str | None:
    """Return "High", "Low", or None when the rules cannot decide."""
    if _domain_in(email.sender_domain, high_domains):
        return "High"
    if _domain_in(email.sender_domain, low_domains):
        return "Low"
    if NO_REPLY.match(email.sender.split("@", 1)[0]):
        return "Low"
    if {"CATEGORY_SOCIAL", "CATEGORY_PROMOTIONS"} & set(email.labels or []):
        return "Low"
    return None


def _low_by_rule(email: Email) -> EmailAnalysis:
    labels = set(email.labels or [])
    social = "CATEGORY_SOCIAL" in labels or email.sender_domain.endswith(
        ("facebook.com", "facebookmail.com", "meta.com", "instagram.com", "linkedin.com", "x.com")
    )
    return EmailAnalysis(
        email_id=email.id,
        priority="Low",
        category="Social" if social else "Newsletter",
        reason="Sender matches a Low rule (social, newsletter or no-reply sender).",
        draft_reply="",
        reply_status="No reply needed",
        decided_by="rule",
    )


def _email_for_llm(email: Email) -> str:
    limit = get_settings().email_max_chars_for_llm
    body = email.body or ""
    if len(body) > limit:
        body = body[:limit] + "\n[... the rest of this long email was cut ...]"
    return (
        f"<email>\nFrom: {email.sender_name} <{email.sender}>\n"
        f"Date: {email.received_at:%Y-%m-%d %H:%M}\nSubject: {email.subject}\n\n{body}\n</email>"
    )


def _parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def analyze_email(
    db: Session,
    email: Email,
    fixed_priority: str | None = None,
    links: list[linker.LinkCandidate] | None = None,
) -> EmailAnalysis:
    """Ask the LLM for priority, category, reason and a draft reply. Saves the result.

    `links` = recent meetings this email is connected to. Their notes help the draft reply.
    After the LLM decides, the link makes the email High (see linker.save_links).
    """
    prompt = f"Today is {date.today():%Y-%m-%d}.\n\n{_email_for_llm(email)}"
    if fixed_priority:
        prompt += (
            f"\n\nThe user's sender rules say this email is {fixed_priority} priority. "
            "Use that priority."
        )
    if links:
        prompt += (
            "\n\nThis email seems connected to a recent meeting of the user. Use the meeting "
            "notes when they help the reply (for example what was decided).\n"
            + linker.meeting_context(links)
        )
    result = ask_json(prompt, EmailDecision, system=PROMPT, max_tokens=4000, effort="medium")
    d = result.data
    priority = fixed_priority or d.priority

    analysis = EmailAnalysis(
        email_id=email.id,
        priority=priority,
        category=d.category,
        reason=d.reason,
        draft_reply=d.draft_reply if d.needs_reply else "",
        reply_status="Draft ready" if d.needs_reply and d.draft_reply else "No reply needed",
        decided_by="rule" if fixed_priority else "llm",
        deadline=_parse_date(d.deadline),
    )
    email.language = d.language
    db.add(analysis)
    email.analysis = analysis
    if links:
        linker.save_links(db, email, links)
    if analysis.priority == "High" and analysis.deadline:
        tasks.create_from_email(db, email)  # a High email with a date -> Daily Tasks
    db.add(
        ActivityLog(
            agent="email",
            action="analyze",
            details={
                "email_id": email.id,
                "priority": analysis.priority,
                "meeting_ids": [c.meeting.id for c in links or []],
                "model": result.model,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            },
        )
    )
    db.commit()
    return analysis


def analyze_pending(db: Session, result: SyncResult | None = None) -> SyncResult:
    """Give a priority to every unread email that has none yet."""
    result = result or SyncResult()
    settings = get_app_settings(db)
    pending = db.scalars(
        select(Email)
        .where(Email.is_read.is_(False), ~Email.analysis.has())
        .order_by(Email.received_at.desc())
    ).all()
    if progress.running:
        progress.to_analyze = len(pending)

    for email in pending:
        decision = rule_check(email, settings.high_domains, settings.low_domains)
        try:
            if decision == "Low":
                analysis = _low_by_rule(email)
                email.language = _guess_language(email.subject + email.body)
                db.add(analysis)
                db.commit()
            else:
                links = linker.find_links(db, email)
                analysis = analyze_email(db, email, fixed_priority=decision, links=links)
        except LLMError as e:
            db.rollback()
            result.errors.append(str(e))
            break  # same problem for every email (no key, rate limit ...), so stop here
        result.analyzed += 1
        if analysis.priority == "High":
            result.high += 1
        else:
            result.low += 1
    return result


def sync(db: Session, lock_held: bool = False) -> SyncResult:
    """Fetch unread emails from Gmail, save new ones, then analyze them.

    lock_held=True: the caller already took the sync lock (start_sync_in_background).
    """
    if not lock_held and not _sync_lock.acquire(blocking=False):
        return SyncResult(errors=["A sync is already running. Try again in a moment."])
    result = SyncResult()
    progress.running, progress.stage, progress.error = True, "fetching", ""
    progress.to_analyze, progress.result, progress.finished_at = 0, result, None
    try:
        max_results = get_settings().email_sync_max
        fetched = mail_client.fetch_unread(db, max_results=max_results)
        result.fetched = len(fetched)
        unread_ids = {f.provider_id for f in fetched}

        for f in fetched:
            email = db.scalar(select(Email).where(Email.provider_id == f.provider_id))
            if email is None:
                db.add(
                    Email(
                        provider_id=f.provider_id,
                        thread_id=f.thread_id,
                        message_id_header=f.message_id_header,
                        sender=f.sender,
                        sender_name=f.sender_name,
                        sender_domain=f.sender_domain,
                        subject=f.subject,
                        body=f.body,
                        received_at=f.received_at,
                        is_read=False,
                        labels=f.labels,
                    )
                )
                result.new += 1
            else:
                email.is_read = False
                email.labels = f.labels

        # We got every unread email, so the others in our database were read in Gmail.
        if len(fetched) < max_results:
            for email in db.scalars(select(Email).where(Email.is_read.is_(False))):
                if email.provider_id not in unread_ids:
                    email.is_read = True
        db.commit()

        progress.stage = "analyzing"
        analyze_pending(db, result)
        if result.high:
            n = result.high
            notify(db, "email", f"{n} new High email{'s' if n > 1 else ''}", link="/high")
        if result.errors:
            notify(db, "problem", "The Email agent could not analyze emails", result.errors[0])
        db.add(
            ActivityLog(
                agent="email",
                action="sync",
                details={k: v for k, v in result.__dict__.items() if k != "errors"},
            )
        )
        db.commit()
        return result
    except Exception as e:
        progress.error = str(e)
        raise
    finally:
        progress.running, progress.stage, progress.finished_at = False, "done", datetime.now()
        _sync_lock.release()


def start_sync_in_background() -> bool:
    """Start a sync in its own thread (the Refresh button). False if one is already running."""
    if not _sync_lock.acquire(blocking=False):
        return False
    # Mark it as running now, so the page never sees "not running" before the thread starts.
    progress.running, progress.stage, progress.error = True, "fetching", ""

    def run() -> None:
        from app.db import SessionLocal  # here, to keep this module free of app start-up code

        with SessionLocal() as db:
            try:
                sync(db, lock_held=True)
            except Exception:  # also kept in progress.error, so the page can show it
                log.exception("Email sync failed")

    threading.Thread(target=run, name="email-sync", daemon=True).start()
    return True


def regenerate_reply(db: Session, email: Email, note: str = "") -> str:
    """Write a new draft reply. `note` is an optional wish, like "shorter" or "in Arabic"."""
    prompt = (
        "Write a new draft reply to this email. Follow the draft reply rules. "
        "Return only the reply text, nothing else.\n\n" + _email_for_llm(email)
    )
    if email.analysis and email.analysis.draft_reply:
        prompt += f"\n\n<previous_draft>\n{email.analysis.draft_reply}\n</previous_draft>"
    if note.strip():
        prompt += f"\n\nThe user asks: {note.strip()}"
    result = ask(prompt, system=PROMPT, max_tokens=3000, effort="medium")
    return result.text.strip()


def mark_sent(email: Email, reply: str) -> None:
    if email.analysis:
        email.analysis.draft_reply = reply
        email.analysis.reply_status = "Sent"
        email.analysis.sent_at = datetime.now()
    email.is_read = True
