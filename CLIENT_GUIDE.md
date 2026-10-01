# Email & Meeting Portal - Install and User Guide

This guide is for the person who will **use** the portal on their own computer. Follow the
steps in order. It takes about **1 hour** the first time (most of it is waiting for downloads).

---

## 1. What the portal does

| Part | What it does for you |
| --- | --- |
| **Email agent** | Reads your new Gmail emails, marks each one **High** or **Low**, and writes a draft reply. You edit and send. |
| **Meeting recorder** | Records your online meetings (Google Meet, Zoom, Teams) on your computer and writes the transcript (Arabic, English or mixed). |
| **Meeting agent** | Summarizes each meeting: key facts, decisions, risks, blockers, and **who must do what**. |
| **Daily Tasks** | Only **your own** tasks from emails and meetings, a morning plan and an end-of-day summary. |
| **Meet helper** (browser extension) | In Google Meet: records from the moment you join until you leave, turns on the captions, and gives every voice its real name. |

Everything is **free**. Your emails, recordings and tasks stay **on your computer**. Only the
text that must be summarized is sent to Google Gemini (see section 16, Privacy).

---

## 2. Why it runs on your own computer (not on a server)

The recorder listens to **your** microphone (you) and **your** speakers (the other people).
A server in the cloud cannot hear your meetings, and the Meet helper talks to the portal on
your own computer (`localhost`). So the portal is installed **on the Windows computer you use
for meetings**, and it starts by itself when you log in to Windows.

> A cloud server copy (Docker) is possible for the email part only - **without** recording
> meetings. Ask the developer if you need that.

---

## 3. What you need

| Need | Details |
| --- | --- |
| **Windows 10 or 11** computer | The one you use for meetings. A normal laptop is fine. |
| Free disk space | About **5 GB** (programs + the speech-to-text model) |
| Memory | At least **8 GB RAM** (the speech-to-text model uses about 3-4 GB while working) |
| A **Google account** (Gmail) | For emails, calendar and Google Meet |
| **Chrome** or **Edge** | For the Meet helper |
| **Headphones** | Recommended for meetings (wired, or Bluetooth in stereo mode) |
| Internet | For Gmail, Gemini and the first downloads |

---

## 4. Install the programs (once)

Install these three free programs. Keep the default options.

1. **Python 3.12** - https://www.python.org/downloads/
   On the first screen, tick **"Add python.exe to PATH"**.
2. **Node.js (LTS)** - https://nodejs.org (only needed to build the portal pages)
3. **Git** - https://git-scm.com/download/win (to download and update the portal)

Check them: open **PowerShell** and type:

```powershell
python --version
node --version
git --version
```

You should see a version number for each (Python must be **3.12** or newer).

---

## 5. Get the portal (once)

In PowerShell, go to the folder where you want the portal (for example your Documents) and
download it:

```powershell
cd $HOME\Documents
git clone https://github.com/saifjamal365-cmd/emails-meetings-portal.git
cd emails-meetings-portal
```

> If the repository is private, the developer must give your GitHub account access first, or
> send you the project as a ZIP file (then unzip it and `cd` into the folder).

Now install the portal's parts. **Run these commands from the `emails-meetings-portal`
folder.** This takes 5-15 minutes:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -e .
cd ..\frontend
npm install
npm run build
cd ..
```

---

## 6. Get your free Gemini key (the AI)

1. Open https://aistudio.google.com/apikey and sign in with your Google account.
2. Click **Create API key** and copy it.
3. Keep it private, like a password.

---

## 7. Connect your Google account - Google Cloud setup (once, about 15 minutes)

The portal needs permission to read your Gmail, calendar and Google Meet. You create this
permission yourself, in your own free Google Cloud project:

1. Open https://console.cloud.google.com and sign in.
2. At the top, click the project list -> **New project** -> name it `Email Portal` -> **Create**.
   Make sure this new project is selected.
3. **APIs & Services -> Library**. Search and **Enable** each of these:
   - **Gmail API**
   - **Google Calendar API**
   - **Google Meet REST API**
4. **APIs & Services -> OAuth consent screen** (or **Google Auth Platform**):
   - User type: **External**
   - App name: `Email Portal`, support email: your email, developer email: your email
   - **Audience / Test users**: add **your own Gmail address**
5. **APIs & Services -> Credentials -> Create credentials -> OAuth client ID**:
   - Application type: **Web application**
   - Name: `Email Portal`
   - **Authorized redirect URIs** -> Add URI:
     `http://localhost:8000/api/auth/google/callback`
   - Click **Create**, then copy the **Client ID** and the **Client secret**.

