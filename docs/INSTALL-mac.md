# Installing ReefScanner on a Mac

ReefScanner watches long underwater videos for sharks and rays and shows you
the moments worth a look. Everything runs on your own computer — nothing is
uploaded anywhere.

**You need:** a Mac with an Apple chip (M1 or newer — check under  → About
This Mac), and about 2 GB of free space.

## 1. Install

1. Download **ReefScanner.dmg** from the link you were sent.
2. Double-click it. A window opens showing ReefScanner and an Applications
   folder.
3. Drag **ReefScanner** onto **Applications**. Wait for the copy to finish,
   then close that window.

## 2. Open it the first time

macOS blocks apps that weren't bought from the App Store or registered with
Apple. You only have to get past this once.

1. Open your **Applications** folder and double-click **ReefScanner**.
2. A message says ReefScanner can't be opened or can't be verified. Click
   **Done** — *not* "Move to Trash".
3. Open **System Settings** → **Privacy & Security**, and scroll down to the
   **Security** section.
4. Next to *"ReefScanner" was blocked…*, click **Open Anyway**, and enter your
   Mac password if asked.
5. Click **Open** in the message that follows.

From now on it opens with a normal double-click. The first launch can take a
little while — you'll see *"Starting ReefScanner…"* in the meantime.

## 3. Scan your first videos

1. Click **New project** and give it a name.
2. For **Footage folder** you need the folder's full path. The easy way to get
   it: in Finder, **right-click the folder while holding the Option (⌥) key**,
   choose **Copy "…" as Pathname**, then paste it into the box.
3. Leave **Results folder** empty — ReefScanner puts results next to your
   footage, in a folder ending in `_results`.
4. Click **Create project**, then **Scan footage**.

Scanning takes a while — roughly as long as the video on a laptop, sometimes
more. You can watch the progress bar.

## 4. Review what it found

Open the finished run and click any picture. Then, for each event:

| Press | Means |
|---|---|
| **T** | Yes, that's an animal |
| **F** | No, false alarm |
| **U** | Can't tell |
| **← →** | Previous / next |

Each answer jumps to the next event you haven't looked at, so you can go
through a whole run with the keyboard.

## If something goes wrong

- **It won't open at all:** redo step 2 — the "Open Anyway" button only
  appears for a while after you try to open the app.
- **Anything else:** send the file
  `~/Library/Logs/ReefScanner/reefscanner.log` to whoever gave you the app.
  To find it: in Finder, press **⌘⇧G**, paste
  `~/Library/Logs/ReefScanner`, and press Return.

Your projects and answers are kept between sessions, and survive installing a
newer version of the app.
