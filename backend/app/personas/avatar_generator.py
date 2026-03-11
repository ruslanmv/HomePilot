# backend/app/personas/avatar_generator.py
"""
Synthetic avatar generator for community personas.

Downloads AI-generated faces from thispersondoesnotexist.com and
processes them into the standard HomePilot avatar format:
  - avatar_{name}.png   (512x512)
  - thumb_avatar_{name}.webp (256x256)

Usage (standalone):
    python -m backend.app.personas.avatar_generator --name marcus --out ./output

Usage (library):
    from backend.app.personas.avatar_generator import generate_avatar
    result = await generate_avatar("marcus", output_dir=Path("./assets"))
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
from PIL import Image
import io

logger = logging.getLogger(__name__)

FACE_URL = "https://thispersondoesnotexist.com/"
AVATAR_SIZE = (512, 512)
THUMB_SIZE = (256, 256)
WEBP_QUALITY = 85
MAX_RETRIES = 5
REQUEST_TIMEOUT = 20.0
USER_AGENT = "HomePilot-AvatarGenerator/1.0"


@dataclass(frozen=True)
class AvatarGenerateResult:
    """Result of generating a synthetic avatar."""
    avatar_path: Path
    thumb_path: Path
    avatar_filename: str
    thumb_filename: str
    sha256: str


async def _download_face(client: httpx.AsyncClient) -> bytes:
    """Download a single random face from thispersondoesnotexist.com."""
    resp = await client.get(
        FACE_URL,
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
    )
    resp.raise_for_status()
    ct = resp.headers.get("content-type", "")
    if "image" not in ct and len(resp.content) < 10_000:
        raise ValueError(f"Unexpected content-type: {ct}")
    return resp.content


async def download_candidates(count: int = 5) -> list[bytes]:
    """Download *count* random face images and return their raw bytes."""
    results: list[bytes] = []
    async with httpx.AsyncClient() as client:
        for i in range(count):
            for attempt in range(MAX_RETRIES):
                try:
                    data = await _download_face(client)
                    results.append(data)
                    logger.debug("Downloaded candidate %d/%d (%d bytes)", i + 1, count, len(data))
                    break
                except Exception as exc:
                    if attempt == MAX_RETRIES - 1:
                        logger.warning("Failed to download candidate %d after %d retries: %s", i + 1, MAX_RETRIES, exc)
                    else:
                        await asyncio.sleep(0.5 * (attempt + 1))
    return results


def process_avatar(
    raw_bytes: bytes,
    name: str,
    output_dir: Path,
) -> AvatarGenerateResult:
    """
    Process raw image bytes into the standard HomePilot avatar format.

    Creates:
      - avatar_{name}.png  (512x512 PNG)
      - thumb_avatar_{name}.webp (256x256 WebP)

    Returns an AvatarGenerateResult with paths and filenames.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    img_avatar = img.resize(AVATAR_SIZE, Image.LANCZOS)
    img_thumb = img_avatar.resize(THUMB_SIZE, Image.LANCZOS)

    avatar_filename = f"avatar_{name}.png"
    thumb_filename = f"thumb_avatar_{name}.webp"
    avatar_path = output_dir / avatar_filename
    thumb_path = output_dir / thumb_filename

    img_avatar.save(avatar_path, "PNG", optimize=True)
    img_thumb.save(thumb_path, "WEBP", quality=WEBP_QUALITY)

    sha = hashlib.sha256(avatar_path.read_bytes()).hexdigest()

    logger.info(
        "Generated avatar for %s: %s (%d bytes), %s (%d bytes)",
        name,
        avatar_filename, avatar_path.stat().st_size,
        thumb_filename, thumb_path.stat().st_size,
    )

    return AvatarGenerateResult(
        avatar_path=avatar_path,
        thumb_path=thumb_path,
        avatar_filename=avatar_filename,
        thumb_filename=thumb_filename,
        sha256=sha,
    )


async def generate_avatar(
    name: str,
    output_dir: Optional[Path] = None,
) -> AvatarGenerateResult:
    """
    High-level: download a synthetic face and process it into avatar files.

    Args:
        name: Short persona name (e.g. "marcus", "diana"). Used in filenames.
        output_dir: Directory to write avatar files. Defaults to cwd.

    Returns:
        AvatarGenerateResult with file paths and metadata.
    """
    if output_dir is None:
        output_dir = Path(".")

    candidates = await download_candidates(count=1)
    if not candidates:
        raise RuntimeError("Failed to download any face image")

    return process_avatar(candidates[0], name, output_dir)


# ── CLI entrypoint ──────────────────────────────────────────────────────────

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate a synthetic avatar for a HomePilot persona",
    )
    parser.add_argument("--name", required=True, help="Persona short name (e.g. marcus)")
    parser.add_argument("--out", default=".", help="Output directory (default: current dir)")
    parser.add_argument("--count", type=int, default=1, help="Number of candidates to download")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    async def _run() -> None:
        out = Path(args.out)
        if args.count > 1:
            candidates = await download_candidates(count=args.count)
            print(f"Downloaded {len(candidates)} candidates to choose from.")
            for i, data in enumerate(candidates):
                result = process_avatar(data, f"{args.name}_candidate_{i+1}", out)
                print(f"  Candidate {i+1}: {result.avatar_path}")
            print(f"\nPick the best one and rename to avatar_{args.name}.png")
        else:
            result = await generate_avatar(args.name, out)
            print(f"Avatar: {result.avatar_path} ({result.avatar_path.stat().st_size:,} bytes)")
            print(f"Thumb:  {result.thumb_path} ({result.thumb_path.stat().st_size:,} bytes)")
            print(f"SHA256: {result.sha256}")

    asyncio.run(_run())


if __name__ == "__main__":
    main()
