"""Meeting-Email link tests: matching (Arabic + English), score, LLM check, both directions."""

from datetime import datetime, timedelta

import pytest

from app.agents import email_agent, linker, meeting_agent
from app.agents.email_agent import EmailDecision
from app.agents.linker import LinkCheck, normalize
from app.models import Email, EmailAnalysis, Meeting, MeetingSummary
from app.services.llm_client import LLMJsonResult

NOW = datetime.now().replace(second=0, microsecond=0)


def make_meeting(db, days_ago: float = 1, keywords=None) -> Meeting:
    meeting = Meeting(
        platform="meet",
        provider_meeting_id=f"m-{days_ago}-{len(keywords or [])}",
        title="Weekly Sales Meeting",
        date=NOW - timedelta(days=days_ago),
        owner="Omar <omar@t2.sa>",
        attendees=["Omar <omar@t2.sa>", "Sara <sara@acme.com>"],
        transcript_status="ready",
        transcript_text="...",
    )
    meeting.summary = MeetingSummary(
        overview="ACME contract and Project Falcon.",
        decisions=["Launch moves to 15 October"],
        keywords=keywords or ["ACME", "Project Falcon", "العقد", "contract", "meeting"],
    )
    db.add(meeting)
    db.commit()
    return meeting


def make_email(db, n: int, subject: str, body: str, sender="buyer@client.com") -> Email:
    email = Email(
        provider_id=f"e-{n}",
        sender=sender,
        sender_domain=sender.split("@")[1],
        subject=subject,
        body=body,
        received_at=NOW - timedelta(hours=1),
    )
    db.add(email)
    db.commit()
    return email


def fake_email_llm(priority="Low"):
    def _ask_json(prompt, schema, **kwargs):
        _ask_json.prompts.append(prompt)
        decision = EmailDecision(
            priority=priority,
            category="Other",
            reason="Looks like general information.",
            language="en",
            needs_reply=False,
            deadline="",
            draft_reply="",
        )
        return LLMJsonResult(data=decision, model="fake", input_tokens=1, output_tokens=1)

    _ask_json.prompts = []
    return _ask_json


def fake_link_check(related: bool):
    def _ask_json(prompt, schema, **kwargs):
        assert schema is LinkCheck
        _ask_json.calls += 1
        return LLMJsonResult(
            data=LinkCheck(related=related, reason="test"),
            model="f",
            input_tokens=1,
            output_tokens=1,
        )

    _ask_json.calls = 0
    return _ask_json


# ---- Matching ------------------------------------------------------------------------


def test_normalize_arabic_forms() -> None:
    assert normalize("إتفاقيّة الشركة") == normalize("اتفاقية الشركه")


@pytest.mark.parametrize(
    ("text", "keyword", "expected"),
    [
        ("Update on the acme order", "ACME", True),
        ("The acmeist club", "ACME", False),  # whole words only for Latin text
        ("نرسل لكم مسودة العقد اليوم", "العقد", True),
        ("بخصوص عقد التوريد", "العقد", True),  # "ال" removed from the keyword
        ("وبالعقد الجديد", "العقد", True),  # Arabic prefixes
    ],
)
def test_keyword_matching(db, text, keyword, expected) -> None:
    meeting = make_meeting(db, keywords=[keyword])
    email = make_email(db, 1, "Hello", text)
    assert (linker.score(email, meeting, set()).score > 0) is expected


def test_score_counts_keywords_subject_and_attendee(db) -> None:
    meeting = make_meeting(db)
    email = make_email(
        db, 2, "ACME contract", "About Project Falcon and the meeting.", sender="sara@acme.com"
    )
    stop = {linker._keyword_form(w) for w in linker.BASE_STOP_WORDS}
    c = linker.score(email, meeting, stop)
    # 3 keywords (ACME, Project Falcon, contract; "meeting" is a stop word) + subject + attendee
    assert sorted(c.matched) == ["ACME", "Project Falcon", "contract"]
    assert c.score == 3 + 2 + 2


# ---- Email -> meeting (when a new email is analyzed) ---------------------------------


def test_new_email_with_meeting_keywords_becomes_high(db, monkeypatch) -> None:
    make_meeting(db)
    llm = fake_email_llm(priority="Low")
    monkeypatch.setattr(email_agent, "ask_json", llm)
    email = make_email(db, 3, "Re: ACME contract", "Here is the new contract for Project Falcon.")

    email_agent.analyze_pending(db)

    db.refresh(email)
    assert email.analysis.priority == "High"
    assert email.analysis.decided_by == "meeting"
    assert email.analysis.reason.startswith("Connected to the meeting Weekly Sales Meeting")
    assert "Launch moves to 15 October" in llm.prompts[0]  # meeting notes help the reply
    link = linker.active_links(email)[0]
    assert link.previous_priority == "Low"


