"""GET/PUT /api/settings - Email agent sender lists and the meeting auto-summarize switch."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.db import DbSession
from app.services.app_settings import get_app_settings

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsBody(BaseModel):
    high_domains: list[str]
    low_domains: list[str]
    auto_summarize: bool = False
    auto_record: bool = False
    meeting_words: list[str] = []
    remember_voices: bool = False


def _clean(domains: list[str]) -> list[str]:
    """Lower-case, remove spaces and a leading "@", drop empty and repeated items.
    An item is a domain (acme.com) or a full address (sara@acme.com)."""
    result: list[str] = []
    for d in domains:
        d = d.strip().lower().lstrip("@")
        if d and d not in result:
            result.append(d)
    return result


def _out(s) -> SettingsBody:
    return SettingsBody(
        high_domains=s.high_domains,
        low_domains=s.low_domains,
        auto_summarize=s.auto_summarize,
        auto_record=bool(s.auto_record),
        meeting_words=s.meeting_words or [],
        remember_voices=bool(s.remember_voices),
    )


@router.get("", response_model=SettingsBody)
def read(db: DbSession) -> SettingsBody:
    return _out(get_app_settings(db))


@router.put("", response_model=SettingsBody)
def update(body: SettingsBody, db: DbSession) -> SettingsBody:
    s = get_app_settings(db)
    s.high_domains = _clean(body.high_domains)
    s.low_domains = _clean(body.low_domains)
    s.auto_summarize = body.auto_summarize
    s.auto_record = body.auto_record
    s.remember_voices = body.remember_voices
    words = [w.strip() for w in body.meeting_words]  # trim first, then remove repeats
    s.meeting_words = [w for w in dict.fromkeys(words) if w][:100]
    db.commit()
    return _out(s)
