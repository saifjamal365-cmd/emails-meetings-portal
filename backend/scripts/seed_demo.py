"""Add sample emails and meetings (Arabic + English) to try the pages without Google.

Run from the backend folder:
    .venv\\Scripts\\python -m scripts.seed_demo           # real agent (needs API key)
    .venv\\Scripts\\python -m scripts.seed_demo --no-llm  # fake results, no key needed

Demo emails and meetings have ids starting with "demo-". Sending a reply to a demo email
fails, because it is not in Gmail. Remove them with:  python -m scripts.seed_demo --clear
"""

import sys
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select

from app.agents import email_agent, meeting_agent
from app.db import SessionLocal, init_db
from app.models import Email, EmailAnalysis, EmailMeetingLink, Meeting, MeetingSummary, Task
from app.services.llm_client import LLMJsonResult

now = datetime.now().replace(second=0, microsecond=0)

DEMO = [
    # (sender, name, subject, body, minutes ago, gmail labels)
    (
        "updates@fastship.com",
        "FastShip Logistics",
        "Project Falcon - delivery update",
        "Hello,\nThe supplier for Project Falcon confirmed the new delivery week. The updated "
        "contract terms are attached.\nFastShip",
        10,
        ["INBOX", "UNREAD"],
    ),
    (
        "ahmad@alnoor-trading.sa",
        "Ahmad Al-Otaibi",
        "طلب عرض سعر - 200 وحدة",
        "السلام عليكم،\nنرغب في الحصول على عرض سعر لـ 200 وحدة من منتجكم الجديد، "
        "مع مدة التوريد. نحتاج الرد قبل يوم الخميس.\nشكراً لكم",
        20,
        ["INBOX", "UNREAD"],
    ),
    (
        "sara@acme-logistics.com",
        "Sara Khan",
        "Contract renewal - please confirm by Oct 2",
        "Hi,\nOur shipping contract ends this month. Can you confirm the renewal and the new "
        "volume by October 2? I attached the draft terms last week.\nBest,\nSara",
        45,
        ["INBOX", "UNREAD"],
    ),
    (
        "support@cloudhost.io",
        "CloudHost Billing",
        "Invoice #4471 is overdue",
        "Your invoice #4471 (USD 320) was due on Sep 25. Please pay it to avoid service "
        "interruption.",
        90,
        ["INBOX", "UNREAD"],
    ),
    (
        "notification@facebookmail.com",
        "Facebook",
        "You have 3 new notifications",
        "See what your friends shared today.",
        30,
        ["INBOX", "UNREAD", "CATEGORY_SOCIAL"],
    ),
    (
        "messages-noreply@linkedin.com",
        "LinkedIn",
        "5 people viewed your profile",
        "See who viewed your profile this week.",
        120,
        ["INBOX", "UNREAD", "CATEGORY_SOCIAL"],
    ),
    (
        "news@techweekly.com",
        "Tech Weekly",
        "This week in AI: 10 stories",
        "Top stories this week ...",
        200,
        ["INBOX", "UNREAD", "CATEGORY_PROMOTIONS"],
    ),
]

FAKE = {  # used with --no-llm
    # The "LLM" thinks this is Low. The demo meeting's keywords make it High (Phase 4).
    "fastship.com": (
        "Low",
        "Other",
        "Looks like a routine delivery notice.",
        "en",
        "",
    ),
    "alnoor-trading.sa": (
        "High",
        "Client",
        "A client asks for a price quote with a deadline.",
        "ar",
        "وعليكم السلام،\nشكراً لتواصلكم. سنرسل لكم عرض السعر لـ 200 وحدة مع مدة التوريد "
        "قبل يوم الخميس [التاريخ].\nمع التحية",
    ),
    "acme-logistics.com": (
        "High",
        "Partner",
        "A partner needs a contract decision by Oct 2.",
        "en",
        "Hi Sara,\nThank you for the reminder. We will review the draft terms and confirm "
        "the renewal and the new volume [volume] by October 2.\nBest regards",
    ),
    "cloudhost.io": (
        "High",
        "Product",
        "An overdue invoice needs a payment.",
        "en",
        "Hello,\nThank you for the notice. We will pay invoice #4471 by [date].\nRegards",
    ),
}


TRANSCRIPT = """[10:00] Omar: السلام عليكم، نبدأ اجتماع المبيعات الأسبوعي. أول موضوع عقد شركة النور.
[10:01] Sara: The Al-Noor contract is ready, but we are still waiting for legal approval.
[10:02] Omar: طيب، سارة ترسل قائمة الأسعار لشركة النور قبل يوم الخميس.
[10:03] Sara: OK, I will send the price list to Al-Noor by Thursday.
[10:04] Ali: About Project Falcon, the supplier said they may be two weeks late.
[10:05] Omar: إذا تأخر المورد نؤجل الإطلاق إلى 15 أكتوبر. متفقين؟
[10:05] Sara: Agreed, launch moves to October 15.
[10:06] Ali: I will book a call with the supplier tomorrow.
"""

DEMO_MEETINGS = [
    # (title, hours ago, transcript status, transcript)
    ("Weekly Sales Meeting - اجتماع المبيعات", 3, "ready", TRANSCRIPT),
    ("Project Falcon kick-off", 26, "ready", TRANSCRIPT),
    ("Marketing sync", 1, "waiting", None),
]

