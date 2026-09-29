# Email & Meeting Portal

A multi-agent web portal:

- **Email Priority Agent** – reads unread emails, gives High or Low priority, and writes draft replies.
- **Meeting Summary Agent** – gets meeting transcripts (Arabic / English) by itself and returns action items, owners, decisions, risks and blockers.
- **Daily Tasks** – turns both agents' results into tasks, a morning plan, and an end-of-day summary.

Emails that contain keywords from a recent meeting become High and get a "Connected to meeting" label.

**Status:** All 6 phases are built: setup, Email agent + High/Low reply pages, Meeting agent
with Google Meet transcripts, the Meeting-Email link, the Daily Tasks page, and Phase 6
(login, notifications, security checks, test sets, deploy files). Still to do by you: add the
API key, connect Google, run the test sets, and deploy.

## Folder structure

```
email-meeting-portal/
  backend/                 Python + FastAPI
    app/
      main.py              FastAPI app, routes, CORS
      config.py            settings from .env
      db.py                database engine and session (SQLite now)
      models.py            all database tables
      jobs.py              background jobs: Gmail every 5 min, meetings every 10 min (auto mode),
                           morning plan 8:00, day summary 18:00
      routes/              API: auth (login), emails, meetings, tasks, reports, notifications,
                           data (delete my data), google_auth, settings, llm, health
      agents/
        email_agent.py     Agent 1: rules -> LLM -> priority + draft reply
        meeting_agent.py   Agent 2: find meetings -> transcript -> summary -> tasks
        linker.py          Meeting-Email link: meeting keywords in emails -> High + label
        planner.py         Daily planner: facts from tasks/emails/meetings -> plan text
      services/
        llm_client.py      all Gemini calls (text and structured JSON), free-tier spacing
        google_client.py   Google login (one login for Gmail, Calendar and Meet)
        mail_client.py     Gmail: read unread, send reply, mark read, archive
        meeting_client.py  Calendar: finished Meet meetings. Meet API: transcripts + speakers
        tasks.py           task helpers (from email, status, source label)
        crypto.py          encrypts the saved Google login
      prompts/             prompt text files
    scripts/seed_demo.py   sample emails, meetings and tasks to try the pages without Google
    scripts/eval_agents.py test sets: 30 labeled emails + 3 meetings, with the real LLM
    tests/
    .env.example           copy to .env and add your API key
  frontend/                React + Vite + Tailwind CSS
    src/
      pages/               Login, Dashboard, Inbox (High/Low), AllEmails, Meetings, Tasks, Settings
      components/          Layout, NotificationBell, EmailDetail, MeetingDetail, ReportCard, TaskForm
      api.js               helper to call the backend
```

## Everything is free

| Part | Free how |
| --- | --- |
| LLM | **Google Gemini free tier** - key from https://aistudio.google.com/apikey, no card needed |
| Gmail + Calendar APIs | Free with a normal Google account |
| Meeting transcripts | **Upload transcript** (free Google accounts cannot save Meet transcripts - see below) |
| Hosting | Run it on your own computer (free cloud plans sleep, so the timed jobs would stop) |

**Free-tier notes:**
- **Privacy:** on the free tier, Google says the content you send is "used to improve our
  products". Here that means the text of your emails and meeting transcripts. Only use it
  with emails you are OK to share that way.
- **Limits:** the free tier allows only a few requests per minute and per day, **per model**
  (for example `gemini-3.8-flash`: only 20 per day). See your numbers at
  https://aistudio.google.com/rate-limit. So the portal uses a chain of free models:
  `gemini-3.1-flash-lite` (main), then `gemini-3.5-flash-lite`, then `gemini-3.8-flash`
  (`LLM_MODEL`, `LLM_FALLBACK_MODELS`). If a model is busy (503) the call is tried again and
  then goes to the next model; a model that used its daily limit is skipped until tomorrow.
  Calls are spaced by `LLM_MIN_SECONDS_BETWEEN_CALLS` (6 s). When all models are full, the
  agents stop and continue at the next check.
- **Busy models:** free models are sometimes "experiencing high demand" for a while. The
  portal then shows "The free Gemini models are busy" - just try again later.
