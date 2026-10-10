# Conversation Hub

Opening a persona project shows its Conversation Hub: the persona's identity
first, then the ways to talk to it. It is a visual and interaction upgrade
only — projects, sessions, memories and voice behave exactly as before. The
one API addition is the face crop below (additive, read-only).

![Conversation Hub on desktop and phone](../assets/readme/homepilot-hub.jpg)

## Layout

| Section | What it shows | What it does |
|---|---|---|
| Identity | The project's saved picture (circular, with a glow tinted from the picture), name, type badge, how long since it was created, memories stored, description | — |
| Continue Conversation | The latest conversation's type, message count and last activity | Reopens it. If the open conversation is still empty (e.g. Voice just started one), it reopens the most recent conversation that has messages. It never creates a new one. |
| Talk by Voice · Chat by Text | Side by side on desktop, stacked on phones | Resume the current conversation in that mode |
| Fresh voice chat · Fresh text chat | Secondary actions | End the current conversation and start a new one |
| Memories | Count, and **View All** | Opens the existing memory manager in place (forget one, forget all — with confirmation) |
| Conversation History | Newest first: date, type, messages, last activity, summary | Opens that conversation; **View All** beyond five; short conversations (< 3 messages) hidden unless asked for |

A persona with no conversations yet is welcomed with its picture, *Ready to meet
you*, and the two ways to start.

The hub is a `ModalSheet`: full-screen on phones, a centred card above;
Escape, the backdrop, the close button or the phone's Back gesture close it.

## The project's picture across the app

| Situation | Shown |
|---|---|
| No project open | The default HomePilot look (Voice: the five-bar icon) |
| Project without a picture | The project's type icon |
| Project with a picture | Its saved picture — project card, hub, chat header, beside its replies, and Voice |
| Project closed | The default look returns |

The picture always comes from the project's saved configuration
(`persona_appearance.selected_filename` / `selected_thumb_filename`), never a
generated stand-in. In Voice a static picture gets a ring that follows the
microphone level; the face itself is never animated. HomePilot has no
animated-avatar projects today, so no project switches to an animated face.

### Cropped to the face

Persona pictures are usually full-body (512×768, head to toe), and the stored
thumbnail is a square from the top — head to waist. In a 24–32 px circle that
left a face a few pixels wide. Every round frame (chat header, beside replies,
hub, Voice) now shows the picture cropped to the face:

`GET /projects/{id}/persona/avatar/face` returns a 320 px WebP square around
the face, written once next to the picture as `thumb_face_<stem>.webp` and
rewritten only when the picture changes. The face is found with InsightFace
when it is already loaded by another feature, otherwise with a skin-region
search in Pillow + numpy (the highest face-shaped region with eyes/mouth
contrast, cut at the neck; skin-toned walls are ignored). A picture with no
face found gets the regular top square. If the crop can't be served, the
frame falls back to the regular thumbnail, then to the type icon.

The glow colour is read from the picture already on screen — no second
download, and no cross-origin request (which the browser blocked when the UI
and API ran on different ports).

## Opening a project

Opening a persona used to run four requests one after another before the hub
appeared (project → session → last conversation → session messages), and the
first project request built a new knowledge-base client and created an empty
collection for projects without documents. Now:

| | Before | After |
|---|---|---|
| Hub visible (local, warm) | 480 ms | 85 ms |
| `GET /projects/{id}`, first after start | 228 ms | 31 ms |

- The hub opens as soon as the project is loaded; the session and messages
  load behind it, in parallel.
- The knowledge-base (Chroma) client is built once per process, warmed in the
  background at start-up, and the document count is read-only — a project
  without documents no longer gets an empty collection written for it.
- Switching back to Chat no longer re-fetches the project and its last
  conversation (which could also replace the session's messages).
- Round frames load a ~12 KB face crop instead of the full-size picture.

Code: `ui/sessions/SessionPanel.tsx` (hub content), `ui/sessions/PersonaHubDrawer.tsx`
(frame), `ui/components/ProjectAvatar.tsx`, `ui/projectIdentity.ts`,
`backend/app/personas/avatar_face.py`, `backend/app/vectordb.py`. Tests:
`src/test/conversationHub.test.tsx`, `backend/tests/test_avatar_face.py`,
`backend/tests/test_vectordb_client.py`.