> **Important - stay connected:** while the app is in **"Testing"**, Google disconnects it
> about **every 7 days** (the portal then shows "Reconnect"). To avoid that, go to
> **OAuth consent screen / Audience** and click **Publish app** ("In production"). For your own
> use you do **not** need Google's verification: when you connect, Google shows "Google hasn't
> verified this app" -> click **Advanced -> Go to Email Portal (unsafe)** once. It is your own
> app.

---

## 8. Your settings file `.env` (once)

1. In the folder `backend`, copy the example file:

   ```powershell
   copy backend\.env.example backend\.env
   notepad backend\.env
   ```

2. Fill in these lines (no spaces around `=`), then save:

   ```
   GEMINI_API_KEY=your-gemini-key
   PORTAL_PASSWORD=choose-a-strong-password
   GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=your-client-secret
   FRONTEND_ORIGIN=http://localhost:8000
   ```

   - `PORTAL_PASSWORD` is the password **you** will use to open the portal.
   - `FRONTEND_ORIGIN` must be exactly `http://localhost:8000`, or the Google login will not
     come back to the portal.
   - **Never share this file.** It holds your keys.

3. Optional: the main language of your meetings. Arabic is the default. For meetings mostly
   in English add: `WHISPER_LANGUAGE=en`

---

## 9. First start and test

In PowerShell, from the `emails-meetings-portal` folder:

```powershell
backend\.venv\Scripts\python backend\run_portal.py
```

Leave this window open, then:

1. Open **http://localhost:8000** in Chrome and log in with your `PORTAL_PASSWORD`.
2. Go to **Settings -> Google account -> Connect Google** and allow everything.
   (If Google warns "hasn't verified this app": **Advanced -> Go to Email Portal**.)
3. Go to the **Dashboard** and click **Refresh**: your unread emails come in and get High/Low.

If this works, close the PowerShell window (this stops the test server) and continue.

---

## 10. Start it with Windows (once)

So the portal runs by itself every time you log in (hidden, no window). In PowerShell, from
the `emails-meetings-portal` folder, paste this whole block:

```powershell
$folder = (Resolve-Path .\backend).Path
$action = New-ScheduledTaskAction -Execute "$folder\.venv\Scripts\pythonw.exe" `
  -Argument "`"$folder\run_portal.py`"" -WorkingDirectory $folder
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "Email Meeting Portal" -Action $action -Trigger $trigger -Settings $settings
Start-ScheduledTask -TaskName "Email Meeting Portal"
```

Open **http://localhost:8000** - the portal is there. Add it to your browser bookmarks.

Useful commands:

```powershell
Start-ScheduledTask -TaskName "Email Meeting Portal"     # start now
Stop-ScheduledTask -TaskName "Email Meeting Portal"      # stop
Get-Content backend\data\logs\portal.log -Tail 30       # see what it did last
```

---

## 11. Install the Meet helper (once, in Chrome or Edge)

1. Open `chrome://extensions` (Edge: `edge://extensions`).
2. Turn on **Developer mode** (Chrome: top-right corner; Edge: bottom of the left menu).
3. Click **Load unpacked** and choose the folder `emails-meetings-portal\extension`.
4. Go to your portal tab and **reload it (F5)**. It connects by itself in a few seconds.
5. **Settings -> Google Meet helper** shows **Connected**.

---

## 12. Turn on the automatic features (Settings page)

