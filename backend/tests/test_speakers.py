"""Who is speaking: the other people's voices are separated ("Speaker 1", "Speaker 2" ...)
and the agent names them. Fake Whisper, voice separation, Google and LLM."""

import wave
from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from app.agents import meeting_agent
from app.models import Meeting
from app.services import google_client, meeting_client, speakers, transcriber
from app.services.llm_client import LLMJsonResult
from tests.test_recorder import FakeRecorder

NOW = datetime.now().replace(microsecond=0)


# ---- which words belong to which voice --------------------------------------------------


def words(*items: tuple[float, float, str]) -> list[speakers.Word]:
    return list(items)


# Omar (voice 0) talks from 0 to 4 s, Ahmad (voice 1) from 4 to 8 s.
TURNS = [(0.0, 4.0, 0), (4.2, 8.0, 1)]


def test_a_sentence_is_split_where_the_voice_changes() -> None:
    segment = words(
        (0.5, 1.0, " أنا"), (1.0, 1.5, " رح"), (1.5, 2.5, " أجهز"), (2.5, 3.5, " العرض."),
        (4.5, 5.0, " وأنا"), (5.0, 6.0, " بعمل"), (6.0, 7.0, " الفاتورة."),
    )  # fmt: skip
    assert speakers.label_segments([segment], TURNS) == [
        (0.5, "Speaker 1", "أنا رح أجهز العرض."),
        (4.5, "Speaker 2", "وأنا بعمل الفاتورة."),
    ]


def test_one_word_of_another_voice_inside_a_sentence_is_a_mistake() -> None:
    turns = [(0.0, 2.0, 0), (2.0, 2.4, 1), (2.4, 6.0, 0)]  # a short wrong turn in the middle
    segment = words((0.5, 1.5, " We"), (1.5, 2.0, " will"), (2.0, 2.4, " send"), (2.4, 3.0, " it."))
    assert speakers.label_segments([segment], turns) == [(0.5, "Speaker 1", "We will send it.")]


def test_a_word_in_a_small_gap_goes_to_the_nearest_voice() -> None:
    assert speakers.speaker_at(4.05, 4.15, TURNS) in (0, 1)
    assert speakers.speaker_at(20.0, 21.0, TURNS) is None  # far from any voice


# ---- the other people's track -----------------------------------------------------------


def _wav(path, seconds=3) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes((np.sin(np.linspace(0, 900, 16000 * seconds)) * 8000).astype("<i2").tobytes())


def _segment(start, end, text, word_list):
    return SimpleNamespace(
        start=start,
        end=end,
        text=text,
        words=[SimpleNamespace(start=s, end=e, word=w) for s, e, w in word_list],
    )


@pytest.fixture
def others_track(tmp_path, monkeypatch):
    path = tmp_path / "others.wav"
    _wav(path)
    fake_segments = [
        _segment(
            0.5, 3.5, "أنا رح أجهز العرض.", [(0.5, 2.0, " أنا رح"), (2.0, 3.5, " أجهز العرض.")]
        ),
        _segment(4.5, 7.0, "تمام.", [(4.5, 7.0, " تمام.")]),
    ]
    monkeypatch.setattr(
        transcriber, "_whisper", lambda audio, w, word_timestamps=False: fake_segments
    )
    return path


def test_others_track_gets_one_label_per_voice(others_track, monkeypatch) -> None:
    monkeypatch.setattr(speakers, "diarize", lambda audio: TURNS)
    assert transcriber.transcribe_others(others_track) == [
        (0.5, "Speaker 1", "أنا رح أجهز العرض."),
        (4.5, "Speaker 2", "تمام."),
    ]


def test_others_track_stays_others_when_separation_fails(others_track, monkeypatch) -> None:
    def broken(audio):
        raise RuntimeError("no model")

    monkeypatch.setattr(speakers, "diarize", broken)
    lines = transcriber.transcribe_others(others_track)
    assert [who for _, who, _ in lines] == ["Others", "Others"]  # the text is never lost


def test_separation_can_be_switched_off(others_track, monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "speaker_separation", False)
    monkeypatch.setattr(speakers, "diarize", lambda audio: pytest.fail("must not run"))
    assert [who for _, who, _ in transcriber.transcribe_others(others_track)] == ["Others"] * 2


# ---- who joined the call -> names for the voices -----------------------------------------


def test_fetch_participants_from_google_meet(db, monkeypatch) -> None:
    from tests.test_meeting_agent import FakeMeet

    monkeypatch.setattr(google_client, "service", lambda db, name, version: FakeMeet())
    names = meeting_client.fetch_participants(db, "abc-mnop-xyz", NOW, NOW + timedelta(hours=1))
    assert names == ["Omar", "Sara"]


def test_recorded_meet_call_names_the_voices(client, db, monkeypatch) -> None:
    monkeypatch.setattr(meeting_agent, "recorder", FakeRecorder())
    monkeypatch.setattr(google_client, "account", lambda db: ("saif@gmail.com", "Saif jamal"))
    monkeypatch.setattr(
        transcriber,
        "transcribe_meeting",
        lambda *a: "[10:00] Saif jamal: شو رأيك يا عمر؟\n[10:01] Speaker 1: أنا رح أجهز العرض.",
    )
    monkeypatch.setattr(
        meeting_client,
        "fetch_participants",
        lambda db, code, start, end: ["Saif jamal", "Omar Ali"],
    )
    output = meeting_agent.MeetingOutput(
        overview="Offer.",
        detected_language="ar",
        action_items=[
            meeting_agent.ActionItem(
                task="Prepare the offer", owner="Omar Ali", owner_is_me=False, due=""
            )
        ],
        decisions=[],
        risks=[],
        blockers=[],
        keywords=["العرض"],
        speakers=[
            meeting_agent.SpeakerName(
                label="Speaker 1", name="Omar Ali", clue="answered when called Omar"
            )
        ],
    )
    prompts = []

    def fake_llm(prompt, schema, **kwargs):
        prompts.append(prompt)
        return LLMJsonResult(data=output, model="f", input_tokens=1, output_tokens=1)

    monkeypatch.setattr(meeting_agent, "ask_json", fake_llm)
    cal = meeting_client.CalendarMeeting(
        event_id="e1", title="Offer call", start=NOW, end=NOW + timedelta(minutes=30),
        meeting_code="abc-mnop-xyz", organizer="saif@gmail.com",
    )  # fmt: skip

    meeting = meeting_agent.start_recording(db, "", cal.end, cal)
    meeting_agent.stop_recording(background=False)

    assert "Joined the call (Google Meet): Saif jamal, Omar Ali" in prompts[0]
    db.expire_all()
    assert db.get(Meeting, meeting.id).participants == ["Saif jamal", "Omar Ali"]
    body = client.get(f"/api/meetings/{meeting.id}").json()
    assert body["participants"] == ["Saif jamal", "Omar Ali"]
    assert body["summary"]["speakers"] == [
        {"label": "Speaker 1", "name": "Omar Ali", "clue": "answered when called Omar"}
    ]
    assert body["tasks"] == []  # Omar's task is not in my Daily Tasks


def test_no_names_without_a_meet_code(db, monkeypatch) -> None:
    """Zoom, Teams and "Record now" have no Meet code: nobody is looked up."""
    monkeypatch.setattr(
        meeting_client, "fetch_participants", lambda *a: pytest.fail("must not call Google")
    )
    meeting = Meeting(
        platform="recorded", provider_meeting_id="r1", title="Zoom", date=NOW, attendees=[]
    )
    assert meeting_agent._joined_the_call(db, meeting) == []
