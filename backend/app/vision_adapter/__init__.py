"""One place every image passes through on its way to a vision model (batch V4).

**This batch changes no behaviour.** It is the seam, with a single ``passthrough`` profile
that returns exactly what it was given. Profiles that resize, crop and tile arrive in V5; the
point of landing the seam first is that V5 then changes one file instead of four call sites.

## Why a seam at all

Every vision request in HomePilot loads bytes and base64-encodes them, and each caller does it
slightly differently. `_load_image_bytes` covers local files and remote URLs; the `image_b64`
path skips both, which is how `meta.image_size_bytes` came to report 0 for every avatar and
remote-screenshot analysis — the fix had to be made twice because there was no one place.

## What it does today

Reports. `adapt()` returns the bytes unchanged and a record of what it saw: real dimensions,
real byte count, and the strategy it chose. That is already worth having — until now nothing
could distinguish "the model returned nothing" from "the image was 40 megapixels" from "the
resize destroyed the text", and V4's `meta.adapter` block is what makes those three different
answers instead of one shrug.

## What it refuses

Nothing yet, except what is not an image at all. A decompression bomb and an ultrawide
screenshot are recorded and passed through, because a seam that starts rejecting images on the
day it lands is not a seam, it is V5 arriving early and unannounced.
"""

from .adapter import AdaptedImage, adapt, describe  # noqa: F401

__all__ = ["AdaptedImage", "adapt", "describe"]
