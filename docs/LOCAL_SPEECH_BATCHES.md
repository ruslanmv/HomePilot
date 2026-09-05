# HomePilot Local Speech — Batch Plan (MeetingSense transcription)

**Status:** LS1 and LS2 are **shipped**; LS3–LS8 are still planning.
The shipped batches keep their original text and carry a ✅ with what actually landed.
**Scope:** `ruslanmv/HomePilot` — `backend/app/voice/`, a new `backend/app/local_speech/`,
`backend/app/meetingsense/`, and the Settings surface in `frontend/src/ui/`.
**Rule for every batch below:** additive only. New files in new directories; existing files
receive guarded hooks and nothing else; `get_stt_provider()` keeps its current behaviour for
voice calls throughout.

---

## 0. The experience we are building toward

Written from the user's side, because every acceptance criterion below exists to protect one
of these moments.

**The normal install.** Somebody installs HomePilot, opens Settings, and sees:

```text
MEETING TRANSCRIPTION

✓ Local · Ready
Whisper Turbo · GPU accelerated

🔒 Audio stays on this computer
```

They never learn the words `WHISPER_MODEL`, `CTranslate2`, `float16`, or `STT_BASE_URL`.

**Pressing 🎙 Meeting.** Consent, share picker, red pill. No model chooser, no device
chooser, no precision chooser. The pill's expanded state says
`Transcription — Local · Whisper Turbo`, and that is the whole configuration surface a
normal user ever sees.

**The moment something is wrong.** The GPU library fails halfway through setup. HomePilot
tries another *local* profile, then local CPU, and if neither can keep up it says so —
*"Local transcription isn't fast enough on this machine"* — and offers a lighter local model.
It does **not** reach for a cloud service. A privacy boundary is never crossed as error
recovery.

---

## 1. What is actually true today

Verified against the code before planning on it, because two of the report's claims are the
foundation of the whole plan.

**`faster-whisper` is not installed by a normal install.** `backend/requirements.txt`
contains no reference to it. `WhisperLocalSTTProvider.available` requires both `WHISPER_MODEL`
set *and* `import faster_whisper` succeeding, so on a stock install it is `False` however the
environment is configured. That — not a missing model, not a hardware limitation — is why the
Settings card reads **Not configured**.

**A configured remote endpoint silently wins over local.**
`backend/app/voice/providers.py:624`:

```python
def _build_stt_provider() -> STTProvider:
    """Selection order, unchanged: a configured remote endpoint wins, then local Whisper."""
    cloud = OpenAICompatSTTProvider()
    if cloud.available:
        return cloud
    local = WhisperLocalSTTProvider()
    ...
```

Somebody who set `STT_BASE_URL` for voice calls months ago has their **meeting audio** sent
there, and nothing in the product says so. For a privacy-first meeting recorder that is the
single most important thing on this page.

**What already works and must not be rebuilt.** MeetingSense converts to 16 kHz, keeps system
audio and microphone on separate channels, runs its own VAD to cut short utterances, closes on
silence, hard-cuts long speech with overlap, caches one provider instance rather than reloading
the model per utterance, and reports the *measured* execution device rather than the requested
one. That is the right foundation. None of these batches replaces any of it.

**What is unvalidated and stays unvalidated until measured.** The design docs' ~0.2× real-time
GPU assumption has never been run on target hardware — the build environment had neither CUDA
nor `faster_whisper`. No batch below is accepted against that number.

---

## 2. The batches

Each is shippable alone. Each names the acceptance test that would catch its regression —
because a batch whose only evidence is "it worked when I tried it" is a batch that silently
stops working.

### LS1 — Make local speech real on a normal install

✅ **Shipped.** `requirements/speech-cpu.txt` and `speech-cuda12.txt`, pinned, plus a `.[whisper]` extra that a test keeps in step with the CPU set. `WHISPER_MODEL` now defaults to `small` — turbo is the design's eventual default, but making a CPU-only machine's first meeting a 1.6 GB download is a worse first experience than a model that works; that swap belongs with LS3's pinned pack and LS5's hardware profile. The CUDA set is untested here: no GPU.

