"""Who is speaking: the other people's voices are separated ("Speaker 1", "Speaker 2" ...),
named by the agent and by the voice memory - and another person's task never becomes mine.
Fake Whisper, voice separation, voice prints, Google and LLM."""

import wave
from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from app.agents import meeting_agent
from app.models import Meeting, MeetingVoice, Task, VoicePrint
from app.services import google_client, meeting_client, speakers, transcriber, voice_memory
from app.services.app_settings import get_app_settings
from app.services.crypto import decrypt
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


def _voice(seed: int) -> np.ndarray:
    v = np.random.default_rng(seed).normal(size=192)
    return v / np.linalg.norm(v)


def _like(voice: np.ndarray, seed: int) -> list[float]:
    """The same person in another meeting: nearly the same voice print."""
    v = voice + np.random.default_rng(seed).normal(size=192) * 0.03
    return (v / np.linalg.norm(v)).tolist()


OMAR, AHMAD = _voice(1), _voice(2)


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
    monkeypatch.setattr(speakers, "voice_prints", lambda audio, turns: {0: OMAR})
    return path


def test_others_track_gets_one_label_per_voice(others_track, monkeypatch) -> None:
    monkeypatch.setattr(speakers, "diarize", lambda audio: TURNS)
    track = transcriber.transcribe_others(others_track)
    assert track.lines == [
        (0.5, "Speaker 1", "أنا رح أجهز العرض."),
        (4.5, "Speaker 2", "تمام."),
    ]
    assert list(track.voices) == ["Speaker 1"]  # Speaker 2 said too little for a voice print


def test_others_track_stays_others_when_separation_fails(others_track, monkeypatch) -> None:
    def broken(audio):
        raise RuntimeError("no model")

    monkeypatch.setattr(speakers, "diarize", broken)
    track = transcriber.transcribe_others(others_track)
    assert [who for _, who, _ in track.lines] == ["Others", "Others"]  # the text is never lost
    assert track.voices == {}


def test_separation_can_be_switched_off(others_track, monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "speaker_separation", False)
    monkeypatch.setattr(speakers, "diarize", lambda audio: pytest.fail("must not run"))
    track = transcriber.transcribe_others(others_track)
    assert [who for _, who, _ in track.lines] == ["Others"] * 2


# ---- one person, one label -----------------------------------------------------------------

AUDIO = np.zeros(16000 * 60, dtype=np.float32)  # the prints are faked, the audio is not used


def _fake_prints(monkeypatch, prints: dict[int, np.ndarray]) -> None:
    monkeypatch.setattr(speakers, "voice_prints", lambda audio, turns, min_seconds=2: dict(prints))


def test_labels_with_the_same_voice_are_merged(monkeypatch) -> None:
    # The separation gave 4 labels: 0 and 2 are Sami, 1 and 3 are Ahmad.
    _fake_prints(
        monkeypatch, {0: OMAR, 1: AHMAD, 2: np.array(_like(OMAR, 7)), 3: np.array(_like(AHMAD, 8))}
    )
    turns = [(0, 5, 0), (5, 9, 1), (9, 14, 2), (14, 20, 3)]
    assert speakers.merge_voices(AUDIO, turns) == [(0, 5, 0), (5, 9, 1), (9, 14, 0), (14, 20, 1)]


def test_never_more_voices_than_people_in_the_call(monkeypatch) -> None:
    third = _voice(3)  # a different-sounding piece of the same person
    _fake_prints(monkeypatch, {0: OMAR, 1: AHMAD, 2: third})
    turns = [(0, 5, 0), (5, 9, 1), (9, 14, 2)]
    assert len({n for *_, n in speakers.merge_voices(AUDIO, turns)}) == 3  # not similar: kept
    assert len({n for *_, n in speakers.merge_voices(AUDIO, turns, max_voices=2)}) == 2


def test_a_tiny_label_joins_the_voice_next_to_it(monkeypatch) -> None:
    _fake_prints(monkeypatch, {0: OMAR, 1: AHMAD})  # label 2 said only "سامعيني": no print
    turns = [(0, 5, 0), (5.6, 5.9, 2), (6, 12, 1)]
    merged = speakers.merge_voices(AUDIO, turns)
    assert merged[1][2] == merged[2][2]  # "سامعيني" belongs to the voice right after it


# ---- "sure" is checked, not trusted --------------------------------------------------------

TRANSCRIPT = (
    "[13:16] Saif jamal: بلش يا سامي\n"
    "[13:16] Speaker 1: الأسبوع خلصت الAPI documentation.\n"
    "[13:17] Speaker 2: مرحبا، معكم أحمد. بلشت التكنيكال داشبورد."
)


