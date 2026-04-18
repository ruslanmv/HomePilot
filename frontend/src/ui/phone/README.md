# `ui/phone/` — call surface component library

Status: **partial port** of the design system from the engineering
handoff (`Phone Call UI.html`). This README tracks what ships today
and what's queued for follow-up sessions.

## What's here now

```
phone/
├── README.md            this file
├── tokens.ts            CALL palette + POST_CALL layout constants
├── icons.tsx            shared SVG icon set (mic, phone*, chat, …)
├── PostCallCard.tsx     inline chat card, expandable transcript,
│                         3 variants (expand / highlights / missed)
└── PostCallCard.test.tsx  13 tests — variant matrix + keyboard/click
```

Consumed by:

- `frontend/src/ui/App.tsx` — renders `PostCallCard` inline in the
  chat stream for every `Msg` that carries a `callMemory` payload.
  The card is **not** a modal — it sits in the conversation so the
  user can expand the transcript without a context switch.

## What's queued for follow-up sessions

The handoff defines a much larger set of components. They are
additive, so shipping them one at a time doesn't block the current
call feature — it's already functional end-to-end with the
`CallOverlay` + the inline `PostCallCard`.

| File | Status | Notes |
|---|---|---|
| `primitives/Aura.tsx` | Pending | Animated gradient avatar — seeded hue, crescent silhouette. Currently inlined in `CallOverlay.tsx::CallAvatar`. |
| `primitives/AmbientAura.tsx` | Pending | Page-wide blurred glow. Lives behind `CallOverlay`'s backdrop today. |
| `primitives/Waveform.tsx` | Pending | Live-intensity bars. `CallOverlay` already has an `rAF`-driven variant that reads real mic + synthesised speech envelope. Port will extract it. |
| `primitives/ControlBtn.tsx` | Pending | Circular glass button. Currently inlined in `CallOverlay`. |
| `CallScreen.tsx` | Pending | Fullscreen mobile composition. Desktop uses the existing `CallOverlay` modal. |
| `CallOverlay.tsx` (refactor) | Pending | Route between fullscreen / modal / PiP based on viewport. Today's `CallOverlay.tsx` is desktop-modal-only. |
| `TextInCall.tsx` | Pending | Mid-call composer sheet — minimize call to a thin bar, slide composer up, send text over the existing chat REST. |
| `HangUpTransition.tsx` | Pending | ~1 s "call ended" fade beat before the overlay dismisses. Today the overlay fades inline. |
| `MutedToast.tsx` | Pending | Brief "you're muted" confirmation pill. Today the muted state is indicated only by the waveform colour. |
| `LockScreenIncoming.tsx` | Pending | iOS-style full-bleed incoming with slide-to-answer. PWA only. |
| `PoorConnection.tsx` | Pending | Reconnecting banner when WS has been silent >3 s. Today the socket reconnects silently. |

## Suggested sequencing for the next session

Small commits, one per component file, matching the pattern from
this session:

1. `primitives/Waveform.tsx` — extract the `rAF`-driven version
   from `CallOverlay.tsx`, swap `CallOverlay`'s inline copy for
   the import.
2. `primitives/Aura.tsx` — extract `CallAvatar`, thread through
   `CallOverlay` + `PostCallCard` so the avatar identity is
   consistent across surfaces.
3. `primitives/ControlBtn.tsx` — same.
4. `CallScreen.tsx` — fullscreen mobile composition on top of the
   primitives.
5. `HangUpTransition.tsx` + `MutedToast.tsx` — small polish
   additions; each a single new render branch in `CallOverlay`.
6. `TextInCall.tsx` — biggest piece, needs its own focus session.
7. `LockScreenIncoming.tsx` — PWA-only, coordinates with service-
   worker push; scope-separate.
8. `PoorConnection.tsx` — layer on `callSocket`'s existing silence
   watchdog.

Keep each batch under ~300 LOC and write a vitest for every
component (the 13-test PostCallCard file is the template).

## Design reference

The pixel-level source of truth is `Phone Call UI.html` in the
design project — matches every state and surface. Each TSX file in
this folder maps 1:1 to a named component in the design canvas.

## Not in scope (anywhere in this folder)

- New backend endpoints
- Replacing the `voice_call` module
- Replacing `CallOverlay`'s streaming / barge-in plumbing
- Group calls / add participant