FAKE_SUMMARY = meeting_agent.MeetingOutput(
    overview="The team reviewed the Al-Noor contract, which waits for legal approval, and the "
    "Project Falcon supplier delay. The launch moves to 15 October if the supplier is late.",
    detected_language="mixed",
    action_items=[
        meeting_agent.ActionItem(
            task="Send the price list to Al-Noor", owner="Sara", owner_is_me=True, due=""
        ),
        meeting_agent.ActionItem(
            task="Book a call with the supplier", owner="Ali", owner_is_me=False, due=""
        ),
    ],
    decisions=["Launch moves to 15 October if the supplier is late"],
    risks=["The Project Falcon supplier may be two weeks late"],
    blockers=["Al-Noor contract is waiting for legal approval"],
    keywords=["Al-Noor", "شركة النور", "Project Falcon", "price list", "قائمة الأسعار", "contract"],
)


DEMO_NOTE = "(demo)"


def add_tasks(db) -> None:
    today = date.today()
    db.add_all(
        [
            Task(title="Prepare the Q4 sales report", due_date=today - timedelta(days=1),
                 priority="High", notes=DEMO_NOTE),
            Task(title="Call the Project Falcon supplier", due_date=today, notes=DEMO_NOTE),
            Task(title="Update the product catalogue", priority="Low", notes=DEMO_NOTE),
        ]
    )  # fmt: skip
    db.commit()


def clear(db) -> None:
    ids = db.scalars(select(Email.id).where(Email.provider_id.like("demo-%"))).all()
    db.execute(delete(EmailAnalysis).where(EmailAnalysis.email_id.in_(ids)))
    db.execute(delete(Email).where(Email.id.in_(ids)))
    meeting_ids = db.scalars(
        select(Meeting.id).where(Meeting.provider_meeting_id.like("demo-%"))
    ).all()
    db.execute(
        delete(EmailMeetingLink).where(
            EmailMeetingLink.email_id.in_(ids) | EmailMeetingLink.meeting_id.in_(meeting_ids)
        )
    )
    db.execute(delete(Task).where(Task.source_type == "meeting", Task.source_id.in_(meeting_ids)))
    db.execute(delete(Task).where(Task.notes == DEMO_NOTE))
    db.execute(delete(Task).where(Task.source_type == "email", Task.source_id.in_(ids)))
    db.execute(delete(MeetingSummary).where(MeetingSummary.meeting_id.in_(meeting_ids)))
    db.execute(delete(Meeting).where(Meeting.id.in_(meeting_ids)))
    db.commit()
    print(f"Removed {len(ids)} demo emails and {len(meeting_ids)} demo meetings.")


def add_meetings(db, fake: bool) -> None:
    for i, (title, hours, status, transcript) in enumerate(DEMO_MEETINGS):
        start = now - timedelta(hours=hours)
        db.add(
            Meeting(
                platform="meet",
                provider_meeting_id=f"demo-meeting-{i}",
                title=title,
                date=start,
                end_time=start + timedelta(minutes=30),
                owner="Omar <omar@example.com>",
                attendees=["Omar <omar@example.com>", "Sara <sara@example.com>", "Ali"],
                transcript_status=status,
                transcript_text=transcript,
            )
        )
    db.commit()
    first = db.scalar(select(Meeting).where(Meeting.provider_meeting_id == "demo-meeting-0"))
    if fake:
        # Summarize the first meeting with a ready-made answer (no API key needed).
        meeting_agent.ask_json = lambda *a, **k: LLMJsonResult(
            data=FAKE_SUMMARY, model="demo (no LLM)", input_tokens=0, output_tokens=0
        )
    try:
        meeting_agent.summarize(db, first)
        print("Summarized the first demo meeting.")
    except Exception as e:
        print("Could not summarize the demo meeting:", e)


def main() -> None:
    init_db()
    with SessionLocal() as db:
        clear(db)
        if "--clear" in sys.argv:
            return
        for i, (sender, name, subject, body, ago, labels) in enumerate(DEMO):
            db.add(
                Email(
                    provider_id=f"demo-{i}",
                    thread_id=f"demo-thread-{i}",
                    sender=sender,
                    sender_name=name,
                    sender_domain=sender.split("@")[1],
                    subject=subject,
                    body=body,
                    received_at=now - timedelta(minutes=ago),
                    labels=labels,
                )
            )
        db.commit()

        if "--no-llm" in sys.argv:
            for email in db.scalars(select(Email).where(Email.provider_id.like("demo-%"))):
                fake = FAKE.get(email.sender_domain)
                if fake:
                    priority, category, reason, lang, draft = fake
                    email.language = lang
                    db.add(
                        EmailAnalysis(
                            email_id=email.id,
                            priority=priority,
                            category=category,
                            reason=reason,
                            draft_reply=draft,
                            reply_status="Draft ready" if draft else "No reply needed",
                        )
                    )
            db.commit()

        add_meetings(db, fake="--no-llm" in sys.argv)
        add_tasks(db)

        result = email_agent.analyze_pending(db)  # the rest (Low rules, or everything with LLM)
        print(
            f"Added {len(DEMO)} demo emails. Analyzed now: {result.analyzed} "
            f"(High {result.high}, Low {result.low})."
        )
        for error in result.errors:
            print("Error:", error)


if __name__ == "__main__":
    main()
