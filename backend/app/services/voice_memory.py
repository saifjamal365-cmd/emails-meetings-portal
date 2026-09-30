"""Voice memory: know people by their voice in later meetings (Settings -> Remember voices).

How a voice gets a name, without naming it in every meeting:
1. Automatically: the voice is SURE (Google Meet's captions named it, the person said their
   own name, or only one other person joined the call) -> that voice print is remembered.
2. Once by the user: on a meeting page, name a voice nobody named ("Speaker 2 = Omar").
In the next meetings every separated voice is compared with the remembered ones. A close and
clear match gets the name, even if nobody says it. Each new sure meeting improves the print.

A voice print is biometric personal data. Nothing here runs while Remember voices is off (the
default - turn it on after the people agreed). The prints stay on this computer, encrypted,
and can be deleted in Settings; "Delete my data" deletes them too.
"""

import json
from datetime import datetime

import numpy as np
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Meeting, MeetingVoice, VoicePrint
from app.services import speakers
from app.services.app_settings import get_app_settings
from app.services.crypto import decrypt, encrypt

MAX_WEIGHT = 20  # a print learns from new meetings; old ones count at most this much


def enabled(db: Session) -> bool:
    return bool(get_app_settings(db).remember_voices)


def _unit(vector: np.ndarray) -> np.ndarray:
    size = np.linalg.norm(vector)
    return vector / size if size else vector


def _pack(vector: np.ndarray) -> str:
    return encrypt(json.dumps([round(float(x), 5) for x in vector]))


def _unpack(token: str) -> np.ndarray:
    return np.array(json.loads(decrypt(token)), dtype=np.float32)


def known(db: Session) -> dict[str, np.ndarray]:
    """Remembered voices: name -> voice print."""
    return {p.name: _unpack(p.print_encrypted) for p in db.scalars(select(VoicePrint))}


def save_meeting_voices(
    db: Session, meeting: Meeting, voices: dict[str, list[float]]
) -> dict[str, tuple[str, float]]:
    """Keep this meeting's voice prints (so they can be named later) and name the voices the
    memory knows. Returns the recognized ones: {"Speaker 2": ("Omar", 0.82)}."""
    if not enabled(db) or not voices:
        return {}
    remembered = known(db)
    threshold = get_settings().voice_match_threshold
    db.execute(delete(MeetingVoice).where(MeetingVoice.meeting_id == meeting.id))
    found = {}
    for label, vector in voices.items():
        voice = _unit(np.array(vector, dtype=np.float32))
        name, score = speakers.best_match(voice, remembered, threshold)
        db.add(
            MeetingVoice(
                meeting_id=meeting.id,
                label=label,
                print_encrypted=_pack(voice),
                name=name,
                named_by="voice" if name else None,
                match_score=round(score, 3),
            )
        )
        if name:
            found[label] = (name, score)
    db.flush()
    return found


def _rows(db: Session, meeting: Meeting) -> dict[str, MeetingVoice]:
    rows = db.scalars(select(MeetingVoice).where(MeetingVoice.meeting_id == meeting.id))
    return {row.label: row for row in rows}


def known_names(db: Session, meeting: Meeting) -> dict[str, tuple[str, str, float | None]]:
    """Voices of this meeting with a reliable name (voice memory, or named by the user):
    {"Speaker 2": ("Omar", "voice", 0.82)}."""
    return {
        label: (row.name, row.named_by, row.match_score)
        for label, row in _rows(db, meeting).items()
        if row.name and row.named_by in ("voice", "you")
    }


def labels_with_prints(db: Session, meeting: Meeting) -> list[str]:
    return sorted(_rows(db, meeting))


def remember(db: Session, name: str, voice: np.ndarray) -> None:
    """Add a voice to the memory, or improve the print of a person already remembered."""
    row = db.scalar(select(VoicePrint).where(func.lower(VoicePrint.name) == name.lower()))
    if row is None:
        db.add(VoicePrint(name=name, print_encrypted=_pack(_unit(voice)), meetings=1))
        return
    weight = min(row.meetings, MAX_WEIGHT)
    row.print_encrypted = _pack(_unit(_unpack(row.print_encrypted) * weight + voice))
    row.meetings += 1
    row.updated_at = datetime.now()


def _unlearn(db: Session, name: str, voice: np.ndarray) -> None:
    """Take a voice back out of a person's print (it was learned under a wrong name)."""
    row = db.scalar(select(VoicePrint).where(func.lower(VoicePrint.name) == name.lower()))
    if row is None:
        return
    if row.meetings <= 1:
        db.delete(row)
        return
    weight = min(row.meetings, MAX_WEIGHT)
    row.print_encrypted = _pack(_unit(_unpack(row.print_encrypted) * weight - voice))
    row.meetings -= 1


def learn(db: Session, meeting: Meeting, found: list[dict]) -> list[str]:
    """Remember the voices the agent is sure about. Returns the names it learned."""
    if not enabled(db):
        return []
    rows = _rows(db, meeting)
    learned = []
    for speaker in found:
        row = rows.get(speaker.get("label"))
        name = (speaker.get("name") or "").strip()
        if not (row and name and speaker.get("sure")) or row.learned or row.named_by == "you":
            continue
        if row.name and row.name.lower() != name.lower():
            continue  # the voice memory says somebody else: never mix two people's voices
        remember(db, name, _unpack(row.print_encrypted))
        row.learned = True
        if not row.name:
            row.name, row.named_by = name, "meet" if speaker.get("how") == "meet" else "talk"
        learned.append(name)
    return learned


def name_voice(db: Session, meeting: Meeting, label: str, name: str) -> bool:
    """The user named a voice. With Remember voices on, it is remembered for next time.
    Returns True when it is in the memory."""
    row = _rows(db, meeting).get(label)
    if row is None:
        return False
    voice = _unpack(row.print_encrypted)
    if row.learned and (row.name or "").lower() != name.lower():
        _unlearn(db, row.name, voice)  # it was learned under a wrong name
        row.learned = False
    row.name, row.named_by = name, "you"
    if enabled(db) and not row.learned:
        remember(db, name, voice)
        row.learned = True
    return bool(row.learned)


def forget(db: Session, voice_id: int) -> bool:
    row = db.get(VoicePrint, voice_id)
    if row is None:
        return False
    db.delete(row)
    return True


def forget_all(db: Session) -> int:
    """Delete every remembered voice and every saved meeting voice print."""
    db.execute(delete(MeetingVoice))
    return db.execute(delete(VoicePrint)).rowcount
