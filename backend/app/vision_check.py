"""Can this model actually see? A ten-second check before it is trusted with images.

Model names and capability flags are not evidence. On one real OllaBridge gateway Open WebUI
marked a text-only model ``vision: true`` and left two genuine vision models unflagged — and a
model that is sent an image through a route that drops it will still answer, confidently, about
a picture it never received. So a model is checked the only reliable way: show it a picture
whose content is known and see whether it says what is in it.

The test image is two flat colours, yellow on the left and blue on the right, built here with
the standard library so the check needs nothing installed. Two colours in a stated order make a
lucky guess unlikely: a model that cannot see tends to say "no image", or names one colour, and
fails. The image goes through :func:`multimodal.analyze_image` — the same provider dispatch,
adapter and request format every real image takes — so passing the check means real uploads
work, not merely that the model can see in principle.
"""

from __future__ import annotations

import base64
import re
import struct
import zlib
from pathlib import Path
from typing import Any, Dict, Optional

#: The colours in the test image, left to right, and the words that count as naming them.
LEFT, RIGHT = "yellow", "blue"
_LEFT_WORDS = ("yellow", "amarillo", "giallo", "jaune", "gelb", "amarelo")
_RIGHT_WORDS = ("blue", "azul", "blu", "bleu", "blau")

PROMPT = (
    "Look at the image. It is split into a left half and a right half, each one flat colour. "
    "Name the two colours, left first, in this form: LEFT=<colour>, RIGHT=<colour>. "
    "If you cannot see an image, answer exactly: NO IMAGE."
)


def test_image_png(width: int = 128, height: int = 64) -> bytes:
    """A PNG: left half yellow (255,220,0), right half blue (0,90,255). No dependencies."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    half = width // 2
    row = b"\x00" + b"\xff\xdc\x00" * half + b"\x00\x5a\xff" * (width - half)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(row * height))
            + chunk(b"IEND", b""))


def judge(answer: str) -> bool:
    """Whether an answer names yellow first and blue second (in any of a few languages)."""
    text = (answer or "").lower()
    if not text or "no image" in text:
        return False
    left = _first(text, _LEFT_WORDS)
    right = _first(text, _RIGHT_WORDS)
    return left is not None and right is not None and left < right


def _first(text: str, words) -> Optional[int]:
    hits = [m.start() for w in words for m in re.finditer(rf"\b{re.escape(w)}\b", text)]
    return min(hits) if hits else None


async def check(
    *,
    provider: str,
    base_url: Optional[str],
    model: Optional[str],
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the check. ``sees_images`` is the verdict; ``answer`` is what the model said."""
    from .multimodal import analyze_image

    result = await analyze_image(
        "",
        Path("."),
        provider=provider or "ollama",
        base_url=base_url,
        model=model,
        user_prompt=PROMPT,
        mode="caption",
        purpose="photo",
        image_b64=base64.b64encode(test_image_png()).decode(),
        api_key=api_key,
    )
    answer = str(result.get("analysis_text") or "").strip()
    if not result.get("ok"):
        return {
            "ok": True,
            "sees_images": False,
            "answer": answer,
            "reason": result.get("error") or "The model did not answer.",
            "error_code": result.get("error_code") or "",
            "model": model,
        }
    sees = judge(answer)
    return {
        "ok": True,
        "sees_images": sees,
        "answer": answer[:400],
        "reason": "" if sees else (
            "The model answered without describing the test image — it cannot see images "
            "through this connection."
        ),
        "error_code": "",
        "model": model,
    }
