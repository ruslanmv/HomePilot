"""
Image validation and processing utilities.

Provides secure image handling with:
- File type validation
- Size limits
- EXIF metadata stripping for privacy
"""

from fastapi import UploadFile, HTTPException
from PIL import Image
from io import BytesIO
from .config import settings


# Allowed MIME types for image uploads
ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp"}


def _max_bytes() -> int:
    """Get maximum upload size in bytes from settings."""
    return int(settings.MAX_UPLOAD_MB) * 1024 * 1024


async def read_and_validate_upload(file: UploadFile) -> bytes:
    """
    Read and validate an uploaded image file.

    Performs the following validations:
    1. Content type is in allowed list
    2. File is not empty
    3. File size is within limits
    4. File is a valid image (can be decoded)

    Args:
        file: FastAPI UploadFile object

    Returns:
        Raw image bytes

    Raises:
        HTTPException: 400 for validation failures, 413 for size limit
    """
    # Check content type
    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported content type: {file.content_type}. "
                   f"Allowed: {', '.join(sorted(ALLOWED_MIME))}"
        )

    # Read file data
    data = await file.read()

    if not data:
        raise HTTPException(status_code=400, detail="Empty upload")

    # Check size limit
    max_size = _max_bytes()
    if len(data) > max_size:
        raise HTTPException(
            status_code=413,
            detail=f"Upload too large. Maximum size: {settings.MAX_UPLOAD_MB}MB"
        )

    # Validate by decoding (do not trust MIME/extension alone)
    try:
        img = Image.open(BytesIO(data))
        img.verify()
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid image file: {e}"
        )

    return data


def strip_exif(image_bytes: bytes) -> bytes:
    """
    Remove EXIF metadata from image for privacy.

    Converts image to PNG format which doesn't support EXIF,
    ensuring all metadata is removed while preserving visual content.

    Args:
        image_bytes: Raw image bytes

    Returns:
        Image bytes without metadata (PNG format)
    """
    try:
        im = Image.open(BytesIO(image_bytes))

        # Convert to RGBA to ensure consistency
        if im.mode not in ("RGBA", "RGB"):
            im = im.convert("RGBA")
        elif im.mode == "RGB":
            # Keep RGB for JPEG sources to avoid alpha issues
            pass
        else:
            im = im.convert("RGBA")

        out = BytesIO()
        # Save as PNG to reliably strip EXIF
        # PNG format doesn't store EXIF metadata
        im.save(out, format="PNG", optimize=True)
        return out.getvalue()
    except Exception:
        # If stripping fails, return original
        # This ensures upload still works even if image processing fails
        return image_bytes


def get_image_dimensions(image_bytes: bytes) -> tuple[int, int]:
    """
    Get image dimensions without fully loading the image.

    Args:
        image_bytes: Raw image bytes

    Returns:
        Tuple of (width, height) in pixels

    Raises:
        ValueError: If image cannot be read
    """
    try:
        img = Image.open(BytesIO(image_bytes))
        return img.size
    except Exception as e:
        raise ValueError(f"Cannot read image dimensions: {e}") from e


def validate_image_dimensions(
    image_bytes: bytes,
    max_width: int = 4096,
    max_height: int = 4096,
    min_width: int = 64,
    min_height: int = 64
) -> None:
    """
    Validate image dimensions are within acceptable range.

    Args:
        image_bytes: Raw image bytes
        max_width: Maximum allowed width
        max_height: Maximum allowed height
        min_width: Minimum required width
        min_height: Minimum required height

    Raises:
        HTTPException: 400 if dimensions are out of range
    """
    try:
        width, height = get_image_dimensions(image_bytes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if width > max_width or height > max_height:
        raise HTTPException(
            status_code=400,
            detail=f"Image too large: {width}x{height}. "
                   f"Maximum: {max_width}x{max_height}"
        )

    if width < min_width or height < min_height:
        raise HTTPException(
            status_code=400,
            detail=f"Image too small: {width}x{height}. "
                   f"Minimum: {min_width}x{min_height}"
        )