- Rule-based emails (social, newsletters, no-reply, "Always Low") never use the LLM, so
  adding senders to "Always Low" saves your free quota.

## Run it (Windows)

**1. Backend** (first time only: create the `.env` file)

```bash
cd backend
copy .env.example .env
```

Open `backend/.env` and set `GEMINI_API_KEY` and `PORTAL_PASSWORD` (your login password).
Then start the API:

```bash
cd backend
.venv\Scripts\activate
uvicorn app.main:app --reload
```

The API runs on http://localhost:8000. API docs: http://localhost:8000/docs

**2. Frontend** (in a second terminal)

```bash
cd frontend
npm run dev
```

Open http://localhost:5173. On the Dashboard, click **Send to LLM**.

## Try it without Google (demo data)

```bash
cd backend
.venv\Scripts\python -m scripts.seed_demo --no-llm
```

This adds 7 sample emails, 3 sample meetings and 3 sample tasks (Arabic and English) with
ready results.
Without `--no-llm`, the real agents do the work (needs `GEMINI_API_KEY`). Remove them with
`--clear`.
Sending a reply to a demo email fails, because it is not in Gmail.

## Connect Google (one time)

You do these steps yourself in the Google Cloud Console, with your own Google account:

1. Go to https://console.cloud.google.com and create a project (for example "Email Portal").
2. **APIs & Services -> Library**: enable the **Gmail API**, the **Google Calendar API** and the
   **Google Meet REST API**.
3. **APIs & Services -> OAuth consent screen**: choose **External**, fill in the app name and
   your email. Under **Test users**, add the Gmail address you want to connect.
4. **APIs & Services -> Credentials -> Create credentials -> OAuth client ID**:
   - Application type: **Web application**
   - Authorized redirect URI: `http://localhost:8000/api/auth/google/callback`
5. Copy the **Client ID** and **Client secret** into `backend/.env`:
   `GOOGLE_CLIENT_ID=...` and `GOOGLE_CLIENT_SECRET=...`
6. Restart the backend. In the portal open **Settings -> Connect Google** and allow access.

The portal asks for these permissions only: read and label emails (`gmail.modify`), send
replies (`gmail.send`), read the calendar (`calendar.readonly`) and read Meet meetings and
transcripts (`meetings.space.readonly`). The login is saved encrypted in the database. Nothing
is sent without your click on **Send**.

If you connected Google before Phase 3, Settings shows **Reconnect**: click it once to allow
Calendar and Meet.

After connecting, the agent checks Gmail every 5 minutes (change with `EMAIL_SYNC_MINUTES`),
or click **Refresh**.

## Automatic meetings on a free account: the meeting recorder

Free Google accounts cannot save Meet transcripts, so the portal can record meetings itself,
on your computer, for free:

1. **Settings -> Auto-record my online meetings** (off by default).
2. Every minute the backend looks at your calendar. When a meeting with a **Meet, Zoom or
   Teams** link starts, it records two tracks: your **microphone** (= you) and your
   **speakers** (= the others). You get a notification "Recording: ...".
3. At the calendar end time it stops (if people still talk, it keeps going 5 minutes more,
   up to `RECORD_MAX_EXTRA_MINUTES`).
4. **Whisper** (faster-whisper, model `WHISPER_MODEL`, default `large-v3-turbo`) writes the
   transcript on your computer - private and offline. The first time it downloads the model (~1.6 GB)
   into `backend/data/whisper`. Your name is on your lines, "Others" on the rest.
5. The Meeting agent summarizes it, adds your tasks and links emails. The audio is deleted
   (unless `KEEP_RECORDINGS=true`). You get "Meeting summarized: ...".

For a meeting that is not in your calendar: **Meetings -> Record now -> Stop**.

Good to know:
- **Tell the other people** that the meeting is recorded (required by law in many countries).
- Use **headphones**, so the others' voices do not also go into your microphone.
- **Settings -> Meeting words**: add names and words from your meetings (people, clients,
  projects, short words like HR). Whisper and the summary use them as hints, so they are
  written correctly.
- Only **your** action items become Daily Tasks. Other people's items, and blockers, stay in
  the meeting summary (blockers also show in the morning plan under "Watch out").
