"""Agent 1 - Email Priority Agent.

For every unread email:
  1. Rule check (fast, free), in this order:
       your Always High list -> High;  your Always Low list -> Low;
       a no-reply sender -> Low;  a reply in a conversation where you wrote -> High;
       a bulk or automatic email (List-Unsubscribe, Auto-Submitted ... headers) -> Low;
       someone you wrote to before (services/contacts.py) -> High;
       Gmail's Social / Promotions / Updates / Forums tab, not marked Important -> Low.
  2. Meeting keyword check: keywords from meetings in the last 7 days (agents/linker.py).
  3. LLM check: priority, category, reason, deadline and a draft reply (structured JSON).
     The LLM also gets the facts the portal found (only in Cc, Gmail Important ...).
  4. Save the result in email_analysis. A meeting link makes the email High and adds the
     label "Connected to meeting". The email now shows on the High or Low page.
  5. A sender you never wrote to who asks for money, bank details or a password gets a
     warning on the email.

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
from app.services import contacts, google_client, mail_client, tasks
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


BULK_REASONS = {
    "auto-submitted": "an automatic message",
    "list-unsubscribe": "a newsletter or mass email (it has an unsubscribe link)",
    "list-id": "sent to a mailing list",
    "precedence": "marked as bulk mail",
}
GMAIL_LOW_TABS = {
    "CATEGORY_SOCIAL": "Social",
    "CATEGORY_PROMOTIONS": "Promotions",
    "CATEGORY_UPDATES": "Updates",
    "CATEGORY_FORUMS": "Forums",
}
SOCIAL_DOMAINS = (
    "facebook.com", "facebookmail.com", "meta.com", "instagram.com", "linkedin.com", "x.com"
)  # fmt: skip

# Asks for money, bank details or a password (English and Arabic).
PAYMENT_ASK = re.compile(
    r"bank (account|details)|\biban\b|swift code|wire transfer|"
    r"transfer (the )?(money|amount|funds|payment)|payment link|pay now|gift cards?|"
    r"password|verify your account|login details|card number|"
    r"حساب ?بنكي|الحساب البنكي|حسابكم البنكي|آيبان|ايبان|تحويل (مبلغ|المبلغ|الأموال)|حوالة|"
    r"كلمة المرور|كلمة السر|بطاقات? هدايا|رقم البطاقة",
    re.I,
)
PAYMENT_WARNING = (
    "You never wrote to this sender, and the email asks for money, bank details or a "
    "password. Check that it is real before you do anything."
)


@dataclass
class RuleDecision:
    priority: str  # "High" / "Low"
    reason: str


def _sender_in(email: Email, entries: list[str]) -> str | None:
    """The list entry that matches the sender: a full address (sara@acme.com), or a domain
    that also matches its sub-domains (facebook.com -> mail.facebook.com). None if none."""
    address, domain = email.sender.lower(), email.sender_domain.lower()
    for entry in entries:
        entry = entry.lower()
        if not entry:
            continue
        if "@" in entry:
            if address == entry:
                return entry
        elif domain == entry or domain.endswith("." + entry):
            return entry
    return None


def _guess_language(text: str) -> str:
    return "ar" if ARABIC.search(text) else "en"


def rule_check(
    email: Email,
    high_list: list[str],
    low_list: list[str],
    known_contacts: set[str] | frozenset[str] = frozenset(),
) -> RuleDecision | None:
    """The free checks, in order. None when the rules cannot decide (then the LLM decides)."""
    labels = set(email.labels or [])
    if match := _sender_in(email, high_list):
        return RuleDecision("High", f"The sender ({match}) is in your Always High list.")
    if match := _sender_in(email, low_list):
        return RuleDecision("Low", f"The sender ({match}) is in your Always Low list.")
    if NO_REPLY.match(email.sender.split("@", 1)[0]):
        return RuleDecision("Low", "Sent from a no-reply address, so no answer is expected.")
    if email.in_my_thread:
        return RuleDecision("High", "A reply in a conversation where you already wrote.")
    if email.bulk_header:
        return RuleDecision("Low", f"The email is {BULK_REASONS[email.bulk_header]}.")
    if email.sender.lower() in known_contacts:
        return RuleDecision("High", "You wrote to this person before.")
    tabs = [name for label, name in GMAIL_LOW_TABS.items() if label in labels]
    if tabs and "IMPORTANT" not in labels:
        return RuleDecision(
            "Low", f"Gmail put it in the {tabs[0]} tab and did not mark it Important."
        )
    return None


def facts(email: Email, me: str, known_contacts: set[str]) -> list[str]:
    """What the portal knows about this email, for the LLM (it cannot see the headers)."""
    result = []
    labels = set(email.labels or [])
    if "IMPORTANT" in labels:
        result.append("Gmail marked this email Important.")
    tabs = [name for label, name in GMAIL_LOW_TABS.items() if label in labels]
    if tabs:
        result.append(f"Gmail put it in the {tabs[0]} tab.")
    to, cc = email.to_addrs or [], email.cc_addrs or []
    if me and (to or cc):
        others = len(set(to + cc) - {me})
        if me in to:
            result.append(
                f"Sent to the user and {others} other people."
                if others
                else "Sent only to the user."
            )
        elif me in cc:
            result.append("The user is only in Cc, not in To.")
        else:
            result.append("The user is not in To or Cc (Bcc or a mailing list).")
    if known_contacts and email.sender.lower() not in known_contacts:
        result.append("The user never wrote to this sender.")
    return result


def payment_warning(email: Email, known_contacts: set[str]) -> str:
    """A warning when a sender I never wrote to asks for money, bank details or a password.
    Before the Sent folder is read (no contacts yet), every sender counts as unknown."""
    if email.in_my_thread or email.sender.lower() in known_contacts:
        return ""
    if PAYMENT_ASK.search(f"{email.subject}\n{email.body}"):
        return PAYMENT_WARNING
    return ""


def _low_by_rule(email: Email, reason: str) -> EmailAnalysis:
    labels = set(email.labels or [])
    social = "CATEGORY_SOCIAL" in labels or email.sender_domain.endswith(SOCIAL_DOMAINS)
    return EmailAnalysis(
        email_id=email.id,
        priority="Low",
        category="Social" if social else "Newsletter",
        reason=reason,
        draft_reply="",
        reply_status="No reply needed",
        decided_by="rule",
    )


def remember_sender(db: Session, email: Email, priority: str) -> str:
    """The user moved an email and said "always": put the sender's address in that list and
    take it out of the other one. Returns the address."""
    settings = get_app_settings(db)
    address = email.sender.lower()
    high, low = list(settings.high_domains or []), list(settings.low_domains or [])
    keep, drop = (high, low) if priority == "High" else (low, high)
    if address not in keep:
        keep.append(address)
    if address in drop:
        drop.remove(address)
    settings.high_domains, settings.low_domains = high, low  # new lists, so the JSON is saved
    return address


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
    rule: RuleDecision | None = None,
    links: list[linker.LinkCandidate] | None = None,
    known_facts: list[str] | None = None,
    warning: str = "",
) -> EmailAnalysis:
    """Ask the LLM for priority, category, reason and a draft reply. Saves the result.

    `rule` = a rule already decided the priority (the LLM writes the rest).
    `links` = recent meetings this email is connected to. Their notes help the draft reply.
    After the LLM decides, the link makes the email High (see linker.save_links).
    `known_facts` = what the portal found (see facts()); `warning` = see payment_warning().
    """
    prompt = f"Today is {date.today():%Y-%m-%d}.\n\n{_email_for_llm(email)}"
    if known_facts:
        prompt += "\n\nFacts the portal found:\n" + "\n".join(f"- {f}" for f in known_facts)
    if warning:
        prompt += (
            "\n\nSafety: the user never wrote to this sender, and the email asks for money, "
            "bank details or a password. Do not promise any payment in the draft reply."
        )
    if rule:
        prompt += (
            f"\n\nThe portal's rules say this email is {rule.priority} priority "
            f"({rule.reason}) Use that priority. In reason, say what the email asks for."
        )
    if links:
        prompt += (
            "\n\nThis email seems connected to a recent meeting of the user. Use the meeting "
            "notes when they help the reply (for example what was decided).\n"
            + linker.meeting_context(links)
        )
    result = ask_json(prompt, EmailDecision, system=PROMPT, max_tokens=4000, effort="medium")
    d = result.data

    analysis = EmailAnalysis(
        email_id=email.id,
        priority=rule.priority if rule else d.priority,
        category=d.category,
        reason=f"{rule.reason} {d.reason}" if rule else d.reason,
        draft_reply=d.draft_reply if d.needs_reply else "",
        reply_status="Draft ready" if d.needs_reply and d.draft_reply else "No reply needed",
        decided_by="rule" if rule else "llm",
        deadline=_parse_date(d.deadline),
        warning=warning,
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
    known_contacts = contacts.known(db)
    me = (google_client.account(db) or ("", ""))[0].lower()
    pending = db.scalars(
        select(Email)
        .where(Email.is_read.is_(False), ~Email.analysis.has())
        .order_by(Email.received_at.desc())
    ).all()
    if progress.running:
        progress.to_analyze = len(pending)

    for email in pending:
        rule = rule_check(email, settings.high_domains, settings.low_domains, known_contacts)
        try:
            if rule and rule.priority == "Low":
                analysis = _low_by_rule(email, rule.reason)
                email.language = _guess_language(email.subject + email.body)
                db.add(analysis)
                db.commit()
            else:
                links = linker.find_links(db, email)
                in_high_list = _sender_in(email, settings.high_domains)
                analysis = analyze_email(
                    db,
                    email,
                    rule=rule,
                    links=links,
                    known_facts=facts(email, me, known_contacts),
                    warning="" if in_high_list else payment_warning(email, known_contacts),
                )
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


def _in_my_thread(db: Session, f: mail_client.FetchedEmail) -> bool:
    """Did I already write in this conversation? Gmail's thread id is the id of the first
    message, so the first message of a thread needs no extra Gmail call."""
    if not f.thread_id or f.thread_id == f.provider_id:
        return False
    try:
        return mail_client.thread_has_my_message(db, f.thread_id)
    except Exception:
        log.warning("Could not read Gmail thread %s", f.thread_id, exc_info=True)
        return False


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
                        to_addrs=f.to_addrs,
                        cc_addrs=f.cc_addrs,
                        bulk_header=f.bulk_header,
                        in_my_thread=_in_my_thread(db, f),
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

        contacts.refresh_if_due(db)  # once a day: who I wrote to (Gmail Sent folder)
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