def _sure(found: list[dict], others: int) -> list[bool]:
    meeting_agent._check_sure(found, TRANSCRIPT, others)
    return [s["sure"] for s in found]


def test_sure_only_when_the_person_says_their_own_name() -> None:
    found = [
        {"label": "Speaker 1", "name": "Sami", "name_quote": "", "how": "talk"},  # was called
        {"label": "Speaker 2", "name": "Ahmad", "name_quote": "معكم احمد", "how": "talk"},
    ]
    assert _sure(found, others=3) == [False, True]  # spelling أحمد/احمد does not matter


def test_a_quote_from_another_line_is_not_believed() -> None:
    found = [{"label": "Speaker 1", "name": "Sami", "name_quote": "بلش يا سامي", "how": "talk"}]
    assert _sure(found, others=3) == [False]  # those were the user's words, not Sami's


def test_sure_when_only_one_other_person_joined() -> None:
    found = [{"label": "Speaker 1", "name": "Sami", "name_quote": "", "how": "talk"}]
    assert _sure(found, others=1) == [True]


def test_a_task_for_everyone_is_never_mine(db, me, monkeypatch) -> None:
    item = meeting_agent.ActionItem(task="Make a plan", owner="Everyone", owner_is_me=True, due="")
    _fake_llm(monkeypatch, _output([item]))
    meeting_agent.summarize(db, _recorded(db, participants=["Saif jamal", "Sami"]))
    assert db.query(Task).count() == 0


# ---- echo: the others' voices on my microphone ---------------------------------------------


def test_echo_on_my_microphone_is_removed() -> None:
    heard = words(
        (10.1, 10.5, " I"), (10.5, 11.0, " will"), (11.0, 11.6, " send"), (11.6, 12.2, " the"),
        (12.2, 12.8, " contract"), (12.8, 13.1, " tomorrow."),
    )  # fmt: skip
    mine = words(
        (10.0, 13.0, " I will send the contract tomorrow."),  # Omar's voice through my mic
        (15.0, 17.0, " OK, I will send the contract tomorrow then."),  # my real answer, later
        (20.0, 20.5, " OK."),  # too short to judge: kept
    )
    kept, dropped = transcriber.remove_echo(mine, heard)
    assert dropped == 1
    assert [t for t, _ in kept] == [15.0, 20.0]


def test_arabic_echo_with_other_spelling_is_removed() -> None:
    heard = words((5.0, 8.0, " انا رح ابعت العقد بكره"))  # the same words, other spelling
    kept, dropped = transcriber.remove_echo(words((5.2, 8.1, " أنا رح أبعت العقد بكرة")), heard)
    assert (kept, dropped) == ([], 1)


def test_meeting_transcript_without_echo_and_with_voices(monkeypatch) -> None:
    others = transcriber.OthersTrack(
        lines=[(10.0, "Speaker 1", "I will send the contract tomorrow.")],
        heard=words((10.0, 13.0, " I will send the contract tomorrow.")),
        voices={"Speaker 1": OMAR.tolist()},
    )
    monkeypatch.setattr(transcriber, "transcribe_others", lambda path, w=None, n=None: others)
    monkeypatch.setattr(
        transcriber,
        "transcribe_mine",
        lambda path, w=None: words((10.2, 13.0, " I will send the contract tomorrow.")),
    )
    result = transcriber.transcribe_meeting(None, None, datetime(2026, 9, 30, 10, 0), "Saif jamal")
    assert result.text == "[10:00] Speaker 1: I will send the contract tomorrow."  # not "Saif"
    assert result.echo_removed == 1
    assert list(result.voices) == ["Speaker 1"]


# ---- who joined the call -> names for the voices -----------------------------------------


def test_fetch_participants_from_google_meet(db, monkeypatch) -> None:
    from tests.test_meeting_agent import FakeMeet

    monkeypatch.setattr(google_client, "service", lambda db, name, version: FakeMeet())
    names = meeting_client.fetch_participants(db, "abc-mnop-xyz", NOW, NOW + timedelta(hours=1))
    assert names == ["Omar", "Sara"]


def _output(items=(), found=()) -> meeting_agent.MeetingOutput:
    return meeting_agent.MeetingOutput(
        overview="Offer.",
        detected_language="ar",
        action_items=list(items),
        decisions=[],
        risks=[],
        blockers=[],
        keywords=["العرض"],
        speakers=list(found),
    )


def _fake_llm(monkeypatch, output) -> list[str]:
    prompts = []

    def fake(prompt, schema, **kwargs):
        prompts.append(prompt)
        return LLMJsonResult(data=output, model="f", input_tokens=1, output_tokens=1)

    monkeypatch.setattr(meeting_agent, "ask_json", fake)
    return prompts


