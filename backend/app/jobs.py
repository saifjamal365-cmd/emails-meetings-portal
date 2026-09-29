"""Background jobs (APScheduler):
- check Gmail every few minutes
- when auto-summarize is on: find new meeting transcripts and summarize them
- morning plan (8:00) and end-of-day summary (18:00)
- meeting recorder: every minute, start/stop recording online meetings from the calendar
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.agents import email_agent, meeting_agent, planner
from app.config import get_settings
from app.db import SessionLocal
from app.services import google_client
from app.services.app_settings import get_app_settings
from app.services.notify import notify

log = logging.getLogger(__name__)


def _google_expired(db) -> None:
    db.rollback()
    notify(
        db,
        "problem",
        "Google login expired",
        "Open Settings and connect Google again.",
        "/settings",
    )
    db.commit()


def email_sync_job() -> None:
    with SessionLocal() as db:
        if google_client.account(db) is None:
            return  # Google not connected yet
        try:
            result = email_agent.sync(db)
            log.info("Email sync: %s", result)
        except google_client.GoogleNotConnected:
            _google_expired(db)
        except Exception:
            log.exception("Email sync failed")


def meeting_job() -> None:
    with SessionLocal() as db:
        if google_client.account(db) is None or not get_app_settings(db).auto_summarize:
            return
        try:
            result = meeting_agent.refresh_and_auto_summarize(db)
            log.info("Meeting auto-summarize: %s", result)
        except google_client.GoogleNotConnected:
            _google_expired(db)
        except Exception:
            log.exception("Meeting auto-summarize failed")


def recorder_job() -> None:
    with SessionLocal() as db:
        try:
            state = meeting_agent.recorder_tick(db)
            if state in ("started", "stopped", "extended"):
                log.info("Meeting recorder: %s", state)
        except google_client.GoogleNotConnected:
            _google_expired(db)
        except Exception:
            log.exception("Meeting recorder failed")


def report_job(kind: planner.Kind) -> None:
    with SessionLocal() as db:
        try:
            result = planner.scheduled(db, kind)
            if result:
                log.info("Daily %s report made (%s)", kind, result.report.made_by)
        except Exception:
            log.exception("Daily %s report failed", kind)


def start_scheduler() -> BackgroundScheduler | None:
    settings = get_settings()
    jobs = [
        (email_sync_job, settings.email_sync_minutes, "email_sync"),
        (meeting_job, settings.meeting_sync_minutes, "meeting_sync"),
    ]
    jobs = [job for job in jobs if job[1] > 0]
    reports = [
        ("morning", settings.morning_plan_hour),
        ("evening", settings.evening_summary_hour),
    ]
    reports = [(kind, hour) for kind, hour in reports if 0 <= hour <= 23]
    if not jobs and not reports and settings.recorder_check_seconds <= 0:
        return None
    scheduler = BackgroundScheduler()
    for fn, minutes, job_id in jobs:
        scheduler.add_job(fn, "interval", minutes=minutes, id=job_id)
    for kind, hour in reports:
        scheduler.add_job(report_job, "cron", hour=hour, args=[kind], id=f"report_{kind}")
    if settings.recorder_check_seconds > 0:
        scheduler.add_job(
            recorder_job, "interval", seconds=settings.recorder_check_seconds, id="recorder"
        )
    scheduler.start()
    return scheduler