def test_old_meetings_are_not_used(db, monkeypatch) -> None:
    make_meeting(db, days_ago=10)
    monkeypatch.setattr(email_agent, "ask_json", fake_email_llm(priority="Low"))
    email = make_email(db, 4, "ACME contract", "Project Falcon")

    email_agent.analyze_pending(db)

    db.refresh(email)
    assert email.analysis.priority == "Low"
    assert email.meeting_links == []


@pytest.mark.parametrize("related", [True, False])
def test_unclear_match_asks_the_llm(db, monkeypatch, related) -> None:
    meeting = make_meeting(db)
    check = fake_link_check(related)
    monkeypatch.setattr(linker, "ask_json", check)
    email = make_email(db, 5, "Hello", "Did you hear about ACME?")  # 1 keyword, body only

    links = linker.find_links(db, email)

    assert check.calls == 1
    assert [c.meeting.id for c in links] == ([meeting.id] if related else [])


def test_one_common_word_in_the_subject_is_not_enough(db, monkeypatch) -> None:
    make_meeting(db)
    check = fake_link_check(False)
    monkeypatch.setattr(linker, "ask_json", check)
    email = make_email(db, 11, "Contract renewal", "Please confirm the renewal.")  # score 1 + 2

    assert linker.find_links(db, email) == []
    assert check.calls == 1  # asked the LLM instead of linking at once


def test_social_rule_emails_are_never_linked(db, monkeypatch) -> None:
    make_meeting(db)
    monkeypatch.setattr(email_agent, "ask_json", fake_email_llm())
    email = make_email(db, 6, "ACME contract", "Project Falcon", sender="x@facebookmail.com")

    email_agent.analyze_pending(db)

    db.refresh(email)
    assert email.analysis.priority == "Low"
    assert email.meeting_links == []


# ---- Meeting -> email (after a new summary) ------------------------------------------


def test_new_summary_rechecks_unread_emails(db, monkeypatch) -> None:
    email = make_email(db, 7, "ACME contract draft", "Project Falcon contract attached.")
    db.add(EmailAnalysis(email_id=email.id, priority="Low", category="Other", decided_by="llm"))
    user_choice = make_email(db, 8, "ACME contract", "Project Falcon", sender="a@client.com")
    db.add(
        EmailAnalysis(email_id=user_choice.id, priority="Low", category="Other", decided_by="user")
    )
    db.commit()

    meeting = meeting_agent.add_uploaded(db, "Sales sync", NOW - timedelta(hours=2), "Omar: hi")
    output = meeting_agent.MeetingOutput(
        overview="ACME contract.",
        detected_language="en",
        action_items=[],
        decisions=[],
        risks=[],
        blockers=[],
        keywords=["ACME", "Project Falcon", "contract"],
    )
    monkeypatch.setattr(
        meeting_agent,
        "ask_json",
        lambda *a, **k: LLMJsonResult(data=output, model="f", input_tokens=1, output_tokens=1),
    )

    meeting_agent.summarize(db, meeting)

    db.refresh(email)
    db.refresh(user_choice)
    assert email.analysis.priority == "High"
    assert user_choice.analysis.priority == "Low"  # the user's choice wins...
    assert len(linker.active_links(user_choice)) == 1  # ...but the label is still shown


# ---- API: label and "wrong link" -------------------------------------------------------


def test_label_and_remove_wrong_link(client, db, monkeypatch) -> None:
    make_meeting(db)
    monkeypatch.setattr(email_agent, "ask_json", fake_email_llm(priority="Low"))
    email = make_email(db, 9, "ACME contract", "Project Falcon")
    email_agent.analyze_pending(db)

    high = client.get("/api/emails", params={"view": "high"}).json()
    assert high[0]["meeting_label"].startswith("Weekly Sales Meeting (")

    detail = client.get(f"/api/emails/{email.id}").json()
    link_id = detail["meeting_links"][0]["id"]
    r = client.delete(f"/api/emails/{email.id}/links/{link_id}")

    assert r.json()["priority"] == "Low"  # back to what the agent decided
    assert r.json()["meeting_label"] is None

    # A removed link does not come back on the next check.
    db.expire_all()
    assert linker.find_links(db, db.get(Email, email.id)) == []


def test_meeting_page_lists_linked_emails(client, db, monkeypatch) -> None:
    meeting = make_meeting(db)
    monkeypatch.setattr(email_agent, "ask_json", fake_email_llm(priority="Low"))
    make_email(db, 10, "ACME contract", "Project Falcon")
    email_agent.analyze_pending(db)

    linked = client.get(f"/api/meetings/{meeting.id}").json()["linked_emails"]
    assert [e["subject"] for e in linked] == ["ACME contract"]
    assert linked[0]["priority"] == "High"
