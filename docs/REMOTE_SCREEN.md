# Remote screen capture (RS1)

Lets somebody away from their desk ask their assistant to *look* at that computer. One
screenshot, taken here, on request, addressable afterwards so a follow-up question is
answered about the same picture rather than a new one.

## Routes

All under `/v1/screensense/`, always mounted. `capability` always answers 200 — a client has
to tell "this HomePilot is too old to know what you are asking" from "capture is switched off
on that machine" from "ready", and a 404 says neither.

| | |
|---|---|
| `GET /capability` | what this machine will do about a screenshot, right now |
| `POST /capture` | take one still → a frame handle |
| `GET /frame/{id}` | the JPEG. `no-store`. 404 once expired |
| `DELETE /frame/{id}` | forget it now |
| `POST /explain` | run the vision model over a frame that already exists |
| `GET /agent/poll`, `POST /agent/frame` | the sharing tab's side |

## The two mechanisms, in this order

**1. `share`** — a HomePilot tab holding a screen share the user granted and can see. It
long-polls `/agent/poll`, grabs a frame off the stream ScreenSense already owns, and posts it
back. No new permission, and the browser's own sharing bar is the indicator.

**2. `desktop`** — a direct grab via `mss` or Pillow. This one has no indicator of its own,
so it is off until `HOMEPILOT_REMOTE_CAPTURE=true` is set **on this machine**. Not settable
from the cloud, from the chat, or over any route here.

Never the other way round: path 2 could satisfy every request path 1 could, and if it ran
first the sharing bar would stop being what tells the user a picture was taken.

## Settings

| | default | |
|---|---|---|
| `HOMEPILOT_REMOTE_CAPTURE` | `false` | allow mechanism 2 |
| `HOMEPILOT_DEVICE_NAME` | hostname | what the card calls this machine |
| `HOMEPILOT_REMOTE_CAPTURE_TTL_S` | `600` | how long a frame lives |
| `HOMEPILOT_REMOTE_CAPTURE_MIN_INTERVAL_S` | `3` | floor between captures |
| `HOMEPILOT_REMOTE_CAPTURE_HOURLY_CAP` | `120` | ceiling per rolling hour |

## Retention

Frames live in `<UPLOAD_DIR>/screensense/` and are deleted past their TTL — from the index
*and* by a filesystem walk, so a restart that emptied the index still cleans up. Every
`desktop` capture is appended to `<UPLOAD_DIR>/screensense-audit.log`, which is never served.

## Removing it

Delete `backend/app/screensense/` and its one `include_router` line in `main.py`. Nothing
else refers to it.
