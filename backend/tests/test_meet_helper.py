"""The Google Meet helper (browser extension): pairing, captions, recording from join to
leave, and naming the voices from Google Meet's captions. Fake recorder, Google and LLM."""

import time
from datetime import datetime, timedelta

import pytest

from app.agents import meeting_agent
from app.models import MeetCaption, Meeting
from app.services import google_client, meet_helper, meeting_client, transcriber
from app.services.app_settings import get_app_settings
from app.services.llm_client import LLMJsonResult
from tests.test_recorder import NOW as REC_NOW
from tests.test_recorder import FakeRecorder

CODE = "abc-mnop-xyz"


def ms(when: datetime) -> int:
    return int(when.timestamp() * 1000)


@pytest.fixture
def key(client) -> dict:
    return {"X-Portal-Extension": client.get("/api/extension/pair").json()["key"]}


@pytest.fixture
def rec(monkeypatch) -> FakeRecorder:
    fake = FakeRecorder()
    monkeypatch.setattr(meeting_agent, "recorder", fake)
    monkeypatch.setattr(google_client, "account", lambda db: ("saif@gmail.com", "Saif jamal"))
    monkeypatch.setattr(meeting_agent, "_left_at", {})
    monkeypatch.setattr(meeting_agent, "_in_call_at", {})
    return fake


def calendar(start: datetime, code: str = CODE) -> meeting_client.CalendarMeeting:
    return meeting_client.CalendarMeeting(
        event_id="evt-qa", title="Daily QA meeting", start=start, end=start + timedelta(minutes=30),
        meeting_code=code, organizer="saif@gmail.com", attendees=[],
    )  # fmt: skip


@pytest.fixture
def auto_record(db) -> None:
    get_app_settings(db).auto_record = True
    db.commit()


# ---- pairing and the key ----------------------------------------------------------------


def test_the_portal_page_gives_the_key(client) -> None:
    key = client.get("/api/extension/pair").json()["key"]
    assert meet_helper.key_ok(key) and not meet_helper.key_ok("wrong")


def test_extension_calls_need_the_key(client, key) -> None:
    body = {"meeting_code": CODE, "lines": []}
    assert client.post("/api/extension/captions", json=body).status_code == 401
    wrong = {"X-Portal-Extension": "not-the-key"}
    assert client.post("/api/extension/captions", json=body, headers=wrong).status_code == 401
    assert client.post("/api/extension/captions", json=body, headers=key).status_code == 200
    assert client.post("/api/extension/hello", headers=key).status_code == 200
    assert client.get("/api/extension/status").json()["active"] is True


