"""Daily Tasks endpoints: the task board (add, edit, move, delete)."""

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.db import DbSession
from app.models import Task
from app.services import tasks as task_service

router = APIRouter(prefix="/tasks", tags=["tasks"])

Priority = Literal["High", "Medium", "Low"]
Status = Literal["To do", "In progress", "Done"]


class TaskOut(BaseModel):
    id: int
    title: str
    description: str
    notes: str
    owner: str | None
    due_date: date | None
    priority: str
    status: str
    source_type: str
    source_id: int | None
    source_label: str | None
    created_at: datetime
    completed_at: datetime | None


class TaskCreate(BaseModel):
    title: str = Field(min_length=1)
    description: str = ""
    notes: str = ""
    due_date: date | None = None
    priority: Priority = "Medium"


class TaskUpdate(BaseModel):
    """Only the fields that are sent are changed."""

    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    notes: str | None = None
    due_date: date | None = None
    priority: Priority | None = None
    status: Status | None = None


def _out(db: DbSession, t: Task) -> TaskOut:
    return TaskOut(
        id=t.id,
        title=t.title,
        description=t.description or "",
        notes=t.notes or "",
        owner=t.owner,
        due_date=t.due_date,
        priority=t.priority,
        status=t.status,
        source_type=t.source_type,
        source_id=t.source_id,
        source_label=task_service.source_label(db, t),
        created_at=t.created_at,
        completed_at=t.completed_at,
    )


def _get(db: DbSession, task_id: int) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(404, "Task not found.")
    return task


def _today_start() -> datetime:
    return datetime.combine(date.today(), datetime.min.time())


@router.get("", response_model=list[TaskOut])
def list_tasks(db: DbSession, all_done: bool = False) -> list[TaskOut]:
    """Open tasks, plus tasks done today (or every done task with all_done=true)."""
    query = select(Task)
    if not all_done:
        query = query.where(or_(Task.status != "Done", Task.completed_at >= _today_start()))
    rows = db.scalars(query).all()
    rows = sorted(
        rows,
        key=lambda t: (
            t.due_date or date.max,
            task_service.PRIORITY_ORDER.get(t.priority, 1),
            t.created_at,
        ),
    )
    return [_out(db, t) for t in rows]


@router.get("/counts")
def counts(db: DbSession) -> dict:
    today = date.today()

    def count(*where) -> int:
        return db.scalar(select(func.count()).select_from(Task).where(*where))

    return {
        "open": count(Task.status != "Done"),
        "due_today": count(Task.status != "Done", Task.due_date == today),
        "late": count(Task.status != "Done", Task.due_date < today),
        "done_today": count(Task.completed_at >= _today_start()),
    }


@router.post("", response_model=TaskOut)
def create(body: TaskCreate, db: DbSession) -> TaskOut:
    task = Task(**body.model_dump(), source_type="manual")
    db.add(task)
    db.commit()
    return _out(db, task)


@router.put("/{task_id}", response_model=TaskOut)
def update(task_id: int, body: TaskUpdate, db: DbSession) -> TaskOut:
    task = _get(db, task_id)
    changes = body.model_dump(exclude_unset=True)
    status = changes.pop("status", None)
    for key, value in changes.items():
        setattr(task, key, value)
    if status:
        task_service.set_status(task, status)
    db.commit()
    return _out(db, task)


@router.delete("/{task_id}")
def delete(task_id: int, db: DbSession) -> dict:
    db.delete(_get(db, task_id))
    db.commit()
    return {"deleted": task_id}
