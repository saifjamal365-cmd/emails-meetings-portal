# Privacy policy - Meet helper extension

This policy is for the browser extension **"Communication Portal - Meet helper"** (the
`extension` folder of this project). It works only together with the Communication Portal
that **you** install and run on **your own computer**.

## What the extension reads

On Google Meet pages (`https://meet.google.com/*`) only:
- when you **join** and **leave** a call, and the call's meeting code;
- the **names** of the people who speak and **when** they speak, from Google Meet's live captions;
- the **caption words** that Google Meet shows.

It does **not** record or send any audio or video, and it reads no other website.

## Where the data goes

Only to the portal **on the same computer** (`http://127.0.0.1:8000` / `http://localhost:8000`).
The extension sends nothing to the developer or to any other server. There are no ads, no
analytics and no tracking.

The portal uses this data to know when to record your meeting and to name the voices in your
meeting summary. What the portal itself does with your data is described in its README.

## What the extension stores

In the browser's extension storage, on your computer:
- a key that connects the extension to your portal (the portal gives it when you are logged in);
- messages waiting to be sent while the portal is not running (at most 2000, deleted when sent).

## Sharing and selling

The data is never sold, never shared with anyone, and never used for advertising or credit.

## Deleting your data

- In the portal: **Settings -> Delete my data** deletes the saved captions and meetings.
- Removing the extension deletes its stored key and waiting messages.

## Contact

Questions: open an issue at https://github.com/saifalrashadeh-star/Communication_Portal/issues
