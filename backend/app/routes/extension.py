"""The Google Meet helper (the portal's browser extension) talks to the portal here.

GET  /api/extension/pair     - the extension's key. Needs the portal login: the portal page's
                               part of the extension picks it up (nothing to type).
GET  /api/extension/status   - is the extension installed and working? (Settings page)
POST /api/extension/hello    - the extension got its key
POST /api/extension/call     - the user "joined" / "left" a Google Meet call, or is "in_call"
POST /api/extension/captions - caption lines: who spoke when, and what
The last three are called by the extension with its key (header X-Portal-Extension) instead
of the login cookie, so they are public paths (see routes/auth.py) and check the key here.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.agents import meeting_agent
from app.db import DbSession
from app.services import meet_helper
from app.services.app_settings import get_app_settings

router = APIRouter(prefix="/extension", tags=["extension"])
log = logging.getLogger(__name__)


def _check_key(request: Request) -> None:
    if not meet_helper.key_ok(request.headers.get("X-Portal-Extension")):
        raise HTTPException(401, "Unknown extension. Open the portal once to connect it.")


@router.get("/pair")
def pair() -> dict:
    return {"key": meet_helper.key()}


class StatusOut(BaseModel):
    active: bool
    last_seen: datetime | None


@router.get("/status", response_model=StatusOut)
def status(db: DbSession) -> StatusOut:
    return StatusOut(
        active=meet_helper.active(db), last_seen=get_app_settings(db).extension_seen_at
    )


@router.post("/hello")
def hello(request: Request, db: DbSession) -> dict:
    """The extension got its key: it is installed and connected."""
    _check_key(request)
    meet_helper.seen(db)
    db.commit()
    return {"ok": True}


STALE = timedelta(minutes=2)  # a "joined" kept while the portal was off must not start it later


class CallBody(BaseModel):
    meeting_code: str = Field(pattern=meet_helper.MEET_CODE)
    state: Literal["joined", "left", "in_call"]
    at: int = Field(gt=0)  # when it happened: ms since 1970, the browser's clock
    captions_on: bool | None = None  # health report: are Google Meet's captions showing?
    caption_lines: int | None = None  # ... and how many caption lines were read
    page: dict | None = None  # when captions could not be turned on: Meet's button labels


@router.post("/call")
def call(body: CallBody, request: Request, db: DbSession) -> dict:
    _check_key(request)
    meet_helper.seen(db)
    log.info(
        "Meet helper: %s %s (captions on: %s, lines read: %s)",
        body.state, body.meeting_code, body.captions_on, body.caption_lines,
    )  # fmt: skip
    if body.page:
        log.info("Meet helper page report: %s", json.dumps(body.page, ensure_ascii=False)[:6000])
    if datetime.now() - datetime.fromtimestamp(body.at / 1000) > STALE:
        db.commit()
        return {"recorder": "too old - ignored"}
    recorder = meeting_agent.meet_call(db, body.meeting_code, body.state)
    db.commit()
    return {"recorder": recorder}


class CaptionLine(BaseModel):
    id: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=200)
    start: int = Field(gt=0)  # ms since 1970, the browser's clock (= this computer's clock)
    end: int = Field(gt=0)
    text: str = Field(default="", max_length=5000)


class CaptionsBody(BaseModel):
    meeting_code: str = Field(pattern=meet_helper.MEET_CODE)
    lines: list[CaptionLine] = Field(max_length=500)


@router.post("/captions")
def captions(body: CaptionsBody, request: Request, db: DbSession) -> dict:
    _check_key(request)
    meet_helper.seen(db)
    saved = meet_helper.save_lines(
        db, body.meeting_code, [line.model_dump() for line in body.lines]
    )
    db.commit()
    return {"saved": saved}
