# HomePilot Local Speech — Batch Plan (MeetingSense transcription)

**Status:** LS1–LS8 are **shipped**. Everything measurable without a licensed corpus
and a GPU has been measured; what could not be is named as such below rather than guessed.
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

✅ **Shipped.** `backend/app/local_speech/` — `manifest.py`, `models.py`, `hardware.py`,
`provider.py`, plus `netguard.py`, which is what makes the acceptance provable.

**The resolver returns a directory or it returns nothing.** Never a model name.
`WhisperModel("small")` is a *download*: it resolves a name against Hugging Face and fetches a few
hundred megabytes, at the moment the model loads — which is the moment somebody starts a meeting.
The first time that happens on a train the feature does not degrade, it fails, in front of people,
for a reason nobody can act on. A directory cannot download anything.

**The acceptance is proved, not documented.** `netguard.no_outbound()` fails a non-loopback
`connect` **or a DNS lookup** at the moment it happens — a lookup being what a download does
first, and therefore the most informative thing to catch. An 8-second WAV goes in, three timed
spans come out in the repo's own `t0`/`t1` shape, and zero outbound sockets were opened. And
because a test asserting "no sockets" with a guard that never fires proves nothing,
`test_the_guard_would_have_caught_a_download` drives the guard with the exact call a download
makes and requires it to fail.

A pack carries its provenance, licence and per-file SHA-256. Three states are kept apart because
each has a different fix: **incomplete** (a download that stopped), **corrupt** (a digest that
does not match — never loaded), and **unverified** (a build nobody has hashed, which is usable and
must never masquerade as verified).

*Original plan:* New `backend/app/local_speech/`: `manifest.py`, `models.py`, `hardware.py`, `benchmark.py`,
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

✅ **Shipped.** `MeetingTranscriptionCard` offers an install button and two sentences; the
server's precise hint moved one disclosure down, into a closed `Advanced`.

The acceptance is a property of the **rendered tree**, not of a string somewhere, so the test
clones the card, removes every `details:not([open])`, and asserts that none of `WHISPER_MODEL`,
`WHISPER_DEVICE`, `WHISPER_COMPUTE`, `STT_BASE_URL`, `HOMEPILOT_SPEECH_DIR`,
`HOMEPILOT_SPEECH_PACK` or `MEETINGSENSE_STT` survives in what is left. Reading `textContent` off
the whole card would have counted the closed disclosure — which is exactly the mistake that would
let the names back into the headline with the test still green.

The download size comes from the pack manifest via the server. A figure typed into the interface
is wrong the first time the pack is rebuilt, because conversion and quantisation change the
footprint, so the test re-renders at 484 MB and 1.6 GB and requires both.

Three install states, not one spinner: not installed, did-not-finish, checksum-mismatch. A single
progress bar over all three would be the same shrug this series has been removing. And the hint
stays gated on `!ready` — MS32 decided that `hint` is advice rather than a fault, and this batch
does not reopen it.

*Original plan:* Settings stops teaching environment variables.

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

✅ **Shipped.** `hardware.py` detects, `benchmark.py` measures once and caches the profile beside
the packs.

**The device recorded is the device read back from the engine**, never the device asked for.
`auto` falls back to CPU silently when CUDA is present but unusable — a mismatched ctranslate2
wheel, a missing cuDNN — and the install then runs ten times slower than its budget while the
interface says GPU. That is this batch's stated acceptance and
`test_cuda_present_but_unusable_records_cpu` is it, verbatim: hardware reports CUDA, the engine
reports CPU, the profile says `cpu`, and the status payload raises `wrong_device`.

`candidates()` is a **search order, not a verdict**. Nothing here decides which runtime is fastest
on which vendor — the plan forbids it and the benchmark decides. `rtf` is measured wall-clock
seconds per second of audio; a failed run is still a profile, because "we tried and it did not
load" is a fact worth keeping and re-running it every startup teaches nobody anything.

*Original plan:* `hardware.py` detects; `benchmark.py` measures once, against a shipped 15–30 s licensed
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

✅ **Shipped.** `keepup.py`. One slow utterance is a hiccup; four in a window of eight is a
machine that cannot do this. Certification is *can it keep up with a meeting*, not *can it load* —
`KEEPS_UP_RTF` is 0.7 rather than 1.0, because transcription is not the only thing happening
during a meeting and a factor that leaves nothing spare turns every hiccup into a backlog it never
recovers from.

**A lighter local model is offered first, always** — and only one that is already installed, since
offering anything else is offering a download in the middle of a meeting, which is what LS3
removed. Remote is offered only to somebody who had already enabled it, and only as a question:
`asks` is a field, and a fallback that merely happens to somebody is not a choice. The default
answer to "your computer is slow" is never "so let us send your meeting somewhere else" — that is
the one thing the person chose this feature to avoid, and it must not be reachable by degradation.
A test drives the whole degrade path inside `no_outbound()` and asserts nothing left the machine.

`WARM_ON` and `NEVER_WARM_ON` are constants rather than comments, so the two forbidden moments —
the first spoken word, and application startup — stay visible.

*Original plan:*

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

✅ **Shipped.** `/v1/meetingsense/status` gained a nested `stt.local_speech` — additive, so every
existing field keeps its meaning and a client that has not been updated simply does not read it.

The acceptance is a property: **six failure modes distinguishable from the payload alone** —
model not found, cold load, wrong device, decode failure, empty model response, remote in use.
Each is exercised with the payload that produces it and `distinguishable()` requires every one to
be observed on its own. Two that are easy to collapse and must not be: *not installed* is a
button and *not loaded yet* is a wait, and merging them sends somebody to install what they
already have.

`classify()` is pure and computed **from** the payload rather than alongside it, so a consumer
holding only the JSON reaches the same conclusion the server did. A status field nobody can
recompute is a status field that will drift. `local` is a field rather than an inference, because
somebody who chose this feature for privacy needs that sentence to be load-bearing.

*Original plan:* Extend `/v1/meetingsense/status` from `{available, provider}` to carry `local`, `engine`,
`model`, `device`, `compute`, `warm`, `supports_segments`, `supports_word_timestamps`, and the
stored benchmark. Recording pill gains `Transcription — Local · Whisper Turbo`. The consent
sheet says **Local** plainly.

**Acceptance.** Six failure modes are distinguishable from the status payload alone: empty
model response, decode failure, wrong device, cold load, remote in use, model not found. A
status endpoint that collapses any two of those has failed at the one job it has.

---

### LS8 — Benchmark before introducing another ASR family

✅ **Shipped, and measured nothing.** `bench.py` carries the thirteen metrics, the decoding
parameters, the candidate list, and `RESULTS = ()`.

That empty tuple is the honest state and it is deliberate: this repository has no licensed speech
corpus and no GPU. A populated table nobody measured would be worse than none — it is the same
discipline that keeps the vision series' verified multi-image set empty.

What ships is the **rule**, as functions. `comparable()` refuses to rank runs measured on
different corpora, on different devices, with metrics missing, or — the one that is easy to skip —
without their decoding parameters, because the same model is two different products at beam 1 and
beam 5 and one of those two is what gets quoted. `may_replace_default()` requires a clean sweep on
every metric against a *measured* incumbent, and refuses an English-only model outright however
well it scores: the people it stops working for are exactly the people who will not be running the
benchmark.

Whisper `large-v3-turbo` through `faster-whisper` stays the default until something beats it
here.

*Original plan:* The harness and corpus, recording every decoding parameter (beam size, thread counts) because
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
