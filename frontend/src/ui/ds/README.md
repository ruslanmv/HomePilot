# HomePilot design system

One visual language for every page. The Meetings pages set it; Routines is the first page
rebuilt on these pieces; the rest move over one at a time (list below). Pages compose these
components instead of styling buttons, cards and badges by hand.

## Tokens

CSS variables in `src/ui/styles.css` (`:root`), exposed to Tailwind in `tailwind.config.js`:

| Token | Tailwind | Value | Use |
|---|---|---|---|
| `--hp-accent` | `bg-hp-accent`, `text-hp-accent`, `/15`… | violet-600 | primary buttons, active states, switches |
| `--hp-accent-hover` | `bg-hp-accent-hover` | violet-500 | primary hover |
| `--hp-accent-fg` | `text-hp-accent-fg` | violet-300 | icons, links and targets on dark |
| `--hp-canvas` | `bg-hp-canvas` | black | page background |
| `--hp-surface` | `bg-hp-surface` | #121218 | menus, popovers |
| radius | `rounded-card` | 1rem | cards, notices, empty states |

Surfaces are white at low opacity on the canvas (`bg-white/[0.02]`, borders `white/10`), so
cards read as one family on any page. Text: white for titles, `white/55` for descriptions and
meta, `white/45` for labels. Status colours come only from `TONE_CLASSES` (green, amber, red,
slate, violet, …). There is one violet — not `#9b5cff`, `purple-500` and `violet-600` side by
side.

## Components (`import { … } from '../ds'`)

| Component | What it is |
|---|---|
| `Page` | scrolling page: canvas, max width 72rem (`narrow` 48rem), shared gutters |
| `PageHeader` | eyebrow (icon + context), `h1`, secondary description, actions on the right |
| `Button` | `primary` (one per view) · `secondary` · `ghost` (row actions) · `danger`; sizes `sm` 32px, `md` 40px, `lg` 44px; `icon`, `loading` |
| `IconButton` | icon-only; `label` is required (it is the accessible name) |
| `Card` | content card, optional title row (icon · title · action) |
| `StatTile` | icon tile + label + value + caption, for the numbers on top of a page |
| `IconTile` | the violet-tinted square behind icons |
| `StatusBadge` | `tone` + label, `busy` adds a pulsing dot — Active, Paused, Failed… |
| `Switch` | the one `role="switch"` toggle, violet when on |
| `InlineAlert` | `info` · `success` · `warning` · `danger`; title + one or two lines + optional action |
| `EmptyState` | soft violet glow, icon (or `art`), title, one helpful line, the primary action |
| `SkeletonRows` | loading placeholders in the shape of the content (`aria-busy`) |
| `SheetHeader` / `SheetFooter` | dialog header/footer for `components/ModalSheet` (focus trap, Escape, Back) |
| `FIELD`, `FIELD_LABEL` | class strings for inputs and their small uppercase labels |

Every state a page has uses the same pieces: loading → `SkeletonRows`, empty → `EmptyState`,
error → `InlineAlert tone="danger"` with a retry, populated → `Card`s with `StatusBadge`s.

## Rules

- One primary button per view; everything else is secondary or ghost.
- Status is honest: a badge says what is true on this server (Routines shows "Manual only"
  when scheduled runs are off, never "Active").
- Destructive actions ask first (inline confirm or a dialog), and dialogs are `ModalSheet`s.
- Focus is always visible (`ring-hp-accent-fg`); touch targets are at least 40px.
- No new UI library; gradients only where the Meetings pages already use them (insight cards).

## Moving the other pages over

In order of how far they are from this today:

1. **Settings** — `SettingsCard`/`StatusPill`/two switch styles and `#9b5cff` → `Card`, `StatusBadge`, `Switch`, `hp-accent`.
2. **Models** — blue/emerald/white primaries → `Button variant="primary"`; `hp-page-header` → `PageHeader`.
3. **Projects** — `rounded-full purple-500` buttons and hand-rolled `#1a1a2e` modals → `Button`, `ModalSheet` + `SheetHeader`.
4. **Teams**, **Community**, **MCP / Tools** — cyan/blue identities → accent tokens, `StatusBadge`, `EmptyState`.
5. **Creator / Interactive** (`interactive/ui.tsx`, YouTube-style `#3ea6ff`) — re-skin its kit on these tokens.
6. The ~13 copies of a switch (`SettingsPanel`, `MeetingsSettings`, `AudioVideoSettings`, `ChatSettingsPopover`…) → `Switch`.

Meetings already matches; its badge colours now come from here (`library/format.ts` re-exports
`TONE_CLASSES`).
