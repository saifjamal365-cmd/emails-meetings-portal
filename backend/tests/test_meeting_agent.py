"""Meeting agent tests: transcripts (fake Google), summary (fake LLM), tasks and the API."""

from datetime import datetime, timedelta

from app.agents import meeting_agent
from app.agents.meeting_agent import ActionItem, MeetingOutput
from app.models import Meeting, Task
from app.services import google_client, meeting_client
from app.services.llm_client import LLMJsonResult

VTT = """WEBVTT

1
00:00:01.000 --> 00:00:04.000
<v Omar>مرحبا جميعاً، نبدأ بعقد ACME</v>

2
00:00:04.000 --> 00:00:08.000
<v Sara>I will send the price list by Thursday.</v>

3
00:00:04.000 --> 00:00:08.000
<v Sara>I will send the price list by Thursday.</v>
"""

OUTPUT = MeetingOutput(
    overview="The team discussed the ACME contract and the price list.",
    detected_language="mixed",
    action_items=[
        ActionItem(task="Send the price list to ACME", owner="Sara", owner_is_me=True, due=""),
        ActionItem(task="Book the meeting room", owner="Omar", owner_is_me=False, due=""),
    ],
    decisions=["Launch moved to 15 October"],
    risks=["Supplier may be late"],
    blockers=["Waiting for legal approval"],
    keywords=["ACME", "Project Falcon", "العقد", "contract"],
)


def fake_llm(prompt, schema, **kwargs):
    fake_llm.last_prompt = prompt
    return LLMJsonResult(data=OUTPUT, model="fake", input_tokens=100, output_tokens=50)


def calendar_meeting(minutes_ago: int = 60) -> meeting_client.CalendarMeeting:
    end = datetime.now().replace(second=0, microsecond=0) - timedelta(minutes=minutes_ago)
    return meeting_client.CalendarMeeting(
        event_id="evt1",
        title="Weekly Sales Meeting",
        start=end - timedelta(minutes=30),
        end=end,
        meeting_code="abc-mnop-xyz",
        organizer="Omar <omar@t2.sa>",
        attendees=["Omar <omar@t2.sa>", "Sara <sara@t2.sa>"],
    )


# ---- Uploaded transcripts ------------------------------------------------------------


def test_clean_vtt_keeps_speakers_and_drops_repeats() -> None:
    assert meeting_client.clean_uploaded_transcript(VTT) == (
        "Omar: مرحبا جميعاً، نبدأ بعقد ACME\nSara: I will send the price list by Thursday."
    )


def test_plain_text_stays_the_same() -> None:
    assert meeting_client.clean_uploaded_transcript("  Ali: hello\nSara: hi  ") == (
        "Ali: hello\nSara: hi"
    )


# ---- Meet API transcript (fake Google service) ---------------------------------------


class _Req:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


class _Lister:
    def __init__(self, pages, calls=None):
        self.pages = pages  # parent -> result dict
        self.calls = calls if calls is not None else []

    def list(self, **kwargs):
        self.calls.append(kwargs)
        return _Req(self.pages.get(kwargs.get("parent", "root"), {}))


class FakeMeet:
    def __init__(self, transcript_state="FILE_GENERATED"):
        self.record_calls: list[dict] = []
        rec = "conferenceRecords/r1"
        self.records = _Lister(
            {"root": {"conferenceRecords": [{"name": rec, "startTime": "2026-09-28T09:00:00Z"}]}},
            self.record_calls,
        )
        self.transcripts = _Lister(
            {rec: {"transcripts": [{"name": f"{rec}/transcripts/t1", "state": transcript_state}]}}
        )
        self.entries = _Lister(
            {
                f"{rec}/transcripts/t1": {
                    "transcriptEntries": [
                        {
                            "participant": f"{rec}/participants/p1",
                            "text": "نبدأ الاجتماع",
                            "startTime": "2026-09-28T09:01:00Z",
                        },
                        {
                            "participant": f"{rec}/participants/p2",
                            "text": "Price list is ready.",
                            "startTime": "2026-09-28T09:02:00Z",
                        },
                    ]
                }
            }
        )
        self.participants = _Lister(
            {
                rec: {
                    "participants": [
                        {"name": f"{rec}/participants/p1", "signedinUser": {"displayName": "Omar"}},
                        {
                            "name": f"{rec}/participants/p2",
                            "anonymousUser": {"displayName": "Sara"},
                        },
                    ]
                }
            }
        )

    def conferenceRecords(self):  # noqa: N802 (Google's method name)
        outer = self

        class Records:
            def list(self, **kw):
                return outer.records.list(**kw)

            def participants(self):
                return outer.participants

            def transcripts(self):
                class Transcripts:
                    def list(self, **kw):
                        return outer.transcripts.list(**kw)

                    def entries(self):
                        return outer.entries

                return Transcripts()

        return Records()


