"""Meetings from Google Calendar + transcripts from the Google Meet API.

- Calendar: finished events that have a Google Meet link (title, time, organizer, attendees).
- Meet API: the conference record of that meeting code, its transcript, and the speakers.

Transcripts exist only when "Transcription" was turned on in the meeting (a Google Workspace
feature). Zoom and Teams can be added later in this file with the same functions.
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.services import google_client


@dataclass
class CalendarMeeting:
    event_id: str
    title: str
    start: datetime  # local time, no timezone
    end: datetime
    meeting_code: str
    organizer: str
    attendees: list[str] = field(default_factory=list)

    @property
    def provider_meeting_id(self) -> str:
        return f"{self.event_id}@{self.start:%Y%m%dT%H%M}"


@dataclass
class TranscriptResult:
    status: str  # "ready" / "waiting" / "none"
    text: str = ""
    conference_record: str | None = None


# ---- time helpers --------------------------------------------------------------


def _parse_time(value: str) -> datetime:
    """RFC 3339 time from Google -> local time without timezone (how the DB stores times)."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)


def _rfc3339(local: datetime) -> str:
    return local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _all_pages(request_fn, key: str, **kwargs) -> list[dict]:
    """Call a Google list method until there are no more pages."""
    items, token = [], None
    while True:
        page = {"pageToken": token} if token else {}
        response = request_fn(**kwargs, **page).execute()
        items.extend(response.get(key, []))
        token = response.get("nextPageToken")
        if not token:
            return items


# ---- Calendar ------------------------------------------------------------------


def _person(p: dict) -> str:
    name, email = p.get("displayName", ""), p.get("email", "")
    return f"{name} <{email}>" if name and email else (name or email)


def list_finished_meetings(db: Session, days: int = 14) -> list[CalendarMeeting]:
    """Google Meet meetings from the primary calendar that ended in the last `days` days."""
    calendar = google_client.service(db, "calendar", "v3")
    now = datetime.now()
    events = _all_pages(
        calendar.events().list,
        "items",
        calendarId="primary",
        timeMin=_rfc3339(now - timedelta(days=days)),
        timeMax=_rfc3339(now),
        singleEvents=True,
        orderBy="startTime",
        maxResults=250,
    )
    meetings = []
    for e in events:
        conference = e.get("conferenceData", {})
        is_meet = (
            conference.get("conferenceSolution", {}).get("key", {}).get("type") == "hangoutsMeet"
        )
        start, end = e.get("start", {}).get("dateTime"), e.get("end", {}).get("dateTime")
        if not (is_meet and conference.get("conferenceId") and start and end):
            continue  # not a Meet meeting, or an all-day event
        attendees = e.get("attendees", [])
        if any(a.get("self") and a.get("responseStatus") == "declined" for a in attendees):
            continue  # the user said No to this meeting
        end_time = _parse_time(end)
        if end_time > now:
            continue  # not finished yet
        meetings.append(
            CalendarMeeting(
                event_id=e["id"],
                title=e.get("summary", "(no title)"),
                start=_parse_time(start),
                end=end_time,
                meeting_code=conference["conferenceId"],
                organizer=_person(e.get("organizer", {})),
                attendees=[_person(a) for a in attendees if not a.get("resource")],
            )
        )
    return meetings


VIDEO_LINKS = ("meet.google.com", "zoom.us", "teams.microsoft.com", "teams.live.com")


def _video_link(e: dict) -> str | None:
    """The meeting's video link (Meet, Zoom or Teams), or None for a normal calendar event."""
    if e.get("hangoutLink"):
        return e["hangoutLink"]
    for point in e.get("conferenceData", {}).get("entryPoints", []):
        if point.get("entryPointType") == "video" and point.get("uri"):
            return point["uri"]
    text = f"{e.get('location', '')} {e.get('description', '')}"
    for word in text.split():
        if any(site in word for site in VIDEO_LINKS):
            return word.strip("<>()\"'")
    return None


