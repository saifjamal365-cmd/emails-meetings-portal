"""Email agent tests: rules, LLM decision (faked), Gmail sync (faked) and the email API."""

import base64
from datetime import datetime

import pytest

from app.agents import email_agent
from app.agents.email_agent import EmailDecision, rule_check
from app.models import Email, Task
from app.services import mail_client
from app.services.llm_client import LLMError, LLMJsonResult


def make_email(db, n: int, sender: str, subject: str = "Hello", labels=None) -> Email:
    email = Email(
        provider_id=f"gmail-{n}",
        thread_id=f"thread-{n}",
        message_id_header=f"<msg-{n}@mail>",
        sender=sender,
        sender_name="Someone",
        sender_domain=sender.split("@")[1],
        subject=subject,
        body="Please send the price list by Thursday.",
        received_at=datetime(2026, 9, 28, 9, n),
        labels=labels or ["INBOX", "UNREAD"],
    )
    db.add(email)
    db.commit()
    return email


def fake_llm(priority="High", deadline="2026-10-01"):
    def _ask_json(prompt, schema, **kwargs):
        decision = EmailDecision(
            priority=priority,
            category="Client",
            reason="Client asks for a price list.",
            language="en",
            needs_reply=True,
            deadline=deadline,
            draft_reply="Dear client, thank you for your email ...",
        )
        return LLMJsonResult(data=decision, model="fake", input_tokens=10, output_tokens=10)

    return _ask_json


# ---- Rules -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sender", "labels", "expected"),
    [
        ("news@facebookmail.com", [], "Low"),  # low domain
        ("a@mail.facebook.com", [], "Low"),  # sub-domain of a low domain
        ("no-reply@shop.com", [], "Low"),  # no-reply sender
        ("sales@shop.com", ["CATEGORY_PROMOTIONS"], "Low"),  # Gmail Promotions tab
        ("ceo@acme.com", [], "High"),  # high domain
        ("someone@unknown.com", [], None),  # rules cannot decide -> LLM
    ],
)
def test_rule_check(sender, labels, expected) -> None:
    email = Email(sender=sender, sender_domain=sender.split("@")[1], labels=labels)
    assert rule_check(email, ["acme.com"], ["facebook.com", "facebookmail.com"]) == expected


# ---- Agent -------------------------------------------------------------------


def test_llm_decides_and_writes_draft(db, monkeypatch) -> None:
    monkeypatch.setattr(email_agent, "ask_json", fake_llm())
    email = make_email(db, 1, "buyer@client.com")

    result = email_agent.analyze_pending(db)

    assert (result.analyzed, result.high, result.low) == (1, 1, 0)
    db.refresh(email)
    assert email.analysis.priority == "High"
    assert email.analysis.reply_status == "Draft ready"
    assert email.analysis.deadline.isoformat() == "2026-10-01"
    assert email.analysis.draft_reply.startswith("Dear client")


def test_low_rule_does_not_call_llm(db, monkeypatch) -> None:
    def must_not_call(*args, **kwargs):
        raise AssertionError("LLM should not be called for a Low rule")

    monkeypatch.setattr(email_agent, "ask_json", must_not_call)
    email = make_email(db, 2, "notification@facebookmail.com")

    email_agent.analyze_pending(db)

    db.refresh(email)
    assert email.analysis.priority == "Low"
    assert email.analysis.category == "Social"
    assert email.analysis.decided_by == "rule"