def test_fetch_transcript_with_speaker_names(db, monkeypatch) -> None:
    fake = FakeMeet()
    monkeypatch.setattr(google_client, "service", lambda db, name, version: fake)

    result = meeting_client.fetch_transcript(db, calendar_meeting())

    assert result.status == "ready"
    assert result.conference_record == "conferenceRecords/r1"
    lines = result.text.splitlines()
    assert lines[0].endswith("Omar: نبدأ الاجتماع")
    assert lines[1].endswith("Sara: Price list is ready.")
    assert 'space.meeting_code = "abc-mnop-xyz"' in fake.record_calls[0]["filter"]


def test_transcript_not_ready_yet(db, monkeypatch) -> None:
    fake = FakeMeet(transcript_state="STARTED")
    monkeypatch.setattr(google_client, "service", lambda db, name, version: fake)
    assert meeting_client.fetch_transcript(db, calendar_meeting()).status == "waiting"


# ---- Refresh -------------------------------------------------------------------------


def test_refresh_saves_meetings_and_transcripts(db, monkeypatch) -> None:
    cal = calendar_meeting()
    monkeypatch.setattr(meeting_client, "list_finished_meetings", lambda db, days: [cal])
    monkeypatch.setattr(
        meeting_client,
        "fetch_transcript",
        lambda db, m: meeting_client.TranscriptResult("ready", "Omar: hi", "conferenceRecords/r1"),
    )

    result = meeting_agent.refresh(db)
    again = meeting_agent.refresh(db)  # second time: no duplicate

    assert (result.found, result.new, result.ready) == (1, 1, 1)
    assert again.new == 0
    meeting = db.query(Meeting).one()
    assert meeting.title == "Weekly Sales Meeting"
    assert meeting.owner == "Omar <omar@t2.sa>"
    assert meeting.transcript_text == "Omar: hi"


def test_missing_transcript_waits_one_day_then_is_none(db, monkeypatch) -> None:
    none = meeting_client.TranscriptResult("none")
    monkeypatch.setattr(meeting_client, "fetch_transcript", lambda db, m: none)

    recent, old = calendar_meeting(minutes_ago=60), calendar_meeting(minutes_ago=60 * 30)
    old.event_id = "evt-old"
    monkeypatch.setattr(meeting_client, "list_finished_meetings", lambda db, days: [recent, old])

    result = meeting_agent.refresh(db)

    assert (result.waiting, result.no_transcript) == (1, 1)


# ---- Summary + tasks -----------------------------------------------------------------


def test_summarize_saves_summary_and_creates_my_tasks(db, monkeypatch) -> None:
    monkeypatch.setattr(meeting_agent, "ask_json", fake_llm)
    meeting = meeting_agent.add_uploaded(db, "Sales sync", datetime(2026, 9, 28, 9, 0), VTT)

    summary = meeting_agent.summarize(db, meeting, "en")

    assert summary.decisions == ["Launch moved to 15 October"]
    assert "العقد" in summary.keywords
    assert "Write the summary in English." in fake_llm.last_prompt
    titles = sorted(t.title for t in db.query(Task).all())
    # Sara's item is "mine" -> task. Omar's item is not. Blockers are not tasks.
    assert titles == ["Send the price list to ACME"]

    meeting_agent.summarize(db, meeting)  # summarize again: no duplicate tasks
    assert db.query(Task).count() == 1


# ---- API -----------------------------------------------------------------------------


def test_upload_summarize_and_detail(client, monkeypatch) -> None:
    monkeypatch.setattr(meeting_agent, "ask_json", fake_llm)

    r = client.post("/api/meetings/upload", json={"title": "Sales sync", "text": VTT})
    assert r.status_code == 200
    meeting_id = r.json()["id"]
    assert r.json()["transcript_status"] == "ready"

    r = client.post(f"/api/meetings/{meeting_id}/summarize", json={"output_language": "same"})
    body = r.json()
    assert r.status_code == 200
    assert body["summary"]["overview"].startswith("The team discussed")
    assert body["summary"]["action_items"][0]["owner"] == "Sara"
    assert [log["action"] for log in body["logs"]] == [
        "tasks_created",
        "summarized",
        "transcript_uploaded",
    ]
    assert len(body["tasks"]) == 1

    # Past summaries, searchable by an Arabic keyword.
    found = client.get("/api/meetings", params={"summarized": True, "q": "العقد"}).json()
    assert [m["id"] for m in found] == [meeting_id]
    assert client.get("/api/meetings", params={"q": "nothing-like-this"}).json() == []


def test_summarize_without_transcript_gives_clear_error(client, db) -> None:
    meeting = Meeting(
        platform="meet",
        provider_meeting_id="x",
        title="No transcript",
        date=datetime(2026, 9, 28, 9, 0),
        attendees=[],
        transcript_status="none",
    )
    db.add(meeting)
    db.commit()
    r = client.post(f"/api/meetings/{meeting.id}/summarize", json={})
    assert r.status_code == 400
    assert "no transcript" in r.json()["detail"]


def test_refresh_without_google_gives_clear_message(client) -> None:
    r = client.post("/api/meetings/refresh")
    assert r.status_code == 409
    assert "Connect Google" in r.json()["detail"]
