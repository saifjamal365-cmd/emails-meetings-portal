"""DELETE /api/data - "Delete my data": remove all saved emails, meetings, tasks, plans and
remembered voices.

The emails stay in Gmail and the meetings in Google; only the portal's copies are deleted.
Settings and the Google connection are kept (disconnect Google separately in Settings).
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete

from app.db import DbSession
from app.models import (
    ActivityLog,
    DailyReport,
    Email,
    EmailAnalysis,
    EmailMeetingLink,
    MeetCaption,
    Meeting,
    MeetingSummary,
    MeetingVoice,
    Notification,
    Task,
    VoicePrint,
)

router = APIRouter(prefix="/data", tags=["data"])

# Children first, so no row points to a deleted row.
TABLES = [
    EmailMeetingLink,
    EmailAnalysis,
    Email,
    MeetingSummary,
    MeetingVoice,
    Meeting,
    MeetCaption,  # Google Meet captions from the browser extension
    VoicePrint,  # remembered voices (biometric data)
    Task,
    DailyReport,
    ActivityLog,
    Notification,
]


class DeleteBody(BaseModel):
    confirm: str  # must be the word DELETE, so it cannot happen by mistake


@router.delete("")
def delete_my_data(body: DeleteBody, db: DbSession) -> dict:
    if body.confirm != "DELETE":
        raise HTTPException(400, "Type DELETE to confirm.")
    counts = {}
    for model in TABLES:
        counts[model.__tablename__] = db.execute(delete(model)).rowcount
    db.commit()
    return {"deleted": counts}
