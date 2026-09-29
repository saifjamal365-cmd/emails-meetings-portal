"""Daily Planner: turns what the two agents found into a plan for the day.

- Morning plan ("What to do today"): late tasks, tasks due today, High emails waiting for a
  reply, and recent meeting decisions, risks and blockers.
- End-of-day summary ("Day summary"): tasks done and still open, replies sent, High emails
  still waiting, meetings and decisions, and what to move to tomorrow.

1. collect_facts() reads the database (no LLM) and writes the facts as text.
2. The LLM turns the facts into a short, ordered plan.
3. If the LLM is not available, the facts themselves are saved as a basic plan.
The user can edit the text afterwards.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DailyReport, Email, EmailAnalysis, Meeting, MeetingSummary, Task
from app.services.llm_client import LLMError, ask
from app.services.notify import notify
from app.services.tasks import PRIORITY_ORDER, source_label

PROMPT = (Path(__file__).parent.parent / "prompts" / "daily_planner.txt").read_text("utf-8")

Kind = Literal["morning", "evening"]
OPEN_EMAIL = ("New", "Draft ready", "Edited", "No reply needed")

INSTRUCTIONS = {
    "morning": (
        "Write the START-OF-DAY plan with these sections:\n"
        "## Top priorities - 3 to 5 numbered items, the most urgent first, each with a short "
        "reason (late, due today, a client waits...)\n"
        "## Emails to answer - High emails waiting for a reply\n"
        "## Also today - other open tasks worth doing today\n"
        "## Watch out - risks and blockers from recent meetings"
    ),
    "evening": (
        "Write the END-OF-DAY summary with these sections:\n"
        "## Done today - finished tasks and replies sent\n"
        "## Still open - important tasks and High emails that are still waiting\n"
        "## Meetings - today's meetings and their key decisions\n"
        "## For tomorrow - 3 to 5 numbered items to start with tomorrow, most urgent first"
    ),
}


@dataclass
class PlanResult:
    report: DailyReport
    warning: str | None = None  # e.g. "LLM not available, basic plan saved"


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, datetime.min.time())
    return start, start + timedelta(days=1)


def _task_line(db: Session, t: Task, day: date) -> str:
    parts = [t.title, f"priority {t.priority}"]
    if t.due_date:
        late = (day - t.due_date).days
        parts.append(f"LATE by {late} day(s)" if late > 0 else f"due {t.due_date:%Y-%m-%d}")
    label = source_label(db, t)
    if label:
        parts.append(f"from {label}")
    return "- " + " | ".join(parts)


def _open_tasks(db: Session) -> list[Task]:
    rows = db.scalars(select(Task).where(Task.status != "Done")).all()
    return sorted(
        rows,
        key=lambda t: (t.due_date or date.max, PRIORITY_ORDER.get(t.priority, 1), t.created_at),
    )


def _waiting_high_emails(db: Session) -> list[Email]:
    return list(
        db.scalars(
            select(Email)
            .join(EmailAnalysis)
            .where(
                EmailAnalysis.priority == "High",
                Email.is_read.is_(False),
                EmailAnalysis.reply_status.in_(OPEN_EMAIL),
            )
            .order_by(EmailAnalysis.deadline.is_(None), EmailAnalysis.deadline)
        )
    )


def _email_line(e: Email) -> str:
    a = e.analysis
    parts = [f"{e.sender_name or e.sender}: {e.subject}"]
    if a.deadline:
        parts.append(f"deadline {a.deadline:%Y-%m-%d}")
    active = [link for link in e.meeting_links if not link.removed]
    if active:
        parts.append(f"about the meeting {active[0].meeting.title}")
    parts.append(a.reason)
    return "- " + " | ".join(parts)


def _meeting_lines(meetings: list[Meeting], with_risks: bool) -> list[str]:
    lines = []
    for m in meetings:
        s = m.summary
        lines.append(f"- {m.title} ({m.date:%Y-%m-%d %H:%M}): {s.overview}")
        lines += [f"    decision: {d}" for d in s.decisions]
        if with_risks:
            lines += [f"    risk: {r}" for r in s.risks]
            lines += [f"    blocker: {b}" for b in s.blockers]
    return lines


def _section(title: str, lines: list[str]) -> list[str]:
    return [f"## {title}", *lines, ""] if lines else []


def collect_facts(db: Session, kind: Kind, day: date) -> str:
    """The day's facts as text (also used as the basic plan when there is no LLM)."""
    start, end = _day_bounds(day)
    open_tasks = _open_tasks(db)
    late = [t for t in open_tasks if t.due_date and t.due_date < day]
    due_today = [t for t in open_tasks if t.due_date == day]
    other = [t for t in open_tasks if t not in late and t not in due_today][:10]
    emails = _waiting_high_emails(db)
    lines = [f"Date: {day:%A %d %B %Y}", ""]

    if kind == "morning":
        since = start - timedelta(days=2)
        meetings = db.scalars(
            select(Meeting)
            .join(MeetingSummary)
            .where(Meeting.date >= since, Meeting.date < end)
            .order_by(Meeting.date)
        ).all()
        lines += _section("Late tasks", [_task_line(db, t, day) for t in late])
        lines += _section("Tasks due today", [_task_line(db, t, day) for t in due_today])
        lines += _section("High emails waiting for a reply", [_email_line(e) for e in emails])
        lines += _section("Other open tasks", [_task_line(db, t, day) for t in other])
        lines += _section("Recent meetings", _meeting_lines(list(meetings), with_risks=True))
        yesterday = db.scalar(
            select(DailyReport).where(
                DailyReport.date == day - timedelta(days=1), DailyReport.type == "evening"
            )
        )
        if yesterday:
            lines += _section("Yesterday's end-of-day summary", yesterday.content.splitlines())
    else:
        done = db.scalars(
            select(Task).where(Task.completed_at >= start, Task.completed_at < end)
        ).all()
        sent = db.scalars(
            select(Email)
            .join(EmailAnalysis)
            .where(EmailAnalysis.sent_at >= start, EmailAnalysis.sent_at < end)
        ).all()
        meetings = db.scalars(
            select(Meeting)
            .join(MeetingSummary)
            .where(Meeting.date >= start, Meeting.date < end)
            .order_by(Meeting.date)
        ).all()
        lines += _section("Tasks done today", [f"- {t.title}" for t in done])
        lines += _section(
            "Replies sent today", [f"- {e.sender_name or e.sender}: {e.subject}" for e in sent]
        )
        lines += _section(
            "Open tasks (late and due first)",
            [_task_line(db, t, day) for t in [*late, *due_today, *other]],
        )
        lines += _section("High emails still waiting", [_email_line(e) for e in emails])
        lines += _section("Today's meetings", _meeting_lines(list(meetings), with_risks=False))

    if len(lines) == 2:
        lines.append("Nothing to report: no open tasks, no waiting High emails, no meetings.")
    return "\n".join(lines).strip()


