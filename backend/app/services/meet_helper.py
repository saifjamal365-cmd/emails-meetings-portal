"""The Google Meet helper: the portal's own browser extension (the "extension" folder).

In a Google Meet call the extension turns on the live captions, sends WHO spoke WHEN (and the
caption text) to this portal, and says when the user joins and leaves the call. Here:
- the extension's key: the logged-in portal page gives it to the extension (nothing to type),
- saving the caption lines,
- naming the separated voices: the voice that talks while Google Meet shows "Sami" is Sami,
- the named captions as extra help for the summary.
Everything stays on this computer: the extension only talks to http://localhost:8000.
"""

import hmac
import re
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import secret_from_file
from app.models import MeetCaption
from app.services.app_settings import get_app_settings

MEET_CODE = r"^[a-z]{3}-[a-z]{4}-[a-z]{3}$"
ACTIVE_DAYS = 7  # the extension counts as installed when it spoke in the last 7 days
CAPTION_LAG = 1.5  # a caption shows about 1-2 seconds after the words are said
MIN_SECONDS = 2.0  # a voice needs this much talk at caption times to get a name
MIN_SHARE = 0.6  # ... and this share of it must be one person's captions
ME_WORDS = {"you", "أنت", "انت"}  # how Google Meet names the user in their own captions
PROMPT_CHARS = 30_000  # the most caption text given to the summary


def key() -> str:
    """The extension's key, made once (data_dir/extension.key, git-ignored)."""
    return secret_from_file("extension.key").decode()


def key_ok(given: str | None) -> bool:
    return bool(given) and hmac.compare_digest(given.encode(), key().encode())


def seen(db: Session) -> None:
    get_app_settings(db).extension_seen_at = datetime.now()


def active(db: Session) -> bool:
    """Installed and working: it sent something in the last days."""
    seen_at = get_app_settings(db).extension_seen_at
    return bool(seen_at) and datetime.now() - seen_at < timedelta(days=ACTIVE_DAYS)


def _time(ms: int) -> datetime:
    """Browser time (ms since 1970) -> local time without timezone, like the other times."""
    return datetime.fromtimestamp(ms / 1000)


def save_lines(db: Session, code: str, lines: list[dict]) -> int:
    """Save caption lines. The same line comes again while it grows: it is updated."""
    ids = [line["id"] for line in lines]
    existing = {
        row.client_id: row
        for row in db.scalars(
            select(MeetCaption).where(
                MeetCaption.meeting_code == code, MeetCaption.client_id.in_(ids)
            )
        )
    }
    for line in lines:
        row = existing.get(line["id"])
        if row is None:
            row = MeetCaption(meeting_code=code, client_id=line["id"])
            db.add(row)
            existing[line["id"]] = row
        row.name = line["name"].strip()
        row.start, row.end = _time(line["start"]), _time(max(line["end"], line["start"]))
        row.text = line.get("text", "").strip()
        row.spans = [[int(s), int(max(e, s))] for s, e in line.get("spans") or []]
    return len(lines)


def _talk_times(caption: MeetCaption, started_at: datetime) -> list[tuple[float, float]]:
    """When this caption's speaker really talked, in seconds from the recording start. A caption
    box can stay open for minutes while others talk: its "spans" say when the words grew."""
    base = started_at.timestamp()
    if caption.spans:
        return [(s / 1000 - base, e / 1000 - base) for s, e in caption.spans]
    return [
        ((caption.start - started_at).total_seconds(), (caption.end - started_at).total_seconds())
    ]


def lines_for(db: Session, code: str | None, start: datetime, end: datetime) -> list[MeetCaption]:
    if not code or not re.match(MEET_CODE, code):
        return []
    return list(
        db.scalars(
            select(MeetCaption)
            .where(
                MeetCaption.meeting_code == code,
                MeetCaption.end >= start,
                MeetCaption.start <= end,
            )
            .order_by(MeetCaption.start)
        )
    )


def is_me(name: str, me_name: str) -> bool:
    n = name.strip().lower()
    return n in ME_WORDS or n == me_name.strip().lower()


def name_voices(
    times: dict[str, list[tuple[float, float]]],
    started_at: datetime,
    captions: list[MeetCaption],
    me_name: str,
) -> dict[str, dict]:
    """Voice -> Google Meet name: the person whose captions show while that voice talks.
    Returns {"Speaker 2": {"name": "Sami Kharroub", "share": 0.92}}. A voice gets a name only
    with enough talk at caption times, most of it with one person's captions."""
    spans = [
        (start - CAPTION_LAG, end + 0.5, c.name)
        for c in captions
        if not is_me(c.name, me_name)
        for start, end in _talk_times(c, started_at)
    ]
    found = {}
    for label, turns in times.items():
        overlap: dict[str, float] = {}
        for turn_start, turn_end in turns:
            for start, end, name in spans:
                both = min(turn_end, end) - max(turn_start, start)
                if both > 0:
                    overlap[name] = overlap.get(name, 0.0) + both
        if not overlap:
            continue
        name, best = max(overlap.items(), key=lambda item: item[1])
        share = best / sum(overlap.values())
        if best >= MIN_SECONDS and share >= MIN_SHARE:
            found[label] = {"name": name, "share": round(share, 2)}
    return found


def captions_text(captions: list[MeetCaption], me_name: str) -> str:
    """The captions as "[10:05:12] Sami Kharroub: ..." lines for the summary."""
    lines = []
    for c in captions:
        if c.text:
            who = me_name if is_me(c.name, me_name) else c.name
            lines.append(f"[{c.start:%H:%M:%S}] {who}: {c.text}")
    return "\n".join(lines)[:PROMPT_CHARS]
