"""Captioning a slide (batch MS9, wave W3 — "Eyes").

The recorder decides *when* a frame is worth keeping; this module decides *what it says*. The
split matters because the two run on opposite sides of the socket and answer different
questions. The client watches the screen thirty times a minute and almost always concludes
"nothing happened" — a decision that has to be cheap, local, and off the network. The server
sees only the handful of frames that survived, and spends a vision model on each.

**A slide is captioned once, however many times it is shown.** A presenter going back to
slide 4 produces a second keyframe — correctly, because the timeline has to show the slide was
up again — but not a second caption. The perceptual hash the client sends is what makes that
possible: an identical hash within the same meeting reuses the caption already written rather
than asking the model to describe the same picture a second time, which costs seconds of GPU
and can come back worded differently. Two strip entries for one slide whose captions disagree
read as two different slides.

**Nothing here is remembered (D4).** ``analyze_image`` is called directly rather than through
``/v1/multimodal/analyze``, and the difference is exactly the ``persist`` flag that endpoint
carries: the chat path writes its analysis into a conversation and hands it to the memory
extractor, and this path writes a caption onto one keyframe row. A meeting is retrieved from
(MS15), never extracted into long-term memory.

**Vision is optional, and its absence is silent.** An install with no multimodal model records
meetings perfectly well and shows a slide strip with timestamps and no captions. So every
failure in here — no model, a timeout, a model that answered with prose about being unable to
see — is logged and swallowed. A meeting has never been worth losing over a slide.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

from . import store

log = logging.getLogger(__name__)

#: What the model is asked. Written for a *slide*, not for a photograph: the default
#: "describe this image in detail" prompt produces "a computer screen showing a presentation
#: with blue text", which is true of every slide in the deck and therefore tells a reader
#: nothing. The title and the text on it are what makes one slide findable among sixty, which
#: is also what makes the retrieval in MS13 able to match a question against it.
SLIDE_PROMPT = (
    "This is a frame from a screen share during a meeting. In at most two sentences, say what "
    "is on it: the title or heading if there is one, and the substance — the claim of a chart, "
    "the subject of a table, the point of a diagram. Transcribe short headings exactly. "
    "Do not describe the window, the browser, the cursor or the desktop. If the screen shows "
    "no readable content, say so in three words."
)

#: Ceiling on the caption stored. A vision model asked for two sentences sometimes answers with
#: six, and the strip, the summary message and the retrieval budget all assume a caption is a
#: line rather than a paragraph.
MAX_CAPTION_CHARS = 400

#: Answers that mean "I could not see it". A model that returns one of these has not captioned
#: the slide, and storing it would put an apology in the meeting summary where a description
#: belongs — worse than an empty strip entry, because an empty one is visibly missing.
_REFUSALS = (
    "i cannot", "i can't", "i am unable", "i'm unable", "unable to", "as an ai",
    "no image", "i do not see", "i don't see", "sorry",
)


def clean_caption(text: Any) -> str:
    """The caption worth storing, or ``""``.

    Trimmed to :data:`MAX_CAPTION_CHARS` at a word boundary — a caption cut mid-word reads as
    corrupted data rather than as a long answer.
    """
    if not isinstance(text, str):
        return ""
    caption = " ".join(text.split())
    if not caption:
        return ""
    lowered = caption.lower()
    if any(lowered.startswith(mark) for mark in _REFUSALS):
        return ""
    if len(caption) <= MAX_CAPTION_CHARS:
        return caption
    cut = caption[:MAX_CAPTION_CHARS]
    space = cut.rfind(" ")
    return (cut[:space] if space > MAX_CAPTION_CHARS // 2 else cut).rstrip(" ,;:") + "…"


def upload_path() -> Optional[Path]:
    """Where ``/files/…`` URLs resolve, or ``None``.

    Imported lazily and guarded for the same reason ``retention.upload_root`` is: this module
    has to be importable — and testable — without the FastAPI app around it.
    """
    try:
        from ..files import _upload_root

        return Path(_upload_root())
    except Exception:  # noqa: BLE001
        log.debug("meetingsense: no upload root for captioning", exc_info=True)
        return None


def reuse(meeting_id: str, hash: Optional[str]) -> Optional[Dict[str, Any]]:
    """The caption already written for this picture in this meeting, if there is one."""
    try:
        return store.keyframe_by_hash(meeting_id, hash)
    except Exception:  # noqa: BLE001
        log.debug("meetingsense: hash lookup failed", exc_info=True)
        return None


async def caption(
    meeting_id: str,
    keyframe_id: str,
    *,
    url: str,
    hash: Optional[str] = None,
    t_ms: int = 0,
    model: str = "",
    analyze: Optional[Callable[..., Awaitable[Dict[str, Any]]]] = None,
) -> Optional[Dict[str, Any]]:
    """Caption one keyframe and return the ``slide`` frame to send, or ``None``.

    ``analyze`` is injected — ``async (image_url, upload_path, *, model, user_prompt, mode)``,
    which is ``multimodal.analyze_image``'s signature. Injected rather than imported at the
    call site so a test needs no vision model and no HTTP, the same reason ``transcribe`` is
    injected into the session.

    Returns ``None`` when there is nothing to say, and never raises: the caller is the meeting.
    """
    seen = reuse(meeting_id, hash)
    if seen is not None:
        text = seen.get("caption") or ""
        try:
            store.set_keyframe_caption(keyframe_id, text, seen.get("ocr_text"))
        except Exception:  # noqa: BLE001
            log.exception("meetingsense: could not copy a caption onto %s", keyframe_id)
            return None
        # `reused` is reported rather than hidden: the strip renders a re-shown slide
        # differently from a new one, and a client cannot work that out from the caption alone.
        return {"type": "slide", "id": keyframe_id, "t": int(t_ms), "url": url,
                "caption": text, "hash": hash, "reused": True}

    if analyze is None:
        return None

    try:
        result = await analyze(
            url,
            upload_path(),
            model=(model or None),
            user_prompt=SLIDE_PROMPT,
            mode="both",
        )
    except Exception:  # noqa: BLE001 — a slide is never worth the meeting
        log.exception("meetingsense: captioning failed for %s", keyframe_id)
        return None

    if not isinstance(result, dict) or not result.get("ok"):
        # An unreachable model is the normal state of an install without one. Debug, not
        # warning: at one line per keyframe it would fill a log with a fact about the config.
        log.debug("meetingsense: no caption for %s (%s)", keyframe_id,
                  (result or {}).get("error") if isinstance(result, dict) else result)
        return None

    text = clean_caption(result.get("analysis_text"))
    if not text:
        return None
    try:
        store.set_keyframe_caption(keyframe_id, text)
    except Exception:  # noqa: BLE001
        log.exception("meetingsense: could not store the caption for %s", keyframe_id)
        return None
    return {"type": "slide", "id": keyframe_id, "t": int(t_ms), "url": url,
            "caption": text, "hash": hash, "reused": False}


def vision_bridge(config: Any) -> Optional[Callable[..., Awaitable[Dict[str, Any]]]]:
    """``analyze_image``, or ``None`` when this install has no multimodal module at all.

    Resolved once per connection rather than per keyframe. Deliberately *not* gated on a
    configured model: ``analyze_image`` auto-detects an installed vision model when none is
    named, so refusing here on an empty ``vision.model`` would disable captioning on the
    common install that has moondream pulled and nothing configured. ``config`` is accepted so
    the caller does not have to learn later that this became config-dependent.
    """
    del config
    try:
        from ..multimodal import analyze_image
    except Exception:  # noqa: BLE001
        log.debug("meetingsense: multimodal unavailable", exc_info=True)
        return None
    return analyze_image