def generate(db: Session, kind: Kind, day: date | None = None) -> PlanResult:
    """Make (or make again) the morning plan or the day summary, and save it."""
    day = day or date.today()
    facts = collect_facts(db, kind, day)
    warning = None
    try:
        result = ask(
            f"{INSTRUCTIONS[kind]}\n\n<facts>\n{facts}\n</facts>",
            system=PROMPT,
            max_tokens=3000,
            effort="low",
        )
        content, made_by = result.text.strip(), "llm"
    except LLMError as e:
        content, made_by = facts, "basic"
        warning = f"The LLM is not available ({e}) - a basic plan was saved instead."

    report = db.scalar(select(DailyReport).where(DailyReport.date == day, DailyReport.type == kind))
    if report is None:
        report = DailyReport(date=day, type=kind, content="")
        db.add(report)
    report.content = content
    report.made_by = made_by
    report.edited_by_user = False
    report.created_at = datetime.now()
    db.commit()
    return PlanResult(report=report, warning=warning)


def scheduled(db: Session, kind: Kind) -> PlanResult | None:
    """The 8:00 / 18:00 job: make today's report, but never replace one that already exists."""
    exists = db.scalar(
        select(DailyReport).where(DailyReport.date == date.today(), DailyReport.type == kind)
    )
    if exists:
        return None
    result = generate(db, kind)
    title = "Your morning plan is ready" if kind == "morning" else "Your day summary is ready"
    notify(db, "plan", f"{title} ({date.today():%d %b})", result.warning or "", link="/tasks")
    db.commit()
    return result