- The backend must be running on this computer during the meeting (not in the cloud).
- Model and speed (measured on an Intel i5-8250U laptop): `large-v3-turbo` (default) gives the
  best Arabic but needs about 6 seconds of CPU per second of speech, so a 1-hour meeting is
  ready a few hours later, in the background. `small` is about 5x faster but weak for spoken
  Arabic. Change it with `WHISPER_MODEL` in `backend/.env`.

## How the Meeting agent gets transcripts

1. **Refresh** (or auto mode) reads your calendar: finished events from the last 14 days that
   have a Google Meet link. Title, time, organizer and attendees come from the calendar
   (this is the "Meeting-owner mapping").
2. For each meeting it asks the Meet API for the transcript, with the speakers' names.
   Status: **Transcript ready**, **Waiting for transcript** (it can take some minutes after
   the meeting), or **No transcript**.
3. Click **Summarize** (choose Arabic, English or "same as meeting"). The agent returns the
   overview, key facts (budget, amounts), action items with owners, decisions, risks, blockers
   and keywords, creates tasks for your own action items only, and writes the Integration logs.
4. **Auto mode** (Settings -> "Auto-summarize my meetings"): every 10 minutes new transcripts
   are summarized for you.

**Important - free accounts:** Google Meet saves transcripts only with a paid Google
Workspace plan (Business Standard or higher). With a free Gmail account, the meetings still
show in the list (from your calendar) as "No transcript". Then:
1. During the meeting, save the captions as a text file - for example with a free browser
   extension that saves Google Meet captions, or copy the live captions.
2. On the Meetings page click **Upload transcript** and choose the file (.txt, .vtt or .srt).
3. Click **Summarize**. Everything after that (tasks, email links, plans) is automatic.

## Login, notifications and your data

- **Login:** set `PORTAL_PASSWORD` in `backend/.env`. The portal then asks for it and keeps you
  logged in for 7 days (`SESSION_DAYS`). After 5 wrong passwords in 15 minutes, login is
  blocked for 15 minutes. In production the password is required.
- **Notifications** (the bell in the side menu): new High emails, meetings summarized in auto
  mode, the morning plan and day summary, and problems (like an expired Google login).
  "Also show them as desktop notifications" shows them outside the browser tab too.
- **Delete my data** (Settings): deletes the portal's copies of emails, meetings, tasks, plans,
  notifications and logs. Your emails stay in Gmail.
- The backend sends security headers (no framing, no content sniffing, a content security
  policy, HSTS in production). Google logins are saved encrypted. Email and meeting text is
  treated as data, never as instructions for the LLM.

## Deploy (production) - optional, not free

The free way is to run the portal on your own computer (see "Run it"). Cloud hosting with a
permanent disk costs money, so this part is only for later. The app runs as **one container**: the backend also serves the built portal. Files:
`Dockerfile`, `.dockerignore` (keeps `.env` and data out of the image) and `render.yaml`.

**Render (recommended):**
1. Put the project on GitHub (without `.env` - it is git-ignored).
2. Render -> **New -> Blueprint** -> choose the repository. It reads `render.yaml`: one web
   service, a 1 GB disk at `/data` for the database and keys (a paid plan is needed for the disk).
3. In the Render dashboard fill in: `PORTAL_PASSWORD`, `GEMINI_API_KEY`,
   `FRONTEND_ORIGIN=https://<your-app>.onrender.com`, `GOOGLE_CLIENT_ID`,
   `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI=https://<your-app>.onrender.com/api/auth/google/callback`.
4. In Google Cloud Console, add the same redirect URI to your OAuth client.

**Railway or any Docker host:** build the `Dockerfile`, add a volume at `/data`, set the same
variables, and run **one** instance (the background jobs run inside the app).

**Try the container locally** (Docker Desktop must be running):

```bash
docker build -t email-meeting-portal .
```

```bash
docker run -p 8000:8000 --env-file backend/.env -e FRONTEND_ORIGIN=http://localhost:8000 -v portal-data:/data email-meeting-portal
```

**Good to know:**
- While the Google OAuth app is in **Testing** mode, Google ends the login after about 7 days;
  the portal then shows a "Google login expired" notification and you click **Reconnect**.
