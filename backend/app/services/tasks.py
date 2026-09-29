"""Small helpers for tasks, shared by the agents and the API."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Email, Meeting, Task

STATUSES = ("To do", "In progress", "Done")
PRIORITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}


def create_from_email(db: Session, email: Email) -> tuple[Task, bool]:
    """A "Reply to ..." task for an email. Returns (task, created). Never makes a duplicate."""
    existing = db.scalar(
        select(Task).where(Task.source_type == "email", Task.source_id == email.id)
    )
    if existing:
        return existing, False
    a = email.analysis
    task = Task(
        title=f"Reply to: {email.subject or '(no subject)'}",
        description=f"From {email.sender_name or email.sender}. {a.reason if a else ''}".strip(),
        source_type="email",
        source_id=email.id,
        due_date=a.deadline if a else None,
        priority=a.priority if a else "Medium",
    )
    db.add(task)
    db.flush()
    return task, True


def set_status(task: Task, status: str) -> None:
    if status not in STATUSES:
        raise ValueError(f"Status must be one of: {', '.join(STATUSES)}")
    if status == "Done" and task.status != "Done":
        task.completed_at = datetime.now()
    elif status != "Done":
        task.completed_at = None
    task.status = status


def source_label(db: Session, task: Task) -> str | None:
    """Where the task came from, e.g. "Email: Contract renewal" or "Meeting: Weekly Sales"."""
    if task.source_type == "email" and task.source_id:
        email = db.get(Email, task.source_id)
        return f"Email: {email.subject}" if email else None
    if task.source_type == "meeting" and task.source_id:
        meeting = db.get(Meeting, task.source_id)
        return f"Meeting: {meeting.title}" if meeting else None
    return None
