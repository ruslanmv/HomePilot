<p align="center">
  <img src="../assets/interactive-flow.svg" alt="Interactive Flow" width="860" />
</p>

<p align="center">
  <b>INTERACTIVE</b><br>
  <em>Turn one sentence into an interactive video you can play, edit, and share.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Status-Shipped-brightgreen?style=for-the-badge" alt="Shipped" />
  <img src="https://img.shields.io/badge/Modes-Standard_%7C_Persona-blue?style=for-the-badge" alt="2 Modes" />
  <img src="https://img.shields.io/badge/Media-Image_or_Video-ec4899?style=for-the-badge" alt="Image or Video" />
  <img src="https://img.shields.io/badge/Editor-Edit_%C2%B7_Preview_%C2%B7_Regenerate-purple?style=for-the-badge" alt="Editor" />
</p>

---

## What is Interactive?

**Interactive** lets anyone create a choose-your-path video. You type one sentence. HomePilot builds the story, makes the scenes, and lets your viewers click through what happens next.

Think of it like a short video with decision points — like a "choose your own adventure" book, but on screen. The AI does the heavy lifting: it writes the story, picks the scenes, and even generates the pictures or clips. You just review, tweak, and hit **Play**.

No coding. No prompts to write. No prior AI knowledge needed.

---

## Two styles of Interactive

<table>
<tr>
<td width="50%" valign="top">

### Standard project

A short video with choices. Each scene plays for a few seconds, then the viewer picks what happens next — a "What to do next?" card with image buttons.

**Great for:**
- Training and onboarding
- Lessons and tutorials
- Product tours and demos
- Quizzes and "choose your adventure" stories

Viewers get simple video controls — play/pause, skip 10s, volume, fullscreen — and pick from image cards at decision points.

</td>
<td width="50%" valign="top">

### Persona live play

A chat-plus-video experience built around one of your personas (the AI characters you create in the **Avatar** tab).

- Your persona's avatar plays in the video window.
- The viewer chats with them through an **Ask Anything** box.
- A joystick button opens quick actions the viewer can trigger as they level up.

**Great for:** companion apps, interactive roleplay, conversational demos. You'll need to create a persona first in the Avatar tab.

</td>
</tr>
</table>

---

## Pictures or Videos — your choice

Every project can use either **still images** or **short video clips** for its scenes. You pick on Step 0 of the wizard:

- **Video** — full motion clips. Looks great. Needs a bigger GPU.
- **Image** — still pictures. Much faster, works on modest hardware. Perfect for trying the whole workflow before committing to full video.

You can switch later by regenerating scenes. Pick whichever fits your computer and your use case.

---

## Getting Started

> No IT background needed. If you've used a smartphone, you can do this.

### 1. First-time setup (one minute)

Open **Settings → Providers** and make sure three things are set:

- **Chat Model** — the AI that writes your story. Default is `llama3:8b` via Ollama.
- **Image Model** — for still scenes (e.g. `dreamshaper_8.safetensors`).
- **Video Model** — for motion clips (e.g. `svd_xt_1_1.safetensors`).

If you want HomePilot to actually generate the visuals, flip on `INTERACTIVE_PLAYBACK_RENDER=true` in your environment before you start the app. If you skip this, you can still plan and write your story — you just won't see pictures until you flip it on later.

> 💡 **We're honest about this.** If scene generation is off, the wizard clearly tells you instead of showing a fake progress bar. You can always turn it on later and click **Regenerate** in the Editor.

### 2. Open the Interactive tab

Click **Interactive** in the sidebar. You'll see an empty grid — that's where your projects will live.

### 3. Click "+ New interactive"

A single box asks **"What do you want to build?"**. Type one sentence. Examples:

- *"Train new sales reps on our three pricing tiers with a quiz."*
- *"Teach a beginner how photosynthesis works."*
- *"Walk a new hire through our onboarding checklist."*
- *"Help someone practice simple Spanish greetings."*

Before you click **Generate**, pick two options:

| Option | What it means |
|---|---|
| **Interaction type** | *Standard project* for a branching video · *Persona live play* for a chat-with-video experience |
| **Render media** | *Video* for full clips · *Image* for fast still scenes |

Then hit **Generate**.

### 4. Review the draft

In a few seconds, HomePilot shows you a full draft — a title, short summary, the audience it's aimed at, how many scenes and choices, etc. Change anything you don't like. When it looks good, click **Create**.

### 5. Watch it build

