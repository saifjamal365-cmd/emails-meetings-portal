"""Morning plan and end-of-day summary endpoints (one of each per day)."""

from datetime import date, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.agents import planner
from app.agents.planner import Kind
from app.db import DbSession
from app.models import DailyReport

router = APIRouter(prefix="/reports", tags=["reports"])


class ReportOut(BaseModel):
    id: int
    date: date
    type: str
    content: str
    made_by: str | None
    edited_by_user: bool
    created_at: datetime | None


class DayReports(BaseModel):
    date: date
    morning: ReportOut | None
    evening: ReportOut | None


class GenerateOut(BaseModel):
    report: ReportOut
    warning: str | None


class EditBody(BaseModel):
    content: str


def _out(r: DailyReport) -> ReportOut:
    return ReportOut(
        id=r.id,
        date=r.date,
        type=r.type,
        content=r.content,
        made_by=r.made_by,
        edited_by_user=bool(r.edited_by_user),
        created_at=r.created_at,
    )


@router.get("", response_model=DayReports)
def for_day(db: DbSession, day: date | None = None) -> DayReports:
    day = day or date.today()
    rows = db.scalars(select(DailyReport).where(DailyReport.date == day)).all()
    by_type = {r.type: _out(r) for r in rows}
    return DayReports(date=day, morning=by_type.get("morning"), evening=by_type.get("evening"))


@router.get("/days", response_model=list[date])
def days_with_reports(db: DbSession) -> list[date]:
    """Dates that have a plan or a summary, newest first (the history list)."""
    rows = db.scalars(select(DailyReport.date).distinct().order_by(DailyReport.date.desc()))
    return list(rows)


@router.post("/{kind}/generate", response_model=GenerateOut)
def generate(kind: Kind, db: DbSession, day: date | None = None) -> GenerateOut:
    result = planner.generate(db, kind, day)
    return GenerateOut(report=_out(result.report), warning=result.warning)


@router.put("/{report_id}", response_model=ReportOut)
def edit(report_id: int, body: EditBody, db: DbSession) -> ReportOut:
    report = db.get(DailyReport, report_id)
    if report is None:
        raise HTTPException(404, "Report not found.")
    report.content = body.content
    report.edited_by_user = True
    db.commit()
    return _out(report)
