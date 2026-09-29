"""Meeting recorder: calendar -> record -> Whisper -> summary. Fake audio, Whisper and LLM."""

from datetime import datetime, timedelta

import pytest

from app.agents import meeting_agent
from app.models import Meeting, Notification, Task
from app.services import google_client, meeting_client, transcriber
from app.services.app_settings import get_app_settings
from app.services.llm_client import LLMJsonResult
from app.services.recorder import RecordingState

NOW = datetime.now().replace(microsecond=0)


class FakeRecorder:
    """Records nothing; remembers what it was asked to do."""

    def __init__(self) -> None:
        self.running = False
        self.state = RecordingState()

    def start(self, meeting_id, title, until, folder) -> None:
        self.running = True
        self.state = RecordingState(
            meeting_id=meeting_id,
            title=title,
            started_at=NOW,
            until=until,
            me_file=folder / "me.wav",
            others_file=folder / "others.wav",
        )

    def extend(self, minutes) -> None:
        self.state.until += timedelta(minutes=minutes)
        self.state.extra_minutes += minutes

    def stop(self) -> RecordingState:
        self.running = False
        self.state.finished = True
        return self.state


@pytest.fixture
def rec(monkeypatch) -> FakeRecorder:
    fake = FakeRecorder()
    monkeypatch.setattr(meeting_agent, "recorder", fake)
    monkeypatch.setattr(google_client, "account", lambda db: ("saif@gmail.com", "Saif jamal"))
    return fake


def calendar_meeting(minutes_left: int = 30) -> meeting_client.CalendarMeeting:
    return meeting_client.CalendarMeeting(
        event_id="evt-live",
        title="Project Falcon sync",
        start=NOW - timedelta(minutes=5),
        end=NOW + timedelta(minutes=minutes_left),
        meeting_code="",
        organizer="Omar <omar@t2.sa>",
        attendees=["Omar <omar@t2.sa>"],
    )


def summary_output():
    return meeting_agent.MeetingOutput(
        overview="Falcon launch and price list.",
        detected_language="mixed",
        action_items=[
            meeting_agent.ActionItem(
                task="Send the price list", owner="Saif jamal", owner_is_me=True, due=""
            )
        ],
        decisions=["Launch on 20 October"],
        risks=[],
        blockers=[],
        keywords=["Project Falcon", "مشروع فالكون"],
    )


# ---- merge of the two tracks ------------------------------------------------------------------


def test_merge_puts_both_tracks_in_time_order_with_names() -> None:
    start = datetime(2026, 9, 28, 10, 0, 0)
    me = [(5.0, "I will send the price list."), (130.0, "Thanks all.")]
    others = [(60.0, "Speaker 1", "السلام عليكم، نحتاج العرض قبل الخميس")]
    assert transcriber.merge(me, others, start, "Saif jamal") == (
        "[10:00] Saif jamal: I will send the price list.\n"
        "[10:01] Speaker 1: السلام عليكم، نحتاج العرض قبل الخميس\n"
        "[10:02] Saif jamal: Thanks all."
    )


# ---- the minute check -------------------------------------------------------------------------


def test_nothing_happens_when_auto_record_is_off(db, rec, monkeypatch) -> None:
    monkeypatch.setattr(
        meeting_client, "list_current_meetings", lambda db, early=0: [calendar_meeting()]
    )
    assert meeting_agent.recorder_tick(db) == "off"
    assert rec.running is False


def test_meeting_from_calendar_starts_recording(db, rec, monkeypatch) -> None:
    get_app_settings(db).auto_record = True
    db.commit()
    cal = calendar_meeting()
    monkeypatch.setattr(meeting_client, "list_current_meetings", lambda db, early=0: [cal])

    assert meeting_agent.recorder_tick(db) == "started"

    meeting = db.query(Meeting).one()
    assert (meeting.platform, meeting.transcript_status) == ("recorded", "recording")
    assert meeting.title == "Project Falcon sync" and meeting.owner == "Omar <omar@t2.sa>"
    assert rec.state.until == cal.end
    notice = db.query(Notification).one()
    assert notice.title == "Recording: Project Falcon sync"
    assert "tell the other people" in notice.body

    assert meeting_agent.recorder_tick(db) == "recording"  # already running: no second start


def test_a_recorded_meeting_is_not_recorded_again(db, rec, monkeypatch) -> None:
    get_app_settings(db).auto_record = True
    db.commit()
    monkeypatch.setattr(
        meeting_client, "list_current_meetings", lambda db, early=0: [calendar_meeting()]
    )
    meeting_agent.recorder_tick(db)
    rec.stop()  # the user stopped it in the middle of the meeting

    assert meeting_agent.recorder_tick(db) == "idle"


