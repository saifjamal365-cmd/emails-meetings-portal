"""Test the agents with the real LLM on a small labeled test set (from the project plan).

    .venv\\Scripts\\python -m scripts.eval_agents            # 30 emails: is the priority right?
    .venv\\Scripts\\python -m scripts.eval_agents --meetings # + 3 meetings (ar / en / mixed)

Needs GEMINI_API_KEY in backend/.env. It uses your free Gemini quota (about 30 LLM calls for
the emails, 3 for the meetings; calls are spaced out, so it takes a few minutes). It uses a
temporary database, so your real data is not touched.
Goal from the plan: at least 90% of the email priorities are right.
"""

import os
import sys
import tempfile
from pathlib import Path

# A temporary database and no background jobs - before the app is imported.
_tmp = Path(tempfile.mkdtemp())
os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'eval.db').as_posix()}"
os.environ["DATA_DIR"] = _tmp.as_posix()

from datetime import datetime, timedelta  # noqa: E402

from app.agents import email_agent, meeting_agent  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import ActivityLog, Email  # noqa: E402

# (expected priority, sender, subject, body)
EMAILS = [
    # ---- High: clients, partners, suppliers, products, money, deadlines ----
    ("High", "ahmad@alnoor-trading.sa", "طلب عرض سعر - 200 وحدة",
     "السلام عليكم، نرغب في عرض سعر لـ 200 وحدة من منتجكم الجديد مع مدة التوريد قبل الخميس."),
    ("High", "sara@acme-logistics.com", "Contract renewal - please confirm by Oct 2",
     "Our shipping contract ends this month. Can you confirm the renewal and the new volume?"),
    ("High", "billing@cloudhost.io", "Invoice #4471 is overdue",
     "Your invoice #4471 (USD 320) was due on Sep 25. Please pay to avoid service interruption."),
    ("High", "procurement@gulfmedical.sa", "Purchase order PO-2291",
     "Please find attached our purchase order for 50 licenses. Kindly confirm delivery date."),
    ("High", "khalid@partner-tech.com", "Integration issue in production",
     "Our customers cannot log in since your last API update. This is urgent, please call me."),
    ("High", "noura@client-bank.com", "Meeting request: project kickoff",
     "Can we schedule the kickoff for the new dashboard project next week? Tuesday works for us."),
    ("High", "support-escalation@bigretail.com", "Complaint: wrong items delivered",
     "We received the wrong items in order 8812. We need a replacement by Monday."),
    ("High", "finance@supplier-co.com", "مطالبة مالية - فاتورة رقم 552",
     "نود تذكيركم بأن الفاتورة رقم 552 مستحقة منذ أسبوعين، نرجو السداد في أقرب وقت."),
    ("High", "legal@partner-law.com", "NDA ready for signature",
     "The NDA for the joint venture is ready. Please review and sign before Friday."),
    ("High", "omar@distributor-ksa.com", "طلب وكالة توزيع",
     "نحن شركة توزيع في الرياض ونرغب في أن نكون وكيلاً لمنتجاتكم. متى يمكننا الاجتماع؟"),
    ("High", "cto@startup-client.io", "Question about your enterprise plan",
     "We are evaluating your product for 300 users. Does the enterprise plan include SSO?"),
    ("High", "hr@t2.sa", "Action needed: approve leave requests",
     "You have 3 leave requests waiting for your approval. Please approve by end of day."),
    ("High", "fatima@ministry-partner.gov.sa", "تحديث بخصوص المناقصة",
     "نود إبلاغكم بأن موعد تقديم العروض للمناقصة تم تمديده إلى 10 أكتوبر. نرجو تأكيد المشاركة."),
    ("High", "account.manager@aws-partner.com", "Your credits expire in 5 days",
     "Your partner credits (USD 5,000) expire on Oct 3. Reply if you want to extend them."),
    ("High", "ali@client-hotel.com", "Feedback on the demo + next steps",
     "The demo was great. We want a price for the 12-month plan and a start date."),
    # ---- Low: social media, newsletters, promotions, automatic messages ----
    ("Low", "notification@facebookmail.com", "You have 3 new notifications",
     "See what your friends shared today."),
    ("Low", "messages-noreply@linkedin.com", "5 people viewed your profile",
     "See who viewed your profile this week."),
    ("Low", "news@techweekly.com", "This week in AI: 10 stories",
     "Top AI stories of the week, from new models to funding rounds."),
    ("Low", "offers@shop-deals.com", "خصم 50% لفترة محدودة!",
     "لا تفوت العرض! خصم 50% على جميع المنتجات حتى نهاية الأسبوع."),
    ("Low", "no-reply@accounts.google.com", "Security alert: new sign-in",
     "A new sign-in on Windows. If this was you, you don't need to do anything."),
    ("Low", "newsletter@marketing-blog.com", "10 tips to grow your brand",
     "Read our latest blog post about social media growth."),
    ("Low", "notify@twitter-x.com", "Trending in Saudi Arabia",
     "See what is trending today."),
    ("Low", "events@webinars-hub.com", "Free webinar: The future of work",
     "Join 5,000 people at our free webinar next month. Register now."),
    ("Low", "digest@medium.com", "Stories for you",
     "Today's highlights: productivity, design and startups."),
    ("Low", "info@airline-miles.com", "Your monthly miles statement",
     "Your balance is 12,300 miles. No action needed."),
    ("Low", "team@productivity-app.com", "What's new in version 4.2",
     "Dark mode, faster search and 20 bug fixes."),
    ("Low", "noreply@instagram.com", "sara_designs started following you",
     "See their profile."),
    ("Low", "promo@food-delivery.sa", "وجبتك المفضلة بخصم 20%",
     "استخدم الكود FOOD20 عند الطلب اليوم."),
    ("Low", "newsletter@industry-news.com", "Monthly industry report - September",
     "Our monthly summary of market news. Read online."),
    ("Low", "no-reply@calendar-tool.com", "Your weekly calendar summary",
     "You had 12 meetings last week. See your stats."),
]  # fmt: skip