@pytest.fixture
def me(monkeypatch) -> None:
    monkeypatch.setattr(google_client, "account", lambda db: ("saif@gmail.com", "Saif jamal"))


def test_recorded_meet_call_names_the_voices(client, db, me, monkeypatch) -> None:
    monkeypatch.setattr(meeting_agent, "recorder", FakeRecorder())
    asked = {}

    def fake_transcribe(*a, max_voices=None):
        asked["max_voices"] = max_voices
        return transcriber.Transcript(
            "[10:00] Saif jamal: شو رأيك يا عمر؟\n[10:01] Speaker 1: أنا رح أجهز العرض."
        )

    monkeypatch.setattr(transcriber, "transcribe_meeting", fake_transcribe)
    monkeypatch.setattr(
        meeting_client,
        "fetch_participants",
        lambda db, code, start, end: ["Saif jamal", "Omar Ali"],
    )
    item = meeting_agent.ActionItem(
        task="Prepare the offer", owner="Omar Ali", owner_is_me=False, due=""
    )
    found = meeting_agent.SpeakerName(label="Speaker 1", name="Omar Ali", clue="answered to Omar")
    prompts = _fake_llm(monkeypatch, _output([item], [found]))
    cal = meeting_client.CalendarMeeting(
        event_id="e1", title="Offer call", start=NOW, end=NOW + timedelta(minutes=30),
        meeting_code="abc-mnop-xyz", organizer="saif@gmail.com",
    )  # fmt: skip

    meeting = meeting_agent.start_recording(db, "", cal.end, cal)
    meeting_agent.stop_recording(background=False)

    assert asked["max_voices"] == 1  # one other person joined: never more than one voice
    assert "Joined the call (Google Meet): Saif jamal, Omar Ali" in prompts[0]
    body = client.get(f"/api/meetings/{meeting.id}").json()
    assert body["participants"] == ["Saif jamal", "Omar Ali"]
    assert body["summary"]["speakers"] == [  # sure: the only other person in the call
        {"label": "Speaker 1", "name": "Omar Ali", "clue": "answered to Omar", "sure": True,
         "how": "talk"}
    ]  # fmt: skip
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


# ---- the most important rule: never another person's task in my Daily Tasks ----------------


def _recorded(db, n: int = 1, participants=None, text=None) -> Meeting:
    meeting = Meeting(
        platform="recorded", provider_meeting_id=f"m{n}", title=f"Call {n}", date=NOW,
        attendees=[], participants=participants or [], transcript_status="ready",
        transcript_text=text or "[10:00] Speaker 1: ...\n[10:01] Saif jamal: ...",
    )  # fmt: skip
    db.add(meeting)
    db.commit()
    return meeting


def test_another_persons_task_never_becomes_mine(db, me, monkeypatch) -> None:
    def item(task, owner):  # the LLM wrongly says "mine" for the first three
        return meeting_agent.ActionItem(task=task, owner=owner, owner_is_me=True, due="")

    items = [
        item("Send the contract", "Omar Ali"),
        item("Book the room", "Speaker 2"),
        item("Write the texts", "Unassigned"),
        item("Send the price offer", "Saif jamal"),
    ]
    _fake_llm(monkeypatch, _output(items))
    meeting = _recorded(db, participants=["Saif jamal", "Omar Ali"])

    summary = meeting_agent.summarize(db, meeting)

    assert [t.title for t in db.query(Task).all()] == ["Send the price offer"]
    assert [i["owner_is_me"] for i in summary.action_items] == [False, False, False, True]


# ---- voice memory ------------------------------------------------------------------------


@pytest.fixture
def remember(db) -> None:
    get_app_settings(db).remember_voices = True
    db.commit()


def test_voice_memory_is_off_by_default(db) -> None:
    meeting = _recorded(db)
    assert voice_memory.save_meeting_voices(db, meeting, {"Speaker 1": OMAR.tolist()}) == {}
    assert db.query(MeetingVoice).count() == 0  # no voice print is kept


def test_best_match_needs_a_clear_winner() -> None:
    twin = np.array(_like(OMAR, 9))
    assert speakers.best_match(np.array(_like(OMAR, 3)), {"Omar": OMAR}, 0.6)[0] == "Omar"
    assert speakers.best_match(AHMAD, {"Omar": OMAR}, 0.6)[0] is None  # a stranger
    both = {"Omar": OMAR, "Omar's twin": twin}
    assert speakers.best_match(np.array(_like(OMAR, 3)), both, 0.6)[0] is None  # not clear


