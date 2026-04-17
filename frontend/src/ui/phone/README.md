# HomePilot · Call UI design set

Static, design‑only mockups for the phone‑call feature. Everything in
this folder is intentionally **not wired** to the app — no hooks, no
event handlers, no `useVoiceController` imports. Each component takes
a `state` prop, renders one frame, and that's it.

Hand these to a designer (or load `preview.html` in a browser) to
review every visual state without touching the live app.

## Files

| File | Exports (window globals) | What it draws |
|---|---|---|
| `tokens.jsx` | `HP_CALL`, `hpCallStateColor`, `hpCallStateLabel` | Palette + state→color / state→label helpers. Single source of truth for every colour used by the other files. |
| `icons.jsx` | `HPIcon` | Line icons at 1.75 px stroke, 24‑grid: phone, phone‑end, mic, mic‑off, chat, back, minimize, speaker. |
| `controls.jsx` | `HPControlBtn` | The circular glass button used by the modal + PIP. Neutral, danger, start, or accent tones; 48 / 56 / 72 px. |
| `avatar.jsx` | `HPCallAvatar` | Persona image with a state‑coloured halo (breathes while listening / speaking / connecting). |
| `waveform.jsx` | `HPCallWaveform` | Stable‑seeded audio bars in the current state colour. |
| `call-button.jsx` | `HPCallButton`, `HPCallHeaderMock` | The emerald 📞 in the Voice page header — 5 states. `HPCallHeaderMock` shows it in context next to the existing ⚙ ✏ group. |
| `call-modal.jsx` | `HPCallModal`, `HPCallModalPresentation` | The centered overlay. Five states (connecting / listening / thinking / speaking / muted). The `Presentation` variant adds the blurred chat backdrop so designer screenshots match what the user really sees. |
| `call-pip.jsx` | `HPCallPip` | Minimized floating dock (bottom‑right of screen). Four states. |
| `first-time-tooltip.jsx` | `HPCallFirstTimeTooltip` | One‑shot emerald pill: "Talk live". Arrow points up; sits just below the header button. |
| `showcase.jsx` | `HPCallShowcase` | Figma‑style canvas that lays out every state + places the modal inside iOS / Android / macOS frames. |
| `preview.html` | — | Standalone HTML that loads React + Babel standalone + all the files above and renders the showcase into `#root`. Open it in a browser. |

## How the colours were chosen

Everything in `tokens.jsx` was picked to match HomePilot's existing
dark theme, with two additions specific to telephony:

- **Emerald (`#10b981`)** as the start‑call button. Universal "alive,
  go live" colour (FaceTime, WhatsApp, Zoom, Google Meet).
- **Red‑500 (`#ef4444`)** as the end‑call / destructive colour. Same
  universal pattern.

State‑aware halos (mapped by `hpCallStateColor`):

| State | Halo | Rationale |
|---|---|---|
| `listening` | cyan `#22d3ee` | HomePilot brand — receptive, calm |
| `thinking` | violet `#a78bfa` | Neutral processing colour (cool, not anxious) |
| `speaking` | emerald `#10b981` | "Alive, talking" — matches the start‑call button |
| `muted` | neutral text‑3 | Explicit "off" tone, no colour |
| `error` | red‑400 `#f87171` | Destructive/attention‑needed |
| `connecting` | cyan | "Brand is spinning up" |

Why four colours instead of one brand cyan: in a voice surface, colour
is the only channel that tells the user whether to talk, wait, or
listen. A single colour with different motion fails WCAG
colour‑and‑motion redundancy and makes the UI feel laggy when the
actual state is moving.

## Loading the preview

```bash
cd frontend/src/ui/phone
python3 -m http.server 7000      # or any static server
# open http://localhost:7000/preview.html
```

Or just double‑click `preview.html` — Babel‑standalone compiles the
JSX in the browser so no build step is needed.

## What's explicitly out of scope here

- No React hooks. No `useState`, no `useEffect` in any component.
- No integration with `useVoiceController`, the TTS registry, or the
  chat / Voice page header. Those are separate commits (see the
  voice fix in `e64d0b5` and the TTS plugin registry in `8c83a2e`).
- No haptic / keyboard wiring for hold‑to‑call — that goes in the
  real `useHoldToCall` hook when the designer signs off.
- No tokens compiled into `tailwind.config`. Designers pick visuals
  here; port to Tailwind tokens in the implementation commit.

## Next step after designer sign‑off

Turn each `.jsx` mockup into a real `.tsx` component by:

1. Convert `Object.assign(window, {...})` → named exports.
2. Drop the inline styles for Tailwind class strings (the colour
   values in `tokens.jsx` already match the Tailwind palette).
3. Replace fixed `state` / `durationSec` props with real data from
   `useVoiceController`.
4. Wire the button's `onClick` (header) and `onPointerDown` (chat
   mic, for hold‑to‑call) to open / close the modal.

The visual surface is already complete — the implementation commit
will be 90 % plumbing.