def test_llm_error_stops_and_is_reported(db, monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise LLMError("GEMINI_API_KEY is not set. Add it to backend/.env.")

    monkeypatch.setattr(email_agent, "ask_json", fail)
    make_email(db, 3, "a@client.com")
    make_email(db, 4, "b@client.com")

    result = email_agent.analyze_pending(db)

    assert result.analyzed == 0
    assert result.errors == ["GEMINI_API_KEY is not set. Add it to backend/.env."]


def test_sync_saves_new_emails_and_marks_read_ones(db, monkeypatch) -> None:
    monkeypatch.setattr(email_agent, "ask_json", fake_llm())
    old = make_email(db, 5, "old@client.com")  # unread in our DB, but read in Gmail now
    fetched = [
        mail_client.FetchedEmail(
            provider_id="gmail-new",
            thread_id="t",
            message_id_header="<new@mail>",
            sender="new@client.com",
            sender_name="New",
            subject="Order",
            body="Hi",
            received_at=datetime(2026, 9, 28, 10, 0),
        )
    ]
    monkeypatch.setattr(mail_client, "fetch_unread", lambda db, max_results: fetched)

    result = email_agent.sync(db)

    assert (result.fetched, result.new, result.analyzed) == (1, 1, 1)
    db.refresh(old)
    assert old.is_read is True


# ---- Gmail message parsing ---------------------------------------------------


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def test_parse_gmail_message_html_and_arabic() -> None:
    message = {
        "id": "m1",
        "threadId": "t1",
        "labelIds": ["INBOX", "UNREAD"],
        "payload": {
            "headers": [
                {"name": "From", "value": "Ahmad Ali <Ahmad@Client.com>"},
                {"name": "Subject", "value": "عرض سعر"},
                {"name": "Date", "value": "Mon, 28 Sep 2026 09:30:00 +0300"},
                {"name": "Message-ID", "value": "<abc@mail>"},
            ],
            "mimeType": "multipart/alternative",
            "parts": [
                {"mimeType": "text/html", "body": {"data": _b64("<p>مرحبا،<br>نريد عرض سعر</p>")}}
            ],
        },
    }
    email = mail_client._parse(message)
    assert email.sender == "ahmad@client.com"
    assert email.sender_name == "Ahmad Ali"
    assert email.sender_domain == "client.com"
    assert email.subject == "عرض سعر"
    assert "نريد عرض سعر" in email.body
    assert email.message_id_header == "<abc@mail>"


# ---- Email API ---------------------------------------------------------------


def test_high_and_low_pages(client, db, monkeypatch) -> None:
    monkeypatch.setattr(email_agent, "ask_json", fake_llm())
    make_email(db, 6, "buyer@client.com")
    make_email(db, 7, "news@facebookmail.com")
    email_agent.analyze_pending(db)

    high = client.get("/api/emails", params={"view": "high"}).json()
    low = client.get("/api/emails", params={"view": "low"}).json()
    counts = client.get("/api/emails/counts").json()

    assert [e["sender"] for e in high] == ["buyer@client.com"]
    assert [e["sender"] for e in low] == ["news@facebookmail.com"]
    assert counts["high"] == 1 and counts["low"] == 1 and counts["unread"] == 2


def test_edit_move_skip_and_task(client, db, monkeypatch) -> None:
    monkeypatch.setattr(email_agent, "ask_json", fake_llm())
    email = make_email(db, 8, "buyer@client.com", subject="Price list")
    email_agent.analyze_pending(db)

    r = client.put(f"/api/emails/{email.id}/draft", json={"draft_reply": "My edited reply"})
    assert r.json()["reply_status"] == "Edited"
    assert r.json()["draft_reply"] == "My edited reply"

    r = client.post(f"/api/emails/{email.id}/priority", json={"priority": "Low"})
    assert r.json()["priority"] == "Low"

    r = client.post(f"/api/emails/{email.id}/task")
    task = db.get(Task, r.json()["task_id"])
    assert task.title == "Reply to: Price list"
    assert task.source_type == "email"

    client.post(f"/api/emails/{email.id}/skip")
    assert client.get("/api/emails", params={"view": "low"}).json() == []


def test_send_reply(client, db, monkeypatch) -> None:
    monkeypatch.setattr(email_agent, "ask_json", fake_llm())
    sent = {}
    monkeypatch.setattr(mail_client, "send_reply", lambda db, email, text: sent.update(text=text))
    email = make_email(db, 9, "buyer@client.com")
    email_agent.analyze_pending(db)

    r = client.post(f"/api/emails/{email.id}/send", json={"reply": "Thanks, here it is."})

    assert r.status_code == 200
    assert r.json()["reply_status"] == "Sent"
    assert sent["text"] == "Thanks, here it is."
    assert client.get("/api/emails/counts").json()["sent_today"] == 1


def test_sync_without_gmail_gives_clear_message(client) -> None:
    r = client.post("/api/emails/sync")
    assert r.status_code == 409
    assert "Connect Google" in r.json()["detail"]


def test_settings_are_cleaned(client) -> None:
    r = client.put(
        "/api/settings",
        json={"high_domains": [" @ACME.com ", "acme.com", ""], "low_domains": ["meta.com"]},
    )
    assert r.json() == {
        "high_domains": ["acme.com"],
        "low_domains": ["meta.com"],
        "auto_summarize": False,
        "auto_record": False,
        "meeting_words": [],
        "remember_voices": False,  # voice prints are biometric data: off until turned on
    }


def test_refresh_runs_in_the_background_with_progress(client, db, monkeypatch) -> None:
    import time

    from app.services import google_client

    monkeypatch.setattr(google_client, "account", lambda db: ("me@gmail.com", "Me"))
    monkeypatch.setattr(email_agent, "ask_json", fake_llm())
    fetched = [
        mail_client.FetchedEmail(
            provider_id=f"bg{i}",
            thread_id="t",
            message_id_header="",
            sender=f"c{i}@client.com",
            sender_name="Client",
            subject="Order",
            body="Hi",
            received_at=datetime(2026, 9, 28, 9, i),
        )
        for i in range(3)
    ]
    monkeypatch.setattr(mail_client, "fetch_unread", lambda db, max_results: fetched)

    r = client.post("/api/emails/sync")
    assert r.status_code == 200 and r.json()["running"] is True  # returns at once

    for _ in range(100):  # wait for the background thread
        status = client.get("/api/emails/sync-status").json()
        if not status["running"]:
            break
        time.sleep(0.05)

    assert status["stage"] == "done" and status["error"] == ""
    assert (status["new"], status["to_analyze"], status["analyzed"]) == (3, 3, 3)
    assert len(client.get("/api/emails", params={"view": "high"}).json()) == 3
