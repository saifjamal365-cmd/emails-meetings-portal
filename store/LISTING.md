# Chrome Web Store - texts to copy

Upload `store/meet-helper.zip` (made by `store/make_zip.ps1`). Copy the texts below into
the Developer Dashboard fields.

## Store listing

**Name** (from the manifest): Communication Portal - Meet helper

**Summary** (from the manifest): Tells your Communication Portal (on this computer) when you
join and leave a Google Meet call, and who speaks when (from the live captions).

**Description:**

```
The helper for the free Communication Portal, which you run on your own computer:
https://github.com/saifalrashadeh-star/Communication_Portal

- Records your Google Meet calls from the moment you join until you leave (the portal records).
- Turns on Google Meet's live captions by itself.
- Notes who speaks when, so your meeting summary shows real names instead of "Speaker 1".
- Sends the captions to your portal, to help the summary.

Private by design: the extension sends data ONLY to the portal on your own computer
(localhost:8000). No audio, no other websites, no tracking, nothing sent to the developer.

You need the portal installed first (see the link above). Then open the portal page once:
the extension connects by itself.
```

**Category:** Productivity   **Language:** English

**Images:**
- Icon: `extension/icons/icon128.png` (already inside the ZIP)
- Screenshot (1280 x 800): `store/screenshot-1280x800.png`

## Privacy practices tab

**Single purpose:**

```
Tell the user's own Communication Portal, running on the same computer, when the user joins
and leaves a Google Meet call and who speaks when, so the portal can record the meeting and
name the speakers in the summary.
```

**Permission justifications:**

| Permission | Justification to paste |
| --- | --- |
| `storage` | Keeps the key that connects the extension to the user's own portal, and messages that wait while the portal is not running. |
| `alarms` | Tries again every minute to send waiting messages to the portal on this computer, after it starts. |
| Host `http://localhost:8000/*`, `http://127.0.0.1:8000/*` | The user's own portal runs on this computer at this address. The extension sends its messages only there, and reads the connection key from the logged-in portal page. |
| Content script on `https://meet.google.com/*` | Notes when the user joins and leaves a call, turns on the live captions, and reads the speaker names, times and caption words. |

**Remote code:** No, I am not using remote code.

**Data usage** - tick:
- Personally identifiable information (speaker names in the captions)
- Website content (caption words on Google Meet)

Then tick all three statements: not sold to third parties, not used for unrelated purposes,
not used for creditworthiness or lending.

**Privacy policy URL:**

```
https://github.com/saifalrashadeh-star/Communication_Portal/blob/main/PRIVACY.md
```

## Distribution

Visibility: **Public** (or **Unlisted**: only people with the link can find it).