A progress window shows five steps:

1. Saving your project
2. Drafting the story
3. Writing dialogue + choices
4. Making the scenes *(the slowest step)*
5. Opening the editor

During step 4, you'll see **"Now making: <scene name>"** and a progress bar like `6 / 12 scenes`.

### 6. Polish in the Editor

Each scene has three small buttons:

- ✏️ **Edit** — change the title, story text, or image description.
- ▶️ **Preview** — watch or view that one scene.
- 🔄 **Regenerate** — remake just that scene (great when one beat feels off).

At the top of the Graph tab, a **Regenerate all (N missing)** button appears whenever some scenes still need visuals.

### 7. Play

Click the **Play** button in the top-right. Your interactive video runs full-screen. Share it, embed it, publish it — up to you.

---

## The Editor tabs

| Tab | What it's for |
|---|---|
| **Graph** | See every scene, edit its text, preview it, regenerate it. You'll spend most of your time here. |
| **Catalog** | Manage the actions your viewers can take during play. |
| **Rules** | Set up personalization — how scenes adapt to each viewer. |
| **QA** | Automatic quality checks — missing pieces, broken links, policy issues. |
| **Publish** | Share your video on the web, as a file, or through an API. |
| **Analytics** | See who watched, how they chose, where they dropped off. |

---

## Common Questions

**Does it work without the internet?**
Yes. If your chat AI (like Ollama) and scene maker (ComfyUI) run locally, everything stays on your machine.

**My GPU is small. Can I still use it?**
Yes — pick **Image** mode. Each scene generates in a few seconds even on modest hardware. You still get the full branching story.

**I made a project with generation off. Do I need to start over?**
No. All your story and choices are saved. Just flip the render flag on, open the Editor, and click **Regenerate all**. Every empty scene fills in.

**Can I edit a scene's text without regenerating the visuals?**
Yes. The ✏️ **Edit** button only changes words. Use 🔄 **Regenerate** when you want new pictures.

**Can I mix images and videos in the same project?**
Not yet. Today the choice is per project. If you need both, create two projects for now — per-scene choice is on the roadmap.

**Where do the AI's writing instructions live?**
In plain, readable files under `backend/app/interactive/prompts/`. You can open them, change the wording, and see the effect on your next project — no code edits needed.

---

## Troubleshooting

| What you see | What to do |
|---|---|
| *"Skipping asset generation"* in the wizard | Set `INTERACTIVE_PLAYBACK_RENDER=true` and restart. Then click **Regenerate all** in the Editor. |
| A scene's story feels generic | Click ✏️ **Edit**, rewrite it, **Save**. No re-render needed for text tweaks. |
| A scene's image doesn't match | ✏️ **Edit** → update the **Image prompt** → **Save** → 🔄 **Regenerate**. |
| A scene shows a blank gradient in the player | No visual yet. Click 🔄 **Regenerate** on that row. |
| **Live Action** panel is empty | Open the **Catalog** tab and add at least one action. |
| *"No personas yet"* when creating a Persona project | Create one in the **Avatar** tab first, then come back. |

---

## For developers — where the code lives

<details>
<summary>Expand the code map</summary>

| What | Where |
|---|---|
| Wizard one-box entry | `frontend/src/ui/interactive/WizardAuto.tsx` |
| Draft review screen | `frontend/src/ui/interactive/WizardAutoPreview.tsx` |
| Editor shell | `frontend/src/ui/InteractiveEditor.tsx` |
| Graph panel (edit/preview/regenerate) | `frontend/src/ui/interactive/GraphPanel.tsx` |
| Standard player | `frontend/src/ui/interactive/StandardPlayer.tsx` |
| Persona player | `frontend/src/ui/InteractivePlayer.tsx` |
| Stage-1 planner (plans the story) | `backend/app/interactive/planner/autoplan_workflow.py` |
| Stage-2 graph builder (lays out scenes) | `backend/app/interactive/planner/autogen_workflow.py` |
| Scene render pipeline | `backend/app/interactive/playback/render_adapter.py` |
| Prompt library (YAML, human-readable) | `backend/app/interactive/prompts/` |
| HTTP routes | `backend/app/interactive/routes/` |

</details>

---

<p align="center">
  <sub>Part of <a href="../README.md">HomePilot</a> · see also <a href="AVATAR.md">Avatar Studio</a>, <a href="MEMORY.md">Memory</a>, <a href="PERSONAS.md">Personas</a></sub>
</p>
