"""One place every image passes through on its way to a vision model (batches V4, V5).

## Why a seam at all

Every vision request in HomePilot loads bytes and base64-encodes them, and each caller used to
do it slightly differently. `_load_image_bytes` covers local files and remote URLs; the
`image_b64` path skipped both, which is how `meta.image_size_bytes` came to report 0 for every
avatar and remote-screenshot analysis — the fix had to be made twice because there was no one
place. V4 made this that place and deliberately had it change nothing.

## What it does now (V5)

**Fits the image to a budget.** Aspect preserved, never enlarged, re-encoded as PNG. A 3840×2160
screenshot is not "too big for the model" in the sense the old error message implied — it is an
image whose text has already been destroyed by the time the model's own vision encoder has
finished downsampling it. Sending a considered 1400px view instead of eight megapixels is the
difference between a model that reads the screen and one that guesses at it.

**Tiles it, when the model can take it.** Overlapping crops of the *original*, so the text
survives at close to native resolution, each labelled (`top-left`, `center`, …) so the answer
can refer to where on the screen something is.

## What is gated, and why it is off

Tiling asks the model to reason across several images, and a model that cannot do that answers
about the last tile it saw as though it were the whole screen — confidently, and wrongly. So it
is gated on `profiles.supports_multiple_images`, whose verified set is **empty**: nothing in
this repository has yet measured a model doing it, and a list of families that ought to work is
not a measurement. V8's bench set is the batch that fills it. An operator who has checked their
own model can name it in `VISION_MULTI_IMAGE_MODELS` and have tiles today.

## What it refuses

Nothing. Without Pillow, on a format it cannot open, on zero bytes, or when a resize fails, it
degrades to V4 — the original bytes, and a warning saying so. A vision request that started
failing over an optional measurement would be a worse product than one that answers from the
image it was given.
"""

from .adapter import AdaptedImage, Part, adapt, describe  # noqa: F401
from .profiles import (  # noqa: F401
    PHOTO,
    SCREEN_OVERVIEW,
    SCREEN_TEXT,
    Profile,
    profile_for,
    supports_multiple_images,
)

__all__ = [
    "AdaptedImage",
    "Part",
    "Profile",
    "PHOTO",
    "SCREEN_OVERVIEW",
    "SCREEN_TEXT",
    "adapt",
    "describe",
    "profile_for",
    "supports_multiple_images",
]
