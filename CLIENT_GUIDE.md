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
text that must be summarized is sent to Google Gemini (see section 15, Privacy).

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

## 4. Install Python (once)

1. Download **Python 3.12 or newer** from https://www.python.org/downloads/
2. On the first screen of the installer, tick **"Add python.exe to PATH"**, then click
   **Install Now**.

That is the only program you need. (Node.js and Git are not needed.)

---

## 5. Get the portal

1. Open https://github.com/saifalrashadeh-star/Communication_Portal
2. Click the green **Code** button -> **Download ZIP**.
3. Unzip it into a folder that OneDrive does **not** sync, for example
   `Documents\Communication_Portal`. (Syncing can break the database.)

> With Git you can instead run
> `git clone https://github.com/saifalrashadeh-star/Communication_Portal.git`

---

## 6. Run the installer (once)

1. Open the portal folder and **double-click `setup.bat`**.
2. If Windows shows "Windows protected your PC", click **More info -> Run anyway**.
3. Wait. The first time it downloads the libraries (**5-15 minutes**). It also makes the
   portal start by itself every time you log in to Windows (hidden, no window).
4. When it says **Done**, the portal opens in your browser at **http://localhost:8000**
   with the **Setup** page.

Keep the next two sections open: the Setup page asks for the keys they give you.

---

## 7. Get your free Gemini key (the AI)

1. Open https://aistudio.google.com/apikey and sign in with your Google account.
2. Click **Create API key** and copy it.
3. Keep it private, like a password.

---

## 8. Get your Google keys - Google Cloud setup (once, about 15 minutes)

The portal needs permission to read your Gmail, calendar and Google Meet. You create this
permission yourself, in your own free Google Cloud project. **No payment method is needed** -
if a page asks for a card ("Free trial"), close it.

1. Open https://console.cloud.google.com/projectcreate and sign in. Name the project
   `Email Portal` -> **Create**. Make sure this project is selected in the top bar.
2. **APIs & Services -> Library**. Search and **Enable** each of these:
   - **Gmail API**
   - **Google Calendar API**
   - **Google Meet REST API**
3. **APIs & Services -> OAuth consent screen** (or **Google Auth Platform**):
   - App name: `Email Portal`, support email: your email
   - User type / Audience: **External**
   - **Test users**: add **your own Gmail address**
4. **APIs & Services -> Credentials -> Create credentials -> OAuth client ID**:
   - Application type: **Web application** (not "Desktop app")
   - Name: `Email Portal`
   - **Authorized redirect URIs** -> Add URI:
     `http://localhost:8000/api/auth/google/callback`
   - Click **Create**, then copy the **Client ID** and the **Client secret**.

> **Important - stay connected:** while the app is in **"Testing"**, Google disconnects it
> about **every 7 days**. To avoid that, go to **OAuth consent screen / Audience** and click
> **Publish app**. For your own use you do **not** need Google's verification: when you
> connect, Google shows "Google hasn't verified this app" -> click **Advanced -> Go to Email
> Portal (unsafe)** once. It is your own app.

---

## 9. The Setup page (once)

On http://localhost:8000 the **Setup** page asks for:

| Field | What to type |
| --- | --- |
| **Portal password** (twice) | A password **you choose** (8 characters or more). You use it to open the portal. |
| **Gemini API key** | The key from section 7 |
| **Google Client ID** | From section 8 (it ends with `.apps.googleusercontent.com`) |
| **Google Client secret** | From section 8 |

Click **Save and start**. The keys are saved only on this computer (in `backend\.env`) and
work at once. Saved keys are never shown again; to change one later, go to **Settings ->
Password and keys**.

Then:
1. **Settings -> Google account -> Connect Google** and allow everything.
   (If Google warns "hasn't verified this app": **Advanced -> Go to Email Portal**.)
2. **Dashboard -> Refresh**: your unread emails come in and get High/Low.

Optional, for meetings mostly in English: open `backend\.env` in Notepad, add the line
`WHISPER_LANGUAGE=en`, save, and restart the portal (or your computer). Arabic is the default.

---

## 10. Install the Meet helper (once, in Chrome or Edge)

1. Open `chrome://extensions` (Edge: `edge://extensions`).
2. Turn on **Developer mode** (Chrome: top-right corner; Edge: bottom of the left menu).
3. Click **Load unpacked** and choose the `extension` folder inside the portal folder.
4. Go to your portal tab and **reload it (F5)**. It connects by itself in a few seconds.
5. **Settings -> Google Meet helper** shows **Connected**.

---

## 11. Turn on the automatic features (Settings page)

| Setting | What to do |
| --- | --- |
| **Auto-record my online meetings** | Turn **on** |
| **Auto-summarize my meetings** | Turn **on** |
| **Meeting words** | Add names and words from your meetings (people, clients, projects, short words like HR). It helps the transcript. |
| **Sender rules** | Optional: email domains that are always High or always Low |
| **Remember the voices** | Optional. Turn on **only after the people in your meetings agreed** (a voice print is personal data). |

Useful commands (PowerShell):

```powershell
Start-ScheduledTask -TaskName "Email Meeting Portal"     # start now
Stop-ScheduledTask -TaskName "Email Meeting Portal"      # stop
Get-Content backend\data\logs\portal.log -Tail 30       # see what it did last
```

---

## 12. Daily use

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

## 13. Troubleshooting

| Problem | What to do |
| --- | --- |
| Setup page: "Choose a portal password" | Type a password in both password fields (8 characters or more). |
| The portal does not open | `Start-ScheduledTask -TaskName "Email Meeting Portal"`, wait 20 seconds, open http://localhost:8000 again. Check the log: `Get-Content backend\data\logs\portal.log -Tail 30` |
| Settings shows **Reconnect** for Google | Click it. If it happens every week, publish the Google app (section 8). |
| Meet helper says **Not connected** | Reload the portal page (F5) in the browser where the extension is installed. In `chrome://extensions`, check the extension is switched on. |
| The meeting summary has **only your voice** | The other people's voices did not go to your speakers. With **Bluetooth earbuds**, do **not** use the earbuds' microphone in Meet: choose the **laptop microphone**, and as speaker the earbuds' **"Stereo"/"Headphones"** device (not "Hands-Free"). |
| "No speech was found in the recording" | Nobody talked, or the microphone is muted / blocked in Windows: **Settings -> Privacy -> Microphone** -> allow apps. |
| "Free Gemini limit reached" | The free daily limit was used. It works again the next day; the portal tries other free models first. |
| A wrong name for a voice | Open the meeting -> **Who spoke** -> **Change**. |
| A task that is not yours | Delete it in Daily Tasks and tell the developer (this should not happen). |

---

## 14. Update to a new version

Your settings and data (`backend\.env` and `backend\data`) are kept.

1. **With the ZIP:** download the new ZIP and unzip it **over** your portal folder (replace
   the files). **With Git:** run `git pull` in the portal folder.
2. Double-click **`setup.bat`** again. It stops the portal, updates it and starts it again.
   Do not do this during a meeting recording.
3. Reload the Meet helper: `chrome://extensions` -> the **circular arrow** on its card.

---

## 15. Privacy and rules

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