| Setting | What to do |
| --- | --- |
| **Auto-record my online meetings** | Turn **on** |
| **Auto-summarize my meetings** | Turn **on** |
| **Meeting words** | Add names and words from your meetings (people, clients, projects, short words like HR). It helps the transcript. |
| **Sender rules** | Optional: email domains that are always High or always Low |
| **Remember the voices** | Optional. Turn on **only after the people in your meetings agreed** (a voice print is personal data). |

---

## 13. Daily use

**Emails**
- **High Priority**: emails that need you, with a draft reply. Edit it and click **Send**
  (nothing is sent without your click).
- **Low Priority**: newsletters, social media and similar.

**Meetings**
- **Google Meet**: just **join** the call. Recording starts when you join and stops 60 seconds
  after you leave. The captions turn on by themselves.
- **Zoom / Teams in your calendar**: recording starts by the calendar time.
- **A meeting that is not in the calendar (Zoom/Teams)**: **Meetings -> Record now**, then **Stop**.
- **Tell the other people that the meeting is recorded** - in many countries this is the law.
- In **Google Meet -> Settings -> Audio**, use your **laptop microphone** and your headphones
  as **speakers** (see Troubleshooting if you use Bluetooth earbuds).
- A few minutes after the meeting: open **Meetings** to see the summary, who spoke, the
  decisions and the tasks. A long meeting takes longer (about half of the meeting time).
- **The very first meeting takes longer**: the portal downloads its speech-to-text model once
  (about 1.6 GB). Make a short test meeting first, for example a Google Meet call alone.

**Daily Tasks**
- Your own tasks from emails and meetings, with due dates. Add, edit and mark them done.
- **Morning plan** at 8:00 and **end-of-day summary** at 18:00.

---

## 14. Troubleshooting

| Problem | What to do |
| --- | --- |
| The portal does not open | `Start-ScheduledTask -TaskName "Email Meeting Portal"`, wait 20 seconds, open http://localhost:8000 again. Check the log: `Get-Content backend\data\logs\portal.log -Tail 30` |
| Settings shows **Reconnect** for Google | Click it. If it happens every week, publish the Google app (section 7). |
| Meet helper says **Not connected** | Reload the portal page (F5) in the browser where the extension is installed. In `chrome://extensions`, check the extension is switched on. |
| The meeting summary has **only your voice** | The other people's voices did not go to your speakers. With **Bluetooth earbuds**, do **not** use the earbuds' microphone in Meet: choose the **laptop microphone**, and as speaker the earbuds' **"Stereo"/"Headphones"** device (not "Hands-Free"). |
| "No speech was found in the recording" | Nobody talked, or the microphone is muted / blocked in Windows: **Settings -> Privacy -> Microphone** -> allow apps. |
| "Free Gemini limit reached" | The free daily limit was used. It works again the next day; the portal tries other free models first. |
| A wrong name for a voice | Open the meeting -> **Who spoke** -> **Change**. |
| A task that is not yours | Delete it in Daily Tasks and tell the developer (this should not happen). |

---

## 15. Update to a new version

```powershell
cd $HOME\Documents\emails-meetings-portal
Stop-ScheduledTask -TaskName "Email Meeting Portal"
git pull
backend\.venv\Scripts\python -m pip install -e backend
cd frontend; npm install; npm run build; cd ..
Start-ScheduledTask -TaskName "Email Meeting Portal"
```

Then reload the Meet helper: `chrome://extensions` -> the **circular arrow** on its card.

---

## 16. Privacy and rules

- **Recording**: always tell the people in the meeting that it is recorded.
- **Audio** is deleted after the transcript is made. Transcripts, summaries and emails stay in
  the portal on your computer (`backend\data`).
- **Google Gemini (free tier)**: the email and meeting text is sent to Gemini to be summarized.
  On the free tier Google may use it to improve its products. Check that your company allows
  this before you use it for work meetings.
- **Voice memory** (off by default): voice prints are personal (biometric) data. Use it only
  with the people's agreement. They are stored encrypted and can be deleted in Settings.
- **Delete my data** (Settings) deletes all saved emails, meetings, tasks, captions and voices.
- To remove the portal: `Unregister-ScheduledTask -TaskName "Email Meeting Portal"
  -Confirm:$false`, remove the extension, then delete the folder.