Packaging, and nothing else.

* `requirements/speech-cpu.txt` and `requirements/speech-cuda12.txt` as **pinned** constraint
  sets; a `.[whisper]` extra that installs one of them.
* Nothing unpinned enters `base.txt`. CTranslate2's CUDA 12 / cuDNN 9 matrix is exactly the
  dependency that breaks an unrelated install three months later.

**Acceptance.** Fresh virtualenv + the CPU set → `/v1/meetingsense/status` reports
`available: true` with no environment variable set. Plus a test asserting the requirement file
pins a version, so a later "just bump it" cannot quietly un-pin it.

**Honest limit.** The CUDA set cannot be validated in CI without a GPU runner. Ship CPU first
and mark CUDA as untested until somebody runs it on real hardware.

---

### LS2 — The meeting gets its own policy

✅ **Shipped.** `get_meeting_stt_provider()` with `MEETINGSENSE_STT_POLICY` defaulting to `local`; `get_stt_provider()` untouched, so voice calls behave exactly as before. `/status` gained `policy`, `remote_configured` and `offer_remote`, and `remote` changed meaning from *one is configured* to *this meeting is using one*. Ten test stubs across five MeetingSense suites moved to the new function, and one status test that asserted the old behaviour was rewritten — that assertion was the bug, written down.

The privacy fix. Add:

```python
def get_meeting_stt_provider() -> STTProvider: ...
```

MeetingSense calls it. `get_stt_provider()` is untouched, so voice calls keep the behaviour
they already rely on. Order: local → explicit remote opt-in → `NullSTTProvider`. **No
automatic cloud fallback, in any branch.**

Operator setting `MEETINGSENSE_STT_POLICY=local` (the default); the UI shows it as
`● Local — Recommended / ○ Remote service`.

**The nuance the source report does not cover.** Defaulting to local silently breaks anyone
currently transcribing meetings through `STT_BASE_URL`. So: default local, and when local is
unavailable *and* a remote endpoint was already configured, say so with a one-click
**Use my configured remote service**. Nothing switches on its own; nothing is taken away.

**Acceptance.** The important test here is a privacy regression test, not a unit test:
`STT_BASE_URL` configured, policy local, run a meeting, assert **zero** requests reach that
host. Merely having a remote endpoint configured for another feature must never again decide
MeetingSense's privacy behaviour.

---

### LS3 — A model that is already on this machine

New `backend/app/local_speech/`: `manifest.py`, `models.py`, `hardware.py`, `benchmark.py`,
`provider.py`.

* A pinned manifest per pack — source model, revision, license, `sha256` per file.
* The resolver hands `faster-whisper` a **directory**, never a model name. A model name means
  a download, and a download during a meeting is a network dependency in a feature sold as
  local.
* `HomePilotLocalSTTProvider(STTProvider)` is the stable seam. MeetingSense must never learn
  whether the runtime underneath is CTranslate2, Metal, Vulkan, or something added in 2028.

**Acceptance.** Networking blocked, pack present, an 8-second WAV in → transcript **with
timestamps** out, and **zero** outbound sockets. That proves local rather than documenting it.

---

### LS4 — The install moment

Settings stops teaching environment variables.

```text
Local transcription needs to be installed.
Private transcription runs entirely on this computer after installation.

[ Install Local Transcription ]
No account or cloud speech service required.
```

→ progress → `✓ Local · Ready · Audio stays on this computer`.

The download size comes from the pack manifest, **not** a hard-coded figure: CTranslate2
conversion and quantisation change the installed footprint, so any number written into the UI
is wrong the first time the pack is rebuilt.

**Acceptance.** No environment variable name appears anywhere in the normal path.
`WHISPER_MODEL` survives only under **Advanced**, and a test walks the rendered Settings tree
to prove it.

---

### LS5 — The hardware chooses itself

