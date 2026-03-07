"""
Hybrid prompt builder — converts wizard selections into robust ComfyUI prompts.

Additive module.  Produces a (positive_prompt, negative_prompt) tuple
from the wizard's appearance fields for full-body/outfit generation.

The positive prompt emphasises outfit and scene over face details, since
the face is already locked via the identity adapter (InstantID/PhotoMaker).

Does not modify any existing prompt builder.
"""

from __future__ import annotations

from typing import Optional, Tuple


def build_fullbody_prompt(
    outfit_style: Optional[str] = None,
    profession: Optional[str] = None,
    body_type: Optional[str] = None,
    posture: Optional[str] = None,
    gender: Optional[str] = None,
    age_range: Optional[str] = None,
    background: Optional[str] = None,
    lighting: Optional[str] = None,
    prompt_extra: Optional[str] = None,
) -> Tuple[str, str]:
    """Build positive + negative prompts for identity-preserving full-body generation.

    Returns
    -------
    tuple[str, str]
        (positive_prompt, negative_prompt)
    """
    parts: list[str] = []

    # Framing — always full body, strong composition cues to prevent face-only output
    parts.append("full body photograph from head to toe, entire body visible, showing feet")

    # Subject
    if gender:
        gender_word = {"female": "woman", "male": "man", "neutral": "person"}.get(
            gender.lower(), gender
        )
    else:
        gender_word = "person"

    if age_range:
        age_word = {
            "young_adult": "young adult",
            "adult": "adult",
            "mature": "mature",
        }.get(age_range.lower(), age_range)
        parts.append(f"{age_word} {gender_word}")
    else:
        parts.append(gender_word)

    # Body
    if body_type:
        parts.append(f"{body_type} build")
    if posture:
        parts.append(f"{posture} posture")

    # Outfit — high priority, placed early for maximum influence
    if outfit_style:
        parts.append(f"wearing {outfit_style}")
    if profession:
        parts.append(f"{profession}")

    # Scene
    if background:
        bg_map = {
            "office": "professional office interior background",
            "studio": "clean studio background, neutral tones",
            "outdoors": "outdoor natural setting background",
            "urban": "modern urban cityscape background",
        }
        parts.append(bg_map.get(background.lower(), f"{background} background"))

    if lighting:
        light_map = {
            "soft": "soft diffused lighting",
            "dramatic": "dramatic cinematic lighting",
            "natural": "natural daylight",
            "studio": "professional studio lighting",
        }
        parts.append(light_map.get(lighting.lower(), f"{lighting} lighting"))
    else:
        parts.append("professional studio lighting")

    # Quality + composition reinforcement
    parts.append("full length shot, wide angle, high quality, sharp focus, highly detailed, 8k resolution")

    # User additions
    if prompt_extra:
        parts.append(prompt_extra.strip())

    positive = ", ".join(p.strip() for p in parts if p and p.strip())

    # Negative prompt — prevents face-only output + reduces common artifacts
    negative = ", ".join([
        "close-up",
        "headshot",
        "portrait crop",
        "face only",
        "cropped body",
        "cut off legs",
        "cut off feet",
        "lowres",
        "blurry",
        "bad anatomy",
        "deformed",
        "extra fingers",
        "missing fingers",
        "bad hands",
        "bad feet",
        "disfigured face",
        "mismatched identity",
        "distorted eyes",
        "duplicate",
        "watermark",
        "text",
        "logo",
        "signature",
    ])

    return positive, negative