- SQLite on the disk is fine for one user. For a team, use PostgreSQL (`DATABASE_URL`).

## How meetings and emails are linked

When an unread email contains keywords from a meeting in the last 7 days, the email becomes
**High** and gets the label **"Meeting: <title> (<date>)"**. The matched words are highlighted
in the email, and the meeting page lists its linked emails.

- Score: +1 per matched keyword, +2 if one is in the subject, +2 if the sender was in the meeting.
- Score 3 or more **and** (2+ keywords or the sender was in the meeting) -> linked at once.
- Weaker matches -> the LLM checks "is this email really about this meeting?". So one common
  word like "contract" is never enough alone.
- Arabic and English: `أ/إ/آ`, `ة/ه`, `ى/ي` and tashkeel are treated as the same, and "ال" is
  removed from keywords, so "العقد" also finds "عقد" and "بالعقد".
- It works both ways: for every new email, and for recent unread emails after every new summary.
- Social / newsletter / no-reply emails (Low by rule) are never linked. If you set a priority
  yourself, it stays; only the label is added.
- **Not related** removes a wrong link, puts the priority back, and the link does not come back.
- Common words are ignored (`stop_words` in the settings table, plus a built-in list).

## Daily Tasks

**Where tasks come from:** your own (**+ New task**), your own action items from
meeting summaries, High emails that have a deadline, and **Add to tasks** on any email.
A task is never created twice for the same email or the same meeting item.

**The board:** To do / In progress / Done. Drag a card to change its status, click it to edit
(title, description, due date, priority, status, notes) or delete it. Late tasks are red.
The Done column shows today's finished tasks ("Show all done tasks" shows the rest).

**Start of day and end of day:** made automatically at 8:00 and 18:00 (change with
`MORNING_PLAN_HOUR` / `EVENING_SUMMARY_HOUR`, -1 = off), or click the button.
1. The planner collects the facts: late tasks, tasks due today, High emails waiting for a
   reply, recent meeting decisions, risks and blockers (evening: tasks done, replies sent,
   today's meetings).
2. The LLM writes a short plan: top priorities first, then emails to answer, other tasks and
   things to watch. The evening summary ends with "For tomorrow", and the next morning plan
   reads it.
3. Without the LLM (no key, no internet) the facts are saved as a **basic plan**, so you
   always get something.

You can edit the text. The automatic job never replaces a plan that already exists. Past days
are in the "Plans for" list.

## How the Email agent decides

1. **Rules first (free):** Settings -> "Always High" / "Always Low" sender domains, no-reply
   senders, and Gmail's Social / Promotions tabs -> Low. Low rule emails never go to the LLM.
2. **LLM:** everything else. Companies, clients, partners and products -> High; social media,
   newsletters and promotions -> Low; when unsure -> High. The LLM also writes a draft reply
   in the email's language and finds deadlines.
3. **You:** move an email between High and Low, edit the reply, regenerate it with a note
   ("shorter", "in Arabic"), send, skip, or add it to Daily Tasks.

## First-time install (only if `.venv` or `node_modules` is missing)

```bash
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
cd ..\frontend
npm install
```

## Tests, lint and security checks

```bash
cd backend
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m pip_audit --skip-editable
```

The tests use a fake LLM and fake Google answers, so they need no keys. `ruff` includes the
security rules (the same as Bandit). `pip_audit` and `npm audit` (in `frontend`) check the
libraries for known security problems.

## Test sets with the real LLM (from the plan)

```bash
cd backend
.venv\Scripts\python -m scripts.eval_agents --meetings
```

- **30 labeled emails** (15 High, 15 Low, Arabic and English): prints how many priorities are
  right (goal: 90% or more) and the reason for every wrong one.
- **3 meetings** (Arabic, English, mixed): prints the summaries so you can check the action
  items, owners, decisions and keywords.

It uses a temporary database (your data is safe) and about 33 calls of your free Gemini
quota (it takes a few minutes because calls are spaced out). If the accuracy is too low, improve
`app/prompts/email_priority.txt` and run it again.

## Next: Phase 2 – Email agent

Connect Gmail (Google Cloud project + OAuth), read unread emails, add the priority rules and the LLM check, and build the High and Low reply pages.
