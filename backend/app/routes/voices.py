"""The voice memory in Settings: who is remembered, and deleting voice prints.
(The prints themselves never leave the server - only names and counts are shown.)"""

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.db import DbSession
from app.models import VoicePrint
from app.services import voice_memory

router = APIRouter(prefix="/voices", tags=["voices"])


class VoiceOut(BaseModel):
    id: int
    name: str
    meetings: int  # how many meetings the voice was learned from
    updated_at: datetime


@router.get("", response_model=list[VoiceOut])
def list_voices(db: DbSession) -> list[VoiceOut]:
    rows = db.scalars(select(VoicePrint).order_by(VoicePrint.name))
    return [
        VoiceOut(id=r.id, name=r.name, meetings=r.meetings, updated_at=r.updated_at) for r in rows
    ]


@router.delete("")
def forget_all(db: DbSession) -> dict:
    deleted = voice_memory.forget_all(db)
    db.commit()
    return {"deleted": deleted}


@router.delete("/{voice_id}")
def forget(voice_id: int, db: DbSession) -> dict:
    if not voice_memory.forget(db, voice_id):
        raise HTTPException(404, "Voice not found.")
    db.commit()
    return {"deleted": 1}