MEETINGS = [
    (
        "Arabic meeting",
        """[09:00] عمر: صباح الخير. نبدأ بمراجعة عقد شركة النور.
[09:01] سارة: العقد جاهز لكن ننتظر موافقة الإدارة القانونية.
[09:02] عمر: سارة ترسلين قائمة الأسعار لشركة النور قبل يوم الخميس.
[09:03] سارة: تمام، أرسلها يوم الأربعاء.
[09:04] علي: المورد قال ممكن يتأخر أسبوعين في مشروع فالكون.
[09:05] عمر: إذا تأخر نؤجل الإطلاق إلى 15 أكتوبر.""",
    ),
    (
        "English meeting",
        """[14:00] Mark: Let's review the Q4 marketing plan.
[14:01] Lina: The campaign budget is approved: 40,000 USD.
[14:02] Mark: Lina, please send the final design to the agency by Monday.
[14:03] Tom: The agency is waiting for the brand guide before they can start.
[14:04] Mark: I will send the brand guide today.
[14:05] Lina: A risk: the printing company may be closed during the holidays.""",
    ),
    (
        "Mixed meeting",
        """[11:00] Omar: OK team, let's start. أول نقطة: موقع العميل الجديد.
[11:01] Sara: The client wants the website live by October 20.
[11:02] Ali: بس نحتاج المحتوى العربي من العميل، ما وصلنا للحين.
[11:03] Omar: Sara, can you follow up with the client for the Arabic content tomorrow?
[11:04] Sara: Sure, I'll call them tomorrow morning.
[11:05] Omar: قررنا نستخدم نفس التصميم للنسخة الإنجليزية والعربية.""",
    ),
]


def tokens_used(db) -> tuple[int, int]:
    tokens_in = tokens_out = 0
    for log in db.query(ActivityLog).all():
        tokens_in += (log.details or {}).get("input_tokens", 0)
        tokens_out += (log.details or {}).get("output_tokens", 0)
    return tokens_in, tokens_out


def eval_emails(db) -> None:
    now = datetime.now()
    for i, (_, sender, subject, body) in enumerate(EMAILS):
        db.add(
            Email(
                provider_id=f"eval-{i}",
                sender=sender,
                sender_name=sender.split("@")[0],
                sender_domain=sender.split("@")[1],
                subject=subject,
                body=body,
                received_at=now - timedelta(minutes=i),
            )
        )
    db.commit()

    print(f"Analyzing {len(EMAILS)} emails with {get_settings().llm_model} ...")
    result = email_agent.analyze_pending(db)
    if result.errors:
        sys.exit(f"Stopped: {result.errors[0]}")

    right, wrong = 0, []
    for i, (expected, sender, subject, _) in enumerate(EMAILS):
        email = db.query(Email).filter(Email.provider_id == f"eval-{i}").one()
        got = email.analysis.priority
        if got == expected:
            right += 1
        else:
            wrong.append((expected, got, sender, subject, email.analysis.reason))

    accuracy = right / len(EMAILS)
    print(f"\nEmail priority: {right}/{len(EMAILS)} right = {accuracy:.0%} (goal: 90%)")
    for expected, got, sender, subject, reason in wrong:
        print(
            f"  WRONG  expected {expected}, got {got}: {sender} - {subject}\n         why: {reason}"
        )
    print("PASS" if accuracy >= 0.9 else "BELOW GOAL - improve prompts/email_priority.txt")


def eval_meetings(db) -> None:
    print("\nSummarizing 3 meetings (check them by reading) ...")
    for title, transcript in MEETINGS:
        meeting = meeting_agent.add_uploaded(db, title, datetime.now(), transcript)
        s = meeting_agent.summarize(db, meeting)
        print(f"\n=== {title} (language: {s.detected_language}) ===\n{s.overview}")
        for item in s.action_items:
            print(f"  action: {item['task']}  | owner: {item['owner']} | due: {item['due']}")
        for label, items in (("decision", s.decisions), ("risk", s.risks), ("blocker", s.blockers)):
            for text in items:
                print(f"  {label}: {text}")
        print(f"  keywords: {', '.join(s.keywords)}")
        problems = [
            n
            for n, ok in (("no action items", s.action_items), ("no keywords", s.keywords))
            if not ok
        ]
        print(f"  check: {'OK' if not problems else ', '.join(problems)}")


def main() -> None:
    if not get_settings().gemini_api_key:
        sys.exit("Add GEMINI_API_KEY to backend/.env first.")
    init_db()
    with SessionLocal() as db:
        eval_emails(db)
        if "--meetings" in sys.argv:
            eval_meetings(db)
        tokens_in, tokens_out = tokens_used(db)
    print(f"\nTokens used (free tier): {tokens_in} in, {tokens_out} out")


if __name__ == "__main__":
    main()
