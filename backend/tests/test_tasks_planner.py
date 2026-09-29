"""Daily Tasks and Daily Planner tests (fake LLM, no API key needed)."""

from datetime import date, datetime, timedelta

from app.agents import email_agent, planner
from app.agents.email_agent import EmailDecision
from app.models import DailyReport, Email, EmailAnalysis, Task
from app.services.llm_client import LLMError, LLMJsonResult, LLMResult

TODAY = date.today()


def add_task(db, title, due=None, priority="Medium", status="To do", **kw) -> Task:
    task = Task(title=title, due_date=due, priority=priority, status=status, **kw)
    db.add(task)
    db.commit()
    return task


# ---- Task board API ------------------------------------------------------------------


def test_create_edit_move_and_delete(client) -> None:
    r = client.post("/api/tasks", json={"title": "Prepare slides", "priority": "High"})
    task = r.json()
    assert task["status"] == "To do" and task["source_type"] == "manual"

    r = client.put(
        f"/api/tasks/{task['id']}", json={"notes": "10 slides", "due_date": "2030-01-05"}
    )
    assert r.json()["notes"] == "10 slides"
    assert r.json()["title"] == "Prepare slides"  # fields not sent stay the same

    r = client.put(f"/api/tasks/{task['id']}", json={"status": "Done"})
    assert r.json()["completed_at"] is not None
    r = client.put(f"/api/tasks/{task['id']}", json={"status": "In progress"})
    assert r.json()["completed_at"] is None

    assert client.delete(f"/api/tasks/{task['id']}").status_code == 200
    assert client.get("/api/tasks").json() == []


def test_empty_title_is_refused(client) -> None:
    assert client.post("/api/tasks", json={"title": ""}).status_code == 422


def test_list_order_and_counts(client, db) -> None:
    add_task(db, "No date")
    add_task(db, "Late one", due=TODAY - timedelta(days=2))
    add_task(db, "Today, low", due=TODAY, priority="Low")
    add_task(db, "Today, high", due=TODAY, priority="High")
    add_task(db, "Done yesterday", status="Done", completed_at=datetime.now() - timedelta(days=1))

    titles = [t["title"] for t in client.get("/api/tasks").json()]
    assert titles == ["Late one", "Today, high", "Today, low", "No date"]  # old Done is hidden
    assert len(client.get("/api/tasks", params={"all_done": True}).json()) == 5

    counts = client.get("/api/tasks/counts").json()
    assert counts == {"open": 4, "due_today": 2, "late": 1, "done_today": 0}


# ---- Tasks from the agents -----------------------------------------------------------


def test_high_email_with_deadline_becomes_a_task(db, monkeypatch) -> None:
    decision = EmailDecision(
        priority="High",
        category="Client",
        reason="Client needs a quote by Thursday.",
        language="en",
        needs_reply=True,
        deadline=(TODAY + timedelta(days=2)).isoformat(),
        draft_reply="Dear client ...",
    )
    monkeypatch.setattr(
        email_agent,
        "ask_json",
        lambda *a, **k: LLMJsonResult(data=decision, model="f", input_tokens=1, output_tokens=1),
    )
    db.add(
        Email(
            provider_id="e1",
            sender="buyer@client.com",
            sender_domain="client.com",
            subject="Quote please",
            body="Please send a quote by Thursday.",
            received_at=datetime.now(),
        )
    )
    db.commit()

    email_agent.analyze_pending(db)

    task = db.query(Task).one()
    assert task.title == "Reply to: Quote please"
    assert task.source_type == "email"
    assert task.due_date == TODAY + timedelta(days=2)


def test_add_to_tasks_twice_makes_one_task(client, db) -> None:
    email = Email(
        provider_id="e2",
        sender="a@b.com",
        sender_domain="b.com",
        subject="Hi",
        body="",
        received_at=datetime.now(),
    )
    db.add(email)
    db.commit()
    first = client.post(f"/api/emails/{email.id}/task").json()
    second = client.post(f"/api/emails/{email.id}/task").json()
    assert first["created"] is True and second["created"] is False
    assert first["task_id"] == second["task_id"]


# ---- Daily planner -------------------------------------------------------------------


def _waiting_high_email(db) -> None:
    email = Email(
        provider_id="e3",
        sender="sara@acme.com",
        sender_name="Sara Khan",
        sender_domain="acme.com",
        subject="Contract renewal",
        body="",
        received_at=datetime.now(),
    )
    db.add(email)
    db.flush()
    db.add(
        EmailAnalysis(
            email_id=email.id,
            priority="High",
            category="Partner",
            reason="Partner needs a decision.",
            reply_status="Draft ready",
            deadline=TODAY + timedelta(days=1),
        )
    )
    db.commit()


def test_morning_facts_put_urgent_things_first(db) -> None:
    add_task(db, "Send price list", due=TODAY - timedelta(days=1), priority="High")
    add_task(db, "Call supplier", due=TODAY)
    add_task(db, "Read report")
    _waiting_high_email(db)

    facts = planner.collect_facts(db, "morning", TODAY)

    assert facts.index("## Late tasks") < facts.index("## Tasks due today")
    assert "Send price list | priority High | LATE by 1 day(s)" in facts
    assert "Sara Khan: Contract renewal" in facts
    assert "## Other open tasks\n- Read report" in facts


def test_evening_facts_count_done_and_sent(db) -> None:
    add_task(db, "Finished thing", status="Done", completed_at=datetime.now())
    add_task(db, "Still open")
    facts = planner.collect_facts(db, "evening", TODAY)
    assert "## Tasks done today\n- Finished thing" in facts
    assert "Still open" in facts


def test_generate_with_llm_and_edit(client, db, monkeypatch) -> None:
    add_task(db, "Send price list", due=TODAY)
    sent = {}

    def fake_ask(prompt, **kwargs):
        sent["prompt"] = prompt
        return LLMResult(
            text="## Top priorities\n1. Send price list", model="f", input_tokens=1, output_tokens=1
        )

    monkeypatch.setattr(planner, "ask", fake_ask)

    r = client.post("/api/reports/morning/generate").json()

    assert r["warning"] is None
    assert r["report"]["made_by"] == "llm"
    assert "Send price list" in sent["prompt"] and "START-OF-DAY" in sent["prompt"]

    edited = client.put(f"/api/reports/{r['report']['id']}", json={"content": "My own plan"})
    assert edited.json()["edited_by_user"] is True
    day = client.get("/api/reports").json()
    assert day["morning"]["content"] == "My own plan" and day["evening"] is None
    assert client.get("/api/reports/days").json() == [TODAY.isoformat()]


def test_without_llm_a_basic_plan_is_saved(client, db, monkeypatch) -> None:
    add_task(db, "Send price list", due=TODAY)

    def no_llm(*args, **kwargs):
        raise LLMError("GEMINI_API_KEY is not set. Add it to backend/.env.")

    monkeypatch.setattr(planner, "ask", no_llm)

    r = client.post("/api/reports/evening/generate").json()

    assert r["report"]["made_by"] == "basic"
    assert "Send price list" in r["report"]["content"]
    assert "GEMINI_API_KEY" in r["warning"]


def test_scheduled_job_never_replaces_an_existing_report(db, monkeypatch) -> None:
    db.add(DailyReport(date=TODAY, type="morning", content="Mine", edited_by_user=True))
    db.commit()
    monkeypatch.setattr(planner, "ask", lambda *a, **k: 1 / 0)  # must not be called

    assert planner.scheduled(db, "morning") is None
    assert db.query(DailyReport).one().content == "Mine"