def list_current_meetings(db: Session, early_seconds: int = 0) -> list[CalendarMeeting]:
    """Online meetings (Meet, Zoom, Teams) happening now, or starting within `early_seconds`
    - for the meeting recorder."""
    calendar = google_client.service(db, "calendar", "v3")
    now = datetime.now()
    early = timedelta(seconds=early_seconds)
    events = _all_pages(
        calendar.events().list,
        "items",
        calendarId="primary",
        timeMin=_rfc3339(now),  # events that end after now ...
        timeMax=_rfc3339(now + early + timedelta(minutes=1)),  # ... and start soon
        singleEvents=True,
        orderBy="startTime",
        maxResults=20,
    )
    meetings = []
    for e in events:
        start, end = e.get("start", {}).get("dateTime"), e.get("end", {}).get("dateTime")
        if not (start and end) or not _video_link(e):
            continue  # all-day event, or no video link
        attendees = e.get("attendees", [])
        if any(a.get("self") and a.get("responseStatus") == "declined" for a in attendees):
            continue
        start_time, end_time = _parse_time(start), _parse_time(end)
        if not start_time - early <= now < end_time:
            continue
        meetings.append(
            CalendarMeeting(
                event_id=e["id"],
                title=e.get("summary", "(no title)"),
                start=start_time,
                end=end_time,
                meeting_code=e.get("conferenceData", {}).get("conferenceId", ""),
                organizer=_person(e.get("organizer", {})),
                attendees=[_person(a) for a in attendees if not a.get("resource")],
            )
        )
    return meetings


# ---- Meet transcripts ----------------------------------------------------------


def _speaker(participant: dict) -> str:
    for kind in ("signedinUser", "anonymousUser", "phoneUser"):
        if participant.get(kind, {}).get("displayName"):
            return participant[kind]["displayName"]
    return "Unknown speaker"


def fetch_transcript(db: Session, meeting: CalendarMeeting) -> TranscriptResult:
    """Find the Meet conference for this meeting and download its transcript, if there is one."""
    meet = google_client.service(db, "meet", "v2")
    records = meet.conferenceRecords()
    window = (
        f'space.meeting_code = "{meeting.meeting_code}" '
        f'AND start_time >= "{_rfc3339(meeting.start - timedelta(hours=1))}" '
        f'AND start_time <= "{_rfc3339(meeting.end)}"'
    )
    found = _all_pages(records.list, "conferenceRecords", filter=window)
    if not found:
        return TranscriptResult(status="none")  # nobody joined on Meet at that time
    record = max(found, key=lambda r: r.get("startTime", ""))
    name = record["name"]

    transcripts = _all_pages(records.transcripts().list, "transcripts", parent=name)
    if not transcripts:
        return TranscriptResult(status="none", conference_record=name)  # transcription was off
    if not any(t.get("state") in ("ENDED", "FILE_GENERATED") for t in transcripts):
        return TranscriptResult(status="waiting", conference_record=name)

    speakers = {
        p["name"]: _speaker(p)
        for p in _all_pages(records.participants().list, "participants", parent=name)
    }
    lines = []
    for t in sorted(transcripts, key=lambda t: t.get("startTime", "")):
        entries = _all_pages(
            records.transcripts().entries().list,
            "transcriptEntries",
            parent=t["name"],
            pageSize=100,
        )
        for entry in entries:
            when = (
                _parse_time(entry["startTime"]).strftime("%H:%M") if entry.get("startTime") else ""
            )
            who = speakers.get(entry.get("participant", ""), "Unknown speaker")
            lines.append(f"[{when}] {who}: {entry.get('text', '').strip()}")

    if not lines:
        return TranscriptResult(status="waiting", conference_record=name)
    return TranscriptResult(status="ready", text="\n".join(lines), conference_record=name)


# ---- Uploaded files (backup when there is no API transcript) ----------------------

_VTT_TIME = re.compile(r"^\d{2}:\d{2}(:\d{2})?[.,]\d{3}\s+-->")
_VTT_VOICE = re.compile(r"<v\s+([^>]+)>(.*?)(</v>)?$")


def clean_uploaded_transcript(text: str) -> str:
    """Turn a .vtt / .srt file into plain "Speaker: text" lines. Plain text stays as it is."""
    text = text.removeprefix(chr(0xFEFF))  # the byte-order mark some editors add
    looks_timed = text.startswith("WEBVTT") or re.search(
        r"^\d{2}:\d{2}:\d{2}[.,]\d{3} -->", text, re.M
    )
    if not looks_timed:
        return text.strip()
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("WEBVTT", "NOTE", "Kind:", "Language:")) or line.isdigit():
            continue
        if _VTT_TIME.match(line):
            continue
        voice = _VTT_VOICE.match(line)
        if voice:
            line = f"{voice.group(1).strip()}: {voice.group(2).strip()}"
        line = re.sub(r"<[^>]+>", "", line).strip()
        if line and (not lines or lines[-1] != line):  # auto captions repeat lines
            lines.append(line)
    return "\n".join(lines)