`hardware.py` detects; `benchmark.py` measures once, against a shipped 15–30 s licensed
sample; the result is cached as a profile:

```json
{"engine": "faster-whisper", "model": "whisper-large-v3-turbo",
 "device": "cuda", "compute": "float16", "rtf": 0.11, "tested_at": "…"}
```

User-facing choices are only: **Auto — Recommended / Maximum accuracy / Low memory /
Advanced**. Keep the existing habit of reporting the *measured* device.

**Acceptance.** CUDA present but unusable → the profile records CPU and the UI says CPU. A
configuration that silently fell back to CPU while still displaying "GPU" is precisely the
failure this batch exists to prevent, and it is invisible without this test.

**Do not** hard-code which runtime is fastest on Intel, AMD or Apple from documentation. The
benchmark decides.

---

### LS6 — Keep up, or say so

* Warm the model when the Meeting panel opens, or when HomePilot is otherwise idle — never on
  the first spoken word, and never during application startup.
* SLO: p95 final-line latency comfortably below the "catching up" threshold the UI already
  uses. Certify hardware because it can *keep up with a meeting*, not because it can
  technically load the model.
* When local cannot keep up: offer a **lighter local model** first. Offer remote only if the
  user had already enabled it, and only as a question.
* Benchmark with `faster-whisper`'s own VAD **disabled** for the MeetingSense path first.
  MeetingSense has already decided where each utterance begins and ends; a second VAD can trim
  audio at exactly those boundaries. Keep it available for the upload-and-transcribe-later path.

**Acceptance.** A deliberately slow runtime drives the degrade path, and the test asserts no
remote call happened at any point in it.

---

### LS7 — Status worth reading

Extend `/v1/meetingsense/status` from `{available, provider}` to carry `local`, `engine`,
`model`, `device`, `compute`, `warm`, `supports_segments`, `supports_word_timestamps`, and the
stored benchmark. Recording pill gains `Transcription — Local · Whisper Turbo`. The consent
sheet says **Local** plainly.

**Acceptance.** Six failure modes are distinguishable from the status payload alone: empty
model response, decode failure, wrong device, cold load, remote in use, model not found. A
status endpoint that collapses any two of those has failed at the one job it has.

---

### LS8 — Benchmark before introducing another ASR family

The harness and corpus, recording every decoding parameter (beam size, thread counts) because
comparisons without them are not comparisons:

| Metric | Why |
|---|---|
| WER | correctness |
| p50 / p95 utterance latency | live UX |
| Real-time factor | can it keep up |
| Cold model load | first-meeting UX |
| RAM / VRAM peak | stability |
| Timestamp error | citations and transcript navigation |
| Proper names, numbers | whether the transcript is useful |
| Silence hallucination | trust |
| Noisy / overlapping speech | real meetings |
| Long-session drift | reliability |

Only then evaluate whisper.cpp, Distil-large-v3 (English only — it must never become the
silent default), Parakeet TDT 0.6B v3, Qwen3-ASR ± its separate forced aligner.

**Rule.** No default changes without data from this repository. Whisper `large-v3-turbo`
through `faster-whisper` stays the default until something beats it *here*.

---

## 3. Order, and where the value is

```text
LS1 ─► LS2 ─► LS3 ─► LS4 ─► LS5 ─► LS6 ─► LS7
                 └──────────────► LS8 (parallel from here)
```

**LS1 + LS2 together are the batch that matters.** They turn "Not configured" into a working,
private default and remove the surprising remote precedence. Everything after them is polish
on something that already works.

---

## 4. What we are deliberately not doing

* Not training or fine-tuning a model. Nothing here needs one.
* Not rewriting `get_stt_provider()`. Voice calls keep their behaviour.
* Not replacing the Python provider with whisper.cpp. It becomes a second engine behind the
  same seam, selected by benchmark, or it does not ship.
* Not adding diarization to recreate speaker information the channel split already carries.
* Not stacking a second VAD on MeetingSense's own without measuring it first.
* Not certifying any hardware profile from documentation.