def test_stop_at_the_end_or_extend_while_people_talk(db, rec, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(meeting_agent, "stop_recording", lambda: calls.append("stop"))
    rec.running = True
    rec.state = RecordingState(meeting_id=1, until=NOW - timedelta(seconds=1))

    rec.state.last_voice_at = datetime.now()  # still talking at the end time
    assert meeting_agent.recorder_tick(db) == "extended"
    assert rec.state.extra_minutes == 5

    rec.state.until = NOW - timedelta(seconds=1)
    rec.state.last_voice_at = datetime.now() - timedelta(minutes=3)  # quiet now
    assert meeting_agent.recorder_tick(db) == "stopped"
    assert calls == ["stop"]


# ---- after the recording: transcript -> summary -> tasks --------------------------------------


def test_recording_is_transcribed_summarized_and_files_deleted(db, rec, monkeypatch, tmp_path):
    meeting = meeting_agent.start_recording(db, "Ad-hoc call", NOW + timedelta(hours=2))
    rec.state.me_file, rec.state.others_file = tmp_path / "me.wav", tmp_path / "others.wav"
    rec.state.me_file.write_bytes(b"x")
    rec.state.others_file.write_bytes(b"x")
    rec.state.seconds = 600

    seen = {}

    def fake_transcribe(me_file, others_file, started_at, me_name, words=None):
        seen["me_name"] = me_name
        return "[10:00] Saif jamal: I will send the price list.\n[10:01] Others: شكراً"

    monkeypatch.setattr(transcriber, "transcribe_meeting", fake_transcribe)
    monkeypatch.setattr(
        meeting_agent,
        "ask_json",
        lambda *a, **k: LLMJsonResult(
            data=summary_output(), model="f", input_tokens=1, output_tokens=1
        ),
    )

    meeting_agent.stop_recording(background=False)

    db.expire_all()
    meeting = db.get(Meeting, meeting.id)
    assert seen["me_name"] == "Saif jamal"
    assert meeting.transcript_status == "ready"
    assert meeting.summary.decisions == ["Launch on 20 October"]
    assert [t.title for t in db.query(Task).all()] == ["Send the price list"]
    titles = [n.title for n in db.query(Notification).all()]
    assert "Meeting summarized: Ad-hoc call" in titles
    assert not rec.state.me_file.exists() and not rec.state.others_file.exists()


def test_silent_recording_gives_a_clear_message(db, rec, monkeypatch) -> None:
    meeting = meeting_agent.start_recording(db, "Quiet call", NOW + timedelta(hours=1))
    monkeypatch.setattr(transcriber, "transcribe_meeting", lambda *a: "")

    meeting_agent.stop_recording(background=False)

    db.expire_all()
    assert db.get(Meeting, meeting.id).transcript_status == "none"
    assert any(n.title == "No transcript: Quiet call" for n in db.query(Notification).all())


# ---- API ------------------------------------------------------------------------------------


def test_record_now_and_stop_api(client, rec, monkeypatch) -> None:
    monkeypatch.setattr(meeting_agent, "process_recording", lambda state: None)

    r = client.post("/api/meetings/record", json={"title": "Call with Ahmad"})
    assert r.status_code == 200 and r.json()["running"] is True
    assert client.post("/api/meetings/record", json={}).status_code == 409  # one at a time
    assert client.get("/api/meetings/recorder").json()["title"] == "Call with Ahmad"

    r = client.post("/api/meetings/record/stop")
    assert r.json()["running"] is False
    assert client.post("/api/meetings/record/stop").status_code == 409


def test_refresh_does_not_touch_recorded_meetings(db, rec, monkeypatch) -> None:
    cal = calendar_meeting()
    meeting = meeting_agent.start_recording(db, "", cal.end, cal)
    monkeypatch.setattr(meeting_client, "list_finished_meetings", lambda db, days: [cal])

    def must_not_fetch(*a):
        raise AssertionError("recorded meetings have no Meet transcript to fetch")

    monkeypatch.setattr(meeting_client, "fetch_transcript", must_not_fetch)
    meeting_agent.refresh(db)

    db.refresh(meeting)
    assert meeting.transcript_status == "recording"


# ---- stop by itself when everybody left ------------------------------------------------------


def test_silence_stops_the_recording_early(db, rec, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(meeting_agent, "stop_recording", lambda: calls.append("stop"))
    now = datetime.now()
    rec.running = True
    rec.state = RecordingState(
        meeting_id=1,
        started_at=now - timedelta(minutes=20),
        scheduled_start=now - timedelta(minutes=19),
        until=now + timedelta(minutes=30),  # the calendar end is still far away
    )

    rec.state.last_voice_at = now - timedelta(minutes=2)  # a short pause: keep going
    assert meeting_agent.recorder_tick(db) == "recording"

    rec.state.last_voice_at = now - timedelta(minutes=6)  # 6 quiet minutes: you left
    assert meeting_agent.recorder_tick(db) == "stopped (silence)"
    assert calls == ["stop"]


def test_before_anybody_talks_it_waits_longer(db, rec, monkeypatch) -> None:
    monkeypatch.setattr(meeting_agent, "stop_recording", lambda: None)
    now = datetime.now()
    rec.running = True
    rec.state = RecordingState(
        meeting_id=1,
        started_at=now - timedelta(minutes=8),
        scheduled_start=now - timedelta(minutes=7),  # people are late: nobody talked yet
        until=now + timedelta(minutes=30),
    )
    assert meeting_agent.recorder_tick(db) == "recording"  # 7 < 10 minutes

    rec.state.started_at = now - timedelta(minutes=12)
    rec.state.scheduled_start = now - timedelta(minutes=11)
    assert meeting_agent.recorder_tick(db) == "stopped (silence)"


# ---- after a restart -----------------------------------------------------------------------------


def test_restart_finishes_a_cut_off_recording(db, rec, monkeypatch, tmp_path) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    folder = tmp_path / "recordings"
    folder.mkdir()
    cut = Meeting(platform="recorded", provider_meeting_id="r1", title="Cut off", date=NOW,
                  attendees=[], transcript_status="transcribing")  # fmt: skip
    lost = Meeting(platform="recorded", provider_meeting_id="r2", title="No files", date=NOW,
                   attendees=[], transcript_status="recording")  # fmt: skip
    db.add_all([cut, lost])
    db.commit()
    (folder / f"meeting{cut.id}-20260929-013032-me.wav").write_bytes(b"x")
    (folder / f"meeting{cut.id}-20260929-013032-others.wav").write_bytes(b"x")

    started = []
    monkeypatch.setattr(meeting_agent, "process_recording", lambda state: started.append(state))
    monkeypatch.setattr(meeting_agent.threading, "Thread", _RunNow)

    assert meeting_agent.recover_unfinished() == 1

    assert started[0].meeting_id == cut.id
    assert started[0].started_at == datetime(2026, 9, 29, 1, 30, 32)
    assert started[0].others_file.name.endswith("-others.wav")
    db.expire_all()
    assert db.get(Meeting, lost.id).transcript_status == "none"


class _RunNow:
    """Runs the thread's work at once (tests do not wait for real threads)."""

    def __init__(self, target, args=(), daemon=None, **kwargs):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


def test_quiet_recording_is_made_louder(tmp_path) -> None:
    import wave

    import numpy as np

    quiet = (np.sin(np.linspace(0, 200, 16000)) * 0.05 * 32767).astype("<i2")  # 5% volume
    path = tmp_path / "quiet.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(quiet.tobytes())

    audio = transcriber.load_audio(path)
    assert 0.85 < float(np.abs(audio).max()) <= 1.0  # now near full volume


def test_meeting_words_reach_whisper_and_the_summary(client, db, rec, monkeypatch) -> None:
    r = client.put(
        "/api/settings",
        json={
            "high_domains": [],
            "low_domains": [],
            "meeting_words": [" HR ", "Al-Noor", "HR", ""],
        },
    )
    assert r.json()["meeting_words"] == ["HR", "Al-Noor"]  # cleaned, no repeats

    seen = {}
    monkeypatch.setattr(
        transcriber,
        "transcribe_meeting",
        lambda me, others, started, name, words: seen.update(words=words) or "Saif jamal: hi",
    )
    prompts = []

    def fake_llm(prompt, schema, **kwargs):
        prompts.append(prompt)
        return LLMJsonResult(data=summary_output(), model="f", input_tokens=1, output_tokens=1)

    monkeypatch.setattr(meeting_agent, "ask_json", fake_llm)
    db.expire_all()
    meeting_agent.start_recording(db, "Words test", NOW + timedelta(hours=1))
    meeting_agent.stop_recording(background=False)

    assert seen["words"] == ["HR", "Al-Noor"]
    assert "HR, Al-Noor" in prompts[0]
