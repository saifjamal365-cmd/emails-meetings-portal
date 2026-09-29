"""Agent 2 - Meeting Summary Agent.

1. refresh(): find finished Google Meet meetings in the calendar and download their
   transcripts (no copying by the user).
2. summarize(): the LLM reads the transcript (Arabic, English or mixed) and returns
   overview, action items + owners, decisions, risks, blockers and keywords (structured JSON).
3. The summary is saved, tasks are created from the user's own action items,
   and every step is written to the activity log (the "Integration logs").
4. Unread emails from the last 7 days are checked for the new keywords (agents/linker.py).
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import linker
from app.config import get_settings
from app.models import ActivityLog, Meeting, MeetingSummary, Task
from app.services import google_client, meeting_client, transcriber
from app.services.app_settings import get_app_settings
from app.services.llm_client import LLMError, ask_json
from app.services.notify import notify
from app.services.recorder import RecordingState, recorder

log = logging.getLogger(__name__)
PROMPT = (Path(__file__).parent.parent / "prompts" / "meeting_summary.txt").read_text("utf-8")
MAX_TRANSCRIPT_CHARS = 800_000  # about 200k tokens - many hours of talk

OutputLanguage = Literal["same", "ar", "en"]
LANGUAGE_RULE = {
    "same": "Write the summary in the main language of the meeting.",
    "ar": "Write the summary in Arabic.",
    "en": "Write the summary in English.",
}


class ActionItem(BaseModel):
    task: str
    owner: str
    owner_is_me: bool
    due: str = Field(description="YYYY-MM-DD, or empty if no date was said")


class SpeakerName(BaseModel):
    label: str = Field(description='The label in the transcript, e.g. "Speaker 1"')
    name: str = Field(description="The person's name, or empty if it is not clear")
    clue: str = Field(description="A few words: how you know")


class MeetingOutput(BaseModel):
    """What the LLM returns for one meeting."""

    overview: str
    detected_language: Literal["ar", "en", "mixed"]
    key_facts: list[str] = Field(default_factory=list, description="Numbers and facts said")
    action_items: list[ActionItem]
    decisions: list[str]
    risks: list[str]
    blockers: list[str]
    keywords: list[str]
    speakers: list[SpeakerName] = Field(
        default_factory=list, description='Who each "Speaker N" in the transcript is'
    )


@dataclass
class RefreshResult:
    found: int = 0
    new: int = 0
    ready: int = 0
    waiting: int = 0
    no_transcript: int = 0
    summarized: int = 0
    errors: list[str] = field(default_factory=list)


_refresh_lock = threading.Lock()


def _log(db: Session, action: str, meeting: Meeting, **details) -> None:
    db.add(
        ActivityLog(
            agent="meeting",
            action=action,
            details={"meeting_id": meeting.id, "title": meeting.title, **details},
        )
    )


def _parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


# ---- 1. Find meetings and transcripts -----------------------------------------------


def refresh(db: Session, days: int = 14) -> RefreshResult:
    """Get finished meetings from the calendar and download transcripts that are ready."""
    if not _refresh_lock.acquire(blocking=False):
        return RefreshResult(errors=["A refresh is already running. Try again in a moment."])
    try:
        result = RefreshResult()
        found = meeting_client.list_finished_meetings(db, days=days)
        result.found = len(found)

        for cal in found:
            meeting = db.scalar(
                select(Meeting).where(Meeting.provider_meeting_id == cal.provider_meeting_id)
            )
            if meeting is not None and meeting.platform == "recorded":
                # Recorded on this PC: its transcript comes from Whisper, not from the Meet API.
                result.ready += meeting.transcript_status == "ready"
                continue
            if meeting is None:
                meeting = Meeting(platform="meet", provider_meeting_id=cal.provider_meeting_id)
                db.add(meeting)
                result.new += 1
            meeting.title = cal.title
            meeting.date = cal.start
            meeting.end_time = cal.end
            meeting.meeting_code = cal.meeting_code
            meeting.owner = cal.organizer
            meeting.attendees = cal.attendees

            if meeting.transcript_status != "ready":
                transcript = meeting_client.fetch_transcript(db, cal)
                meeting.conference_record = transcript.conference_record
                # A missing transcript right after the meeting may still come: keep "waiting"
                # for 24 hours, then decide it is "none".
                recent = datetime.now() - cal.end < timedelta(hours=24)
                meeting.transcript_status = (
                    "waiting" if transcript.status == "none" and recent else transcript.status
                )
                if transcript.status == "ready":
                    meeting.transcript_text = transcript.text
                    db.flush()
                    _log(
                        db, "transcript_downloaded", meeting, lines=transcript.text.count("\n") + 1
                    )

            counter = {"ready": "ready", "waiting": "waiting", "none": "no_transcript"}
            key = counter[meeting.transcript_status]
            setattr(result, key, getattr(result, key) + 1)
        db.commit()
        return result
    finally:
        _refresh_lock.release()


def add_uploaded(db: Session, title: str, when: datetime, text: str) -> Meeting:
    """Backup way: a transcript file the user uploads (Zoom/Teams, or no Meet transcript)."""
    clean = meeting_client.clean_uploaded_transcript(text)
    if not clean:
        raise ValueError("The transcript is empty.")
    meeting = Meeting(
        platform="upload",
        provider_meeting_id=f"upload-{datetime.now():%Y%m%d%H%M%S%f}",
        title=title.strip() or "Uploaded meeting",
        date=when,
        attendees=[],
        transcript_text=clean,
        transcript_status="ready",
    )
    db.add(meeting)
    db.flush()
    _log(db, "transcript_uploaded", meeting, lines=clean.count("\n") + 1)
    db.commit()
    return meeting


# ---- 2. Summarize -------------------------------------------------------------------


def _meeting_words_hint(db: Session) -> str:
    """Names and terms from Settings, so misheard words can be corrected ("الهر" -> "HR")."""
    words = get_app_settings(db).meeting_words or []
    if not words:
        return ""
    return (
        "Names and words that often come up in the user's meetings (speech-to-text may have "
        f"written them wrong): {', '.join(words)}\n\n"
    )


def _who_am_i(db: Session, meeting: Meeting) -> str:
    account = google_client.account(db)
    if not account:
        return "The user is the owner of this portal (name unknown)."
    email, name = account
    return f"The user is {name or 'unknown name'} <{email}>."


def summarize(
    db: Session, meeting: Meeting, output_language: OutputLanguage = "same"
) -> MeetingSummary:
    """Ask the LLM for the structured summary, save it, and create tasks."""
    if meeting.transcript_status != "ready" or not meeting.transcript_text:
        raise ValueError("This meeting has no transcript yet.")
    if len(meeting.transcript_text) > MAX_TRANSCRIPT_CHARS:
        raise ValueError("This transcript is too long to summarize in one step.")

    attendees = "\n".join(f"- {a}" for a in meeting.attendees) or "- (not known)"
    joined = ", ".join(meeting.participants or [])
    joined_line = f"Joined the call (Google Meet): {joined}\n" if joined else ""
    prompt = (
        f"Today is {date.today():%A %Y-%m-%d}.\n"
        f"{_who_am_i(db, meeting)}\n\n"
        f"Meeting: {meeting.title}\nDate: {meeting.date:%A %Y-%m-%d %H:%M}\n"
        f"Organizer: {meeting.owner or '(not known)'}\nInvited:\n{attendees}\n{joined_line}\n"
        f"{_meeting_words_hint(db)}"
        f"{LANGUAGE_RULE[output_language]} Keep the keywords in both languages as explained.\n\n"
        f"<transcript>\n{meeting.transcript_text}\n</transcript>"
    )
    result = ask_json(
        prompt,
        MeetingOutput,
        system=PROMPT,
        max_tokens=16000,
        effort="medium",
        model=get_settings().meeting_llm_model,
    )
    out = result.data

    summary = meeting.summary or MeetingSummary(meeting_id=meeting.id)
    summary.overview = out.overview
    summary.detected_language = out.detected_language
    summary.action_items = [item.model_dump() for item in out.action_items]
    summary.decisions = out.decisions
    summary.risks = out.risks
    summary.blockers = out.blockers
    summary.keywords = out.keywords
    summary.key_facts = out.key_facts
    summary.speakers = [s.model_dump() for s in out.speakers]
    summary.output_language = output_language
    summary.created_at = datetime.now()
    meeting.summary = summary
    db.flush()

    _log(
        db,
        "summarized",
        meeting,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )
    created = _create_tasks(db, meeting, out)
    if created:
        _log(db, "tasks_created", meeting, count=len(created), titles=created)
    # The other way round: unread emails from the last 7 days may be about this meeting.
    linker.recheck_emails_for_meeting(db, meeting)
    db.commit()
    return summary


def _create_tasks(db: Session, meeting: Meeting, out: MeetingOutput) -> list[str]:
    """Tasks for the user's own action items only (blockers stay in the summary and the
    morning plan, not in Daily Tasks). No duplicates."""
    existing = set(
        db.scalars(
            select(Task.title).where(Task.source_type == "meeting", Task.source_id == meeting.id)
        )
    )
    soon = date.today() + timedelta(days=3)
    new_tasks: list[Task] = []
    for item in out.action_items:
        if not item.owner_is_me:
            continue
        due = _parse_date(item.due)
        new_tasks.append(
            Task(
                title=item.task,
                description=f"Action item from the meeting: {meeting.title}",
                owner=item.owner,
                due_date=due,
                priority="High" if due and due <= soon else "Medium",
            )
        )

    created = []
    for task in new_tasks:
        if task.title in existing:
            continue
        task.source_type = "meeting"
        task.source_id = meeting.id
        db.add(task)
        existing.add(task.title)
        created.append(task.title)
    return created


# ---- 3. Auto mode -------------------------------------------------------------------


def refresh_and_auto_summarize(db: Session) -> RefreshResult:
    """Background job when auto-summarize is on: refresh, then summarize every new transcript."""
    result = refresh(db)
    pending = db.scalars(
        select(Meeting).where(Meeting.transcript_status == "ready", ~Meeting.summary.has())
    ).all()
    for meeting in pending:
        try:
            summary = summarize(db, meeting)
            result.summarized += 1
            items = len(summary.action_items or [])
            notify(
                db,
                "meeting",
                f"Meeting summarized: {meeting.title}",
                f"{items} action item{'s' if items != 1 else ''}. Your tasks were added.",
                link=f"/meetings?open={meeting.id}",
            )
            db.commit()
        except (LLMError, ValueError) as e:
            db.rollback()
            result.errors.append(f"{meeting.title}: {e}")
            notify(db, "problem", "A meeting could not be summarized", f"{meeting.title}: {e}")
            db.commit()
    return result


# ---- 4. Record meetings on this computer (free accounts have no Meet transcripts) ------------
#
# Every minute (jobs.py -> recorder_tick): if auto-record is on and an online meeting from the
# calendar is happening now, start recording (mic = you, speakers = the others). At the
# calendar end time (a bit later if people still talk) stop, transcribe with local Whisper,
# summarize, create tasks and link emails - all without a click.

_process_lock = threading.Lock()  # one transcription at a time (it uses the CPU a lot)


def _me_name(db: Session) -> str:
    account = google_client.account(db)
    return (account[1] or account[0].split("@")[0]) if account else "Me"


def start_recording(
    db: Session,
    title: str,
    until: datetime,
    cal: meeting_client.CalendarMeeting | None = None,
) -> Meeting:
    """Start recording now. `cal` = the calendar meeting, or None for "Record now"."""
    if recorder.running:
        raise ValueError("A recording is already running.")
    provider_id = cal.provider_meeting_id if cal else f"rec-{datetime.now():%Y%m%d%H%M%S%f}"
    meeting = db.scalar(select(Meeting).where(Meeting.provider_meeting_id == provider_id))
    if meeting is None:
        meeting = Meeting(provider_meeting_id=provider_id, attendees=[])
        db.add(meeting)
    meeting.platform = "recorded"
    meeting.title = cal.title if cal else (title.strip() or "Recorded meeting")
    meeting.date = cal.start if cal else datetime.now()
    meeting.end_time = until
    if cal:
        meeting.owner, meeting.attendees, meeting.meeting_code = (
            cal.organizer,
            cal.attendees,
            cal.meeting_code,
        )
    meeting.transcript_status = "recording"
    db.flush()

    recorder.start(meeting.id, meeting.title, until, get_settings().data_dir / "recordings")
    recorder.state.scheduled_start = cal.start if cal else datetime.now()
    _log(db, "recording_started", meeting)
    notify(
        db,
        "meeting",
        f"Recording: {meeting.title}",
        "Please tell the other people that this meeting is recorded.",
        link=f"/meetings?open={meeting.id}",
    )
    db.commit()
    return meeting


def stop_recording(background: bool = True) -> RecordingState | None:
    """Stop the recording, then transcribe + summarize it (in the background by default)."""
    if not recorder.running:
        return None
    state = recorder.stop()
    if background:
        threading.Thread(target=process_recording, args=(state,), daemon=True).start()
    else:
        process_recording(state)
    return state


def _joined_the_call(db: Session, meeting: Meeting) -> list[str]:
    """Who joined the Google Meet call. It helps the agent name "Speaker 1", "Speaker 2" ...
    Zoom / Teams / "Record now" have no meeting code: nobody is listed."""
    if not meeting.meeting_code:
        return []
    try:
        return meeting_client.fetch_participants(
            db, meeting.meeting_code, meeting.date, meeting.end_time or datetime.now()
        )
    except Exception:  # not needed for the summary: go on without the names
        log.exception("Could not read who joined the call")
        return []


def process_recording(state: RecordingState) -> None:
    """Whisper transcript -> summary -> tasks and email links -> notification."""
    from app.db import SessionLocal  # here, to keep this module free of app start-up code

    with _process_lock, SessionLocal() as db:
        meeting = db.get(Meeting, state.meeting_id)
        if meeting is None:
            return
        link = f"/meetings?open={meeting.id}"
        meeting.transcript_status = "transcribing"
        db.commit()
        try:
            text = transcriber.transcribe_meeting(
                state.me_file,
                state.others_file,
                state.started_at,
                _me_name(db),
                get_app_settings(db).meeting_words or [],
            )
        except Exception as e:
            log.exception("Transcription failed")
            meeting.transcript_status = "none"
            notify(db, "problem", f"Could not transcribe: {meeting.title}", str(e)[:300], link)
            db.commit()
            return

        if not text:
            meeting.transcript_status = "none"
            detail = state.error or "No speech was found in the recording."
            notify(db, "problem", f"No transcript: {meeting.title}", detail, link)
            db.commit()
        else:
            meeting.transcript_text = text
            meeting.participants = _joined_the_call(db, meeting)
            meeting.transcript_status = "ready"
            _log(db, "transcript_recorded", meeting, lines=text.count("\n") + 1,
                 minutes=round(state.seconds / 60))  # fmt: skip
            db.commit()
            try:
                summary = summarize(db, meeting)
                items = len(summary.action_items or [])
                notify(db, "meeting", f"Meeting summarized: {meeting.title}",
                       f"{items} action item{'s' if items != 1 else ''}. Your tasks were added.",
                       link)  # fmt: skip
            except (LLMError, ValueError) as e:
                db.rollback()
                notify(db, "problem", f"Transcript ready, summary failed: {meeting.title}",
                       f"{e} Open the meeting and click Summarize.", link)  # fmt: skip
            db.commit()

        if not get_settings().keep_recordings:
            for path in (state.me_file, state.others_file):
                if path:
                    path.unlink(missing_ok=True)


def _silent_too_long(s: RecordingState, now: datetime) -> bool:
    """Nobody talked for silence_stop_minutes (twice as long if nobody has talked at all)."""
    minutes = get_settings().silence_stop_minutes
    if minutes <= 0:
        return False
    begin = max(filter(None, [s.scheduled_start, s.started_at]), default=now)
    if s.last_voice_at:
        return now - s.last_voice_at >= timedelta(minutes=minutes)
    return now - begin >= timedelta(minutes=2 * minutes)


def recorder_tick(db: Session) -> str:
    """Every few seconds: stop a finished recording, or start one for a meeting starting now."""
    settings = get_settings()
    now = datetime.now()
    if recorder.running:
        s = recorder.state
        if s.until and now >= s.until:
            talking = s.last_voice_at and now - s.last_voice_at < timedelta(minutes=1)
            if talking and s.extra_minutes < settings.record_max_extra_minutes:
                recorder.extend(5)  # the meeting runs late: keep recording
                return "extended"
            stop_recording()
            return "stopped"
        if _silent_too_long(s, now):  # everybody left (or you left the meeting)
            stop_recording()
            return "stopped (silence)"
        return "recording"

    if not get_app_settings(db).auto_record or google_client.account(db) is None:
        return "off"
    for cal in meeting_client.list_current_meetings(db, settings.record_start_early_seconds):
        done = db.scalar(
            select(Meeting).where(
                Meeting.provider_meeting_id == cal.provider_meeting_id,
                Meeting.platform == "recorded",
            )
        )
        if done is None:  # not recorded yet (also not after a stop in the middle)
            start_recording(db, cal.title, cal.end, cal)
            return "started"
    return "idle"


def recover_unfinished() -> int:
    """After a restart: finish meetings that were recording or being transcribed.

    Their audio files are still in data_dir/recordings, so they are transcribed and summarized
    now. Without files, the meeting is marked "none". Returns how many were restarted.
    """
    from app.db import SessionLocal

    folder = get_settings().data_dir / "recordings"
    jobs = []
    with SessionLocal() as db:
        stuck = db.scalars(
            select(Meeting).where(Meeting.transcript_status.in_(("recording", "transcribing")))
        ).all()
        for meeting in stuck:
            if recorder.running and recorder.state.meeting_id == meeting.id:
                continue
            files = sorted(folder.glob(f"meeting{meeting.id}-*-me.wav"))
            if not files:
                meeting.transcript_status = "none"
                continue
            me_file = files[-1]
            stamp = me_file.name.split("-", 1)[1].rsplit("-me.wav", 1)[0]  # 20260929-013032
            try:
                started_at = datetime.strptime(stamp, "%Y%m%d-%H%M%S")
            except ValueError:
                started_at = meeting.date
            jobs.append(
                RecordingState(
                    meeting_id=meeting.id,
                    title=meeting.title,
                    started_at=started_at,
                    me_file=me_file,
                    others_file=me_file.with_name(me_file.name.replace("-me.wav", "-others.wav")),
                    finished=True,
                )
            )
            _log(db, "recording_recovered", meeting)
        db.commit()
    for state in jobs:  # one after another (process_recording takes the lock)
        threading.Thread(target=process_recording, args=(state,), daemon=True).start()
    return len(jobs)