def test_with_the_portal_login_on(client, key, monkeypatch) -> None:
    """The key is only given to the logged-in portal; the extension's calls use the key."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "portal_password", "a-test-password")
    assert client.get("/api/extension/pair").status_code == 401  # not logged in: no key
    assert client.get("/api/extension/status").status_code == 401
    assert client.post("/api/extension/hello", headers=key).status_code == 200
    assert client.post("/api/extension/hello").status_code == 401  # no key: no entry


def test_caption_lines_are_saved_and_updated(client, db, key) -> None:
    now = datetime.now()
    line = {"id": "l1", "name": "Sami Kharroub", "start": ms(now), "end": ms(now), "text": "خلصت"}
    client.post(
        "/api/extension/captions", json={"meeting_code": CODE, "lines": [line]}, headers=key
    )
    grown = {**line, "end": ms(now + timedelta(seconds=4)), "text": "خلصت الـ API documentation"}
    client.post(
        "/api/extension/captions", json={"meeting_code": CODE, "lines": [grown]}, headers=key
    )

    row = db.query(MeetCaption).one()  # the same line, updated - not a second one
    assert row.text == "خلصت الـ API documentation"
    assert (row.end - row.start).total_seconds() == pytest.approx(4, abs=0.01)


def test_a_bad_meeting_code_is_refused(client, key) -> None:
    body = {"meeting_code": "../../etc", "lines": []}
    assert client.post("/api/extension/captions", json=body, headers=key).status_code == 422


# ---- record from joining to leaving -----------------------------------------------------------


def _call(client, key, state: str, at: datetime | None = None) -> dict:
    body = {"meeting_code": CODE, "state": state, "at": ms(at or datetime.now())}
    return client.post("/api/extension/call", json=body, headers=key).json()


def test_joining_starts_and_leaving_stops_the_recording(
    client, db, key, rec, auto_record, monkeypatch
) -> None:
    cal = calendar(datetime.now() + timedelta(minutes=10))  # you joined 10 minutes early
    monkeypatch.setattr(meeting_client, "list_current_meetings", lambda db, early_seconds: [cal])
    stopped = []
    monkeypatch.setattr(meeting_agent, "stop_recording", lambda: stopped.append(True))

    assert _call(client, key, "joined")["recorder"] == "started"
    meeting = db.query(Meeting).one()
    assert (meeting.title, meeting.meeting_code) == ("Daily QA meeting", CODE)

    _call(client, key, "left")
    assert meeting_agent.recorder_tick(db) == "recording"  # maybe a page reload: wait a bit
    meeting_agent._left_at[CODE] = datetime.now() - timedelta(minutes=2)
    assert meeting_agent.recorder_tick(db) == "stopped (left the call)"
    assert stopped == [True]


def test_coming_back_after_the_stop_records_part_2(client, db, key, rec, auto_record, monkeypatch):
    cal = calendar(datetime.now() - timedelta(minutes=5))
    monkeypatch.setattr(meeting_client, "list_current_meetings", lambda db, early_seconds: [cal])
    _call(client, key, "joined")
    first = db.query(Meeting).one()
    rec.stop()
    first.transcript_status = "ready"  # the first part was transcribed
    db.commit()

    assert _call(client, key, "joined")["recorder"] == "started"
    titles = sorted(m.title for m in db.query(Meeting).all())
    assert titles == ["Daily QA meeting", "Daily QA meeting (part 2)"]  # part 1 is kept


def test_a_call_not_in_the_calendar_is_recorded_too(client, db, key, rec, auto_record, monkeypatch):
    monkeypatch.setattr(meeting_client, "list_current_meetings", lambda db, early_seconds: [])
    assert _call(client, key, "joined")["recorder"] == "started"
    meeting = db.query(Meeting).one()
    assert (meeting.title, meeting.meeting_code) == (f"Google Meet {CODE}", CODE)


def test_an_old_join_message_does_not_start_a_recording(client, db, key, rec, auto_record) -> None:
    old = datetime.now() - timedelta(minutes=30)  # the portal was off during the call
    assert _call(client, key, "joined", at=old)["recorder"] == "too old - ignored"
    assert rec.running is False


def test_no_recording_when_auto_record_is_off(client, key, rec) -> None:
    assert _call(client, key, "joined")["recorder"] == "off"
    assert rec.running is False


def test_with_the_extension_the_calendar_waits_for_you_to_join(db, rec, auto_record, monkeypatch):
    meet_helper.seen(db)  # the extension is installed and working
    db.commit()
    cal = calendar(datetime.now() - timedelta(minutes=1))
    monkeypatch.setattr(meeting_client, "list_current_meetings", lambda db, early_seconds=0: [cal])

    assert meeting_agent.recorder_tick(db) == "idle"  # no recording before you join

    cal.start = datetime.now() - timedelta(minutes=6)  # you never joined on this computer
    assert meeting_agent.recorder_tick(db) == "started"  # the calendar is the safety net


def test_still_in_the_call_keeps_recording_after_the_calendar_end(db, rec, monkeypatch) -> None:
    meeting = Meeting(
        platform="recorded", provider_meeting_id="p1", title="QA", date=datetime.now(),
        attendees=[], meeting_code=CODE, transcript_status="recording",
    )  # fmt: skip
    db.add(meeting)
    db.commit()
    rec.running = True
    rec.state.meeting_id = meeting.id
    rec.state.until = datetime.now() - timedelta(minutes=1)  # the calendar end has passed
    meeting_agent.meet_call(db, CODE, "in_call")
    assert meeting_agent.recorder_tick(db) == "recording"


# ---- naming the voices from the captions --------------------------------------------------------


def _caption(name: str, start: float, end: float, base: datetime, text: str = "...") -> MeetCaption:
    return MeetCaption(
        meeting_code=CODE, client_id=f"{name}{start}", name=name, text=text,
        start=base + timedelta(seconds=start), end=base + timedelta(seconds=end),
    )  # fmt: skip


def test_voices_get_the_names_google_meet_shows() -> None:
    base = datetime(2026, 9, 30, 13, 15)
    captions = [
        _caption("Sami Kharroub", 11, 21, base),
        _caption("You", 21, 25, base),  # the user's own captions are not a voice here
        _caption("hala bassam", 31, 41, base),
    ]
    times = {"Speaker 1": [(10.0, 20.0)], "Speaker 2": [(30.0, 40.0)], "Speaker 3": [(60.0, 61.0)]}
    found = meet_helper.name_voices(times, base, captions, "Saif jamal")
    assert {label: v["name"] for label, v in found.items()} == {
        "Speaker 1": "Sami Kharroub",
        "Speaker 2": "hala bassam",
    }  # Speaker 3 talked when no caption showed: no name


def test_a_long_open_caption_box_does_not_hide_others() -> None:
    """The real meeting of 1 Oct: Meet kept Durrah's caption box open for 17 minutes. Its
    "spans" say when her words really grew, so Fahad, who spoke in between, gets his name."""
    base = datetime(2026, 10, 1, 13, 37)

    def at(seconds: float) -> int:
        return ms(base + timedelta(seconds=seconds))

    durrah = _caption("Durrah Dahash", 0, 17 * 60, base)  # one box from 13:37 to 13:54
    durrah.spans = [[at(0), at(400)], [at(460), at(1020)]]  # quiet from 400 s to 460 s
    fahad = _caption("Fahad Aljuaylan", 405, 455, base)
    times = {"Speaker 1": [(406.0, 454.0)], "Speaker 2": [(10.0, 390.0), (470.0, 1000.0)]}

    found = meet_helper.name_voices(times, base, [durrah, fahad], "Saif jamal")
    assert {label: v["name"] for label, v in found.items()} == {
        "Speaker 1": "Fahad Aljuaylan",
        "Speaker 2": "Durrah Dahash",
    }


def test_spans_are_saved_from_the_extension(client, db, key) -> None:
    now = datetime.now()
    line = {
        "id": "s1", "name": "Durrah Dahash", "text": "...",
        "start": ms(now), "end": ms(now + timedelta(seconds=60)),
        "spans": [[ms(now), ms(now + timedelta(seconds=5))]],
    }  # fmt: skip
    client.post(
        "/api/extension/captions", json={"meeting_code": CODE, "lines": [line]}, headers=key
    )
    assert db.query(MeetCaption).one().spans == [[ms(now), ms(now + timedelta(seconds=5))]]


def test_a_voice_between_two_people_gets_no_name() -> None:
    base = datetime(2026, 9, 30, 13, 15)
    captions = [_caption("Sami", 11, 16, base), _caption("Hala", 16, 21, base)]
    found = meet_helper.name_voices({"Speaker 1": [(10.0, 20.0)]}, base, captions, "Saif")
    assert found == {}  # half Sami, half Hala: not sure


def test_recorded_call_is_named_from_the_captions(client, db, rec, monkeypatch) -> None:
    for c in (
        _caption("Sami Kharroub", 6, 16, REC_NOW, "الأسبوع خلصت الAPI documentation"),
        _caption("Saif jamal", 20, 25, REC_NOW, "يعطيك العافية"),
    ):
        db.add(c)
    db.commit()
    monkeypatch.setattr(
        transcriber,
        "transcribe_meeting",
        lambda *a, **k: transcriber.Transcript(
            "[13:15] Speaker 1: الأسبوع خلصت الAPI documentation.\n[13:15] Saif jamal: يعطيك",
            times={"Speaker 1": [(5.0, 15.0)]},
        ),
    )
    monkeypatch.setattr(
        meeting_client, "fetch_participants", lambda *a: ["Saif jamal", "Sami Kharroub"]
    )
    prompts = []

    def fake_llm(prompt, schema, **kwargs):
        prompts.append(prompt)
        output = meeting_agent.MeetingOutput(
            overview="QA sync.", detected_language="mixed", action_items=[], decisions=[],
            risks=[], blockers=[], keywords=["API"],
        )  # fmt: skip
        return LLMJsonResult(data=output, model="f", input_tokens=1, output_tokens=1)

    monkeypatch.setattr(meeting_agent, "ask_json", fake_llm)
    meeting = meeting_agent.start_recording(
        db, "", REC_NOW + timedelta(minutes=30), calendar(REC_NOW)
    )
    rec.state.seconds = 60  # a one-minute recording
    meeting_agent.stop_recording(background=False)

    db.expire_all()
    meeting = db.get(Meeting, meeting.id)
    assert meeting.meet_names["Speaker 1"]["name"] == "Sami Kharroub"
    assert "Speaker 1 = Sami Kharroub" in prompts[0]
    assert "<captions>" in prompts[0] and "Sami Kharroub: الأسبوع خلصت" in prompts[0]
    speaker = meeting.summary.speakers[0]
    assert (speaker["name"], speaker["how"], speaker["sure"]) == ("Sami Kharroub", "meet", True)


def test_delete_my_data_also_deletes_captions(client, db) -> None:
    db.add(_caption("Sami", 1, 2, datetime.now()))
    db.commit()
    counts = client.request("DELETE", "/api/data", json={"confirm": "DELETE"}).json()["deleted"]
    assert counts["meet_captions"] == 1


def test_times_are_the_browser_clock() -> None:
    now = time.time()
    assert abs(meet_helper._time(int(now * 1000)).timestamp() - now) < 0.01