def test_a_sure_name_is_learned_and_recognized_next_time(db, me, remember, monkeypatch) -> None:
    first = _recorded(
        db, 1, text="[10:00] Speaker 1: مرحبا، معكم عمر.\n[10:01] Speaker 2: تمام، ماشي."
    )
    voice_memory.save_meeting_voices(
        db, first, {"Speaker 1": OMAR.tolist(), "Speaker 2": AHMAD.tolist()}
    )
    sure = meeting_agent.SpeakerName(
        label="Speaker 1", name="Omar Ali", clue="said معكم عمر", name_quote="معكم عمر"
    )
    guess = meeting_agent.SpeakerName(label="Speaker 2", name="Ahmad", clue="maybe")
    _fake_llm(monkeypatch, _output(found=[sure, guess]))
    meeting_agent.summarize(db, first)

    assert [v.name for v in db.query(VoicePrint).all()] == ["Omar Ali"]  # a guess is not learned

    second = _recorded(db, 2)
    found = voice_memory.save_meeting_voices(
        db, second, {"Speaker 1": _like(AHMAD, 4), "Speaker 2": _like(OMAR, 5)}
    )
    assert list(found) == ["Speaker 2"] and found["Speaker 2"][0] == "Omar Ali"

    prompts = _fake_llm(monkeypatch, _output())  # nobody says a name in this meeting
    summary = meeting_agent.summarize(db, second)
    assert "Voices already known (" in prompts[0]
    assert "Speaker 2 = Omar Ali" in prompts[0]
    assert summary.speakers[0]["label"] == "Speaker 2"
    assert (summary.speakers[0]["name"], summary.speakers[0]["how"]) == ("Omar Ali", "voice")


def test_naming_a_voice_once_fixes_the_summary_and_is_remembered(client, db, remember, monkeypatch):
    meeting = _recorded(db)
    voice_memory.save_meeting_voices(db, meeting, {"Speaker 2": AHMAD.tolist()})
    task = meeting_agent.ActionItem(
        task="Book the room", owner="Speaker 2", owner_is_me=False, due=""
    )
    _fake_llm(monkeypatch, _output([task]))
    meeting_agent.summarize(db, meeting)

    r = client.post(
        f"/api/meetings/{meeting.id}/voices", json={"label": "Speaker 2", "name": "Ahmad"}
    )

    body = r.json()
    assert r.status_code == 200
    assert body["summary"]["action_items"][0]["owner"] == "Ahmad"
    assert body["summary"]["action_items"][0]["owner_is_me"] is False  # never mine by naming
    assert body["summary"]["speakers"][0]["how"] == "you"
    assert [v["name"] for v in client.get("/api/voices").json()] == ["Ahmad"]

    # A wrong name is corrected: the voice leaves "Ahmad" and goes to "Khaled"
    client.post(f"/api/meetings/{meeting.id}/voices", json={"label": "Speaker 2", "name": "Khaled"})
    assert [v["name"] for v in client.get("/api/voices").json()] == ["Khaled"]


def test_voice_prints_are_encrypted(db, remember) -> None:
    voice_memory.remember(db, "Omar", OMAR)
    db.commit()
    stored = db.query(VoicePrint).one().print_encrypted
    assert stored.startswith("gAAAA") and "0." not in stored  # Fernet token, no numbers
    assert len(decrypt(stored)) > 100


def test_voices_can_be_deleted(client, db, remember) -> None:
    voice_memory.remember(db, "Omar", OMAR)
    voice_memory.remember(db, "Ahmad", AHMAD)
    db.commit()
    voices = client.get("/api/voices").json()
    assert client.delete(f"/api/voices/{voices[0]['id']}").status_code == 200
    assert len(client.get("/api/voices").json()) == 1
    assert client.delete("/api/voices").json() == {"deleted": 1}
    assert client.get("/api/voices").json() == []


def test_delete_my_data_also_deletes_voices(client, db, remember) -> None:
    voice_memory.save_meeting_voices(db, _recorded(db), {"Speaker 1": OMAR.tolist()})
    voice_memory.remember(db, "Omar", OMAR)
    db.commit()
    counts = client.request("DELETE", "/api/data", json={"confirm": "DELETE"}).json()["deleted"]
    assert counts["voice_prints"] == 1 and counts["meeting_voices"] == 1


def test_the_voice_name_label_is_checked(client, db) -> None:
    meeting = _recorded(db)
    r = client.post(f"/api/meetings/{meeting.id}/voices", json={"label": "<b>x</b>", "name": "A"})
    assert r.status_code == 422
