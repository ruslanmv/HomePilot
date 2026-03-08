"""
Post-generation orientation guard for left/right view-pack images.

Additive module — safe to remove without breaking any existing code.

After generating a "left" or "right" view, this module inspects the image
to estimate which direction the face is pointing.  If the detected direction
does not match the requested side, the image is mirrored horizontally.

Convention:
  "left"  = the person is looking toward the left side of the image
  "right" = the person is looking toward the right side of the image

Dependencies (all optional — gracefully degrades):
  - insightface  (preferred: pose estimation via buffalo_l)
  - opencv-python (cv2) — used by insightface internally
  - Pillow (always available)

When insightface is not installed the helper returns "unknown" and skips
the fix, so nothing breaks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional, Union

import numpy as np
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

try:
    from insightface.app import FaceAnalysis  # type: ignore
except Exception:  # pragma: no cover
    FaceAnalysis = None

Direction = Literal["left", "right"]
FixMode = Literal["copy", "overwrite"]


@dataclass
class OrientationDetection:
    detected: Optional[Direction]
    confidence: float
    method: str
    face_count: int
    details: dict = field(default_factory=dict)


@dataclass
class OrientationFixResult:
    requested: Direction
    detected: Optional[Direction]
    changed: bool
    output_path: str
    confidence: float
    method: str
    reason: str


# ---------------------------------------------------------------------------
# Lazy InsightFace loader
# ---------------------------------------------------------------------------

_FACE_ANALYZER = None


def _get_face_analyzer():
    global _FACE_ANALYZER
    if _FACE_ANALYZER is not None:
        return _FACE_ANALYZER

    if FaceAnalysis is None:
        return None

    try:
        app = FaceAnalysis(
            name="buffalo_l",
            providers=["CPUExecutionProvider"],
        )
        app.prepare(ctx_id=0, det_size=(640, 640))
        _FACE_ANALYZER = app
        return _FACE_ANALYZER
    except Exception:
        logger.debug("InsightFace initialization failed", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Image utils
# ---------------------------------------------------------------------------

def _load_rgb(path: Union[str, Path]) -> np.ndarray:
    img = Image.open(path).convert("RGB")
    return np.asarray(img)


def _save_mirrored(
    src_path: Union[str, Path],
    dst_path: Union[str, Path],
) -> None:
    with Image.open(src_path) as img:
        mirrored = ImageOps.mirror(img)
        mirrored.save(dst_path)


# ---------------------------------------------------------------------------
# Detection logic
# ---------------------------------------------------------------------------

def detect_left_right_orientation(
    image_path: Union[str, Path],
    min_face_score: float = 0.45,
) -> OrientationDetection:
    """
    Detect whether the person is looking toward image-left or image-right.

    Strategy:
    1. Prefer InsightFace pose yaw if available.
    2. Fallback to nose-tip offset relative to face bbox center.
    3. If no usable face is found, return detected=None.
    """
    rgb = _load_rgb(image_path)
    analyzer = _get_face_analyzer()

    if analyzer is None:
        return OrientationDetection(
            detected=None,
            confidence=0.0,
            method="unavailable",
            face_count=0,
            details={"reason": "insightface_not_available"},
        )

    try:
        faces = analyzer.get(rgb)
    except Exception as exc:
        return OrientationDetection(
            detected=None,
            confidence=0.0,
            method="error",
            face_count=0,
            details={"reason": "analyzer_failed", "error": str(exc)},
        )

    if not faces:
        return OrientationDetection(
            detected=None,
            confidence=0.0,
            method="no_face",
            face_count=0,
            details={"reason": "no_face_detected"},
        )

    # Pick the largest confident face
    def _face_area(face) -> float:
        bbox = getattr(face, "bbox", None)
        if bbox is None:
            bbox = face.get("bbox")
        x1, y1, x2, y2 = bbox
        return max(0.0, (x2 - x1) * (y2 - y1))

    best = sorted(faces, key=_face_area, reverse=True)[0]
    score = float(getattr(best, "det_score", best.get("det_score", 0.0)))
    if score < min_face_score:
        return OrientationDetection(
            detected=None,
            confidence=score,
            method="low_face_score",
            face_count=len(faces),
            details={"det_score": score},
        )

    bbox = getattr(best, "bbox", None)
    if bbox is None:
        bbox = best.get("bbox")
    x1, y1, x2, y2 = [float(v) for v in bbox]
    face_center_x = (x1 + x2) / 2.0

    # ---------------------------------------------------------
    # Nose offset detection (landmark-based)
    # ---------------------------------------------------------
    kps = getattr(best, "kps", None)
    if kps is None and hasattr(best, "get"):
        kps = best.get("kps")

    nose_offset_direction: Optional[Direction] = None
    nose_offset_strength = 0.0
    if kps is not None and len(kps) >= 3:
        # InsightFace 5-point landmarks: left_eye, right_eye, nose, mouth_left, mouth_right
        nose_x = float(kps[2][0])
        face_width = max(1.0, x2 - x1)
        offset = (nose_x - face_center_x) / face_width

        if abs(offset) >= 0.03:
            nose_offset_direction = "left" if offset < 0 else "right"
            nose_offset_strength = min(1.0, abs(offset) / 0.18)

    # ---------------------------------------------------------
    # Method A: explicit pose/yaw from InsightFace
    # ---------------------------------------------------------
    pose = getattr(best, "pose", None)
    if pose is None and hasattr(best, "get"):
        pose = best.get("pose")

    if pose is not None and len(pose) >= 2:
        yaw = float(pose[1])

        # Cross-validate yaw sign with nose offset when available
        if nose_offset_direction is not None and abs(yaw) >= 3.0:
            pose_direction: Direction = "left" if yaw < 0 else "right"
            if pose_direction != nose_offset_direction:
                pose_direction = "right" if pose_direction == "left" else "left"
        else:
            pose_direction = "left" if yaw < 0 else "right"

        confidence = min(1.0, max(abs(yaw) / 25.0, nose_offset_strength))
        return OrientationDetection(
            detected=pose_direction,
            confidence=confidence,
            method="insightface_pose",
            face_count=len(faces),
            details={
                "yaw": yaw,
                "det_score": score,
                "nose_offset_direction": nose_offset_direction,
                "nose_offset_strength": nose_offset_strength,
            },
        )

    # ---------------------------------------------------------
    # Method B: nose-tip offset fallback
    # ---------------------------------------------------------
    if nose_offset_direction is not None:
        return OrientationDetection(
            detected=nose_offset_direction,
            confidence=max(0.35, nose_offset_strength),
            method="nose_offset",
            face_count=len(faces),
            details={
                "det_score": score,
                "nose_offset_strength": nose_offset_strength,
            },
        )

    return OrientationDetection(
        detected=None,
        confidence=0.0,
        method="unknown",
        face_count=len(faces),
        details={"reason": "pose_and_landmarks_not_usable", "det_score": score},
    )


# ---------------------------------------------------------------------------
# Fix logic
# ---------------------------------------------------------------------------

def fix_image_orientation(
    image_path: Union[str, Path],
    requested: Direction,
    output_path: Optional[Union[str, Path]] = None,
    mode: FixMode = "copy",
    min_confidence: float = 0.35,
) -> OrientationFixResult:
    """
    Detect left/right orientation and mirror the image if it does not match.

    mode="copy"      keeps original file, writes to output_path
    mode="overwrite"  replaces original file in-place
    """
    src = Path(image_path)

    if mode == "overwrite":
        dst = src
    else:
        if output_path is None:
            dst = src.with_name(f"{src.stem}_fixed{src.suffix}")
        else:
            dst = Path(output_path)

    detection = detect_left_right_orientation(src)

    if detection.detected is None:
        if mode == "copy" and src != dst:
            Image.open(src).save(dst)
        return OrientationFixResult(
            requested=requested,
            detected=None,
            changed=False,
            output_path=str(dst),
            confidence=detection.confidence,
            method=detection.method,
            reason="orientation_unknown_no_flip_applied",
        )

    if detection.confidence < min_confidence:
        if mode == "copy" and src != dst:
            Image.open(src).save(dst)
        return OrientationFixResult(
            requested=requested,
            detected=detection.detected,
            changed=False,
            output_path=str(dst),
            confidence=detection.confidence,
            method=detection.method,
            reason="low_confidence_no_flip_applied",
        )

    should_flip = detection.detected != requested

    if should_flip:
        _save_mirrored(src, dst)
        logger.info(
            "Orientation fix: detected=%s requested=%s → mirrored (confidence=%.2f)",
            detection.detected, requested, detection.confidence,
        )
        return OrientationFixResult(
            requested=requested,
            detected=detection.detected,
            changed=True,
            output_path=str(dst),
            confidence=detection.confidence,
            method=detection.method,
            reason=f"detected_{detection.detected}_but_requested_{requested}_image_mirrored",
        )

    if mode == "copy" and src != dst:
        Image.open(src).save(dst)

    return OrientationFixResult(
        requested=requested,
        detected=detection.detected,
        changed=False,
        output_path=str(dst),
        confidence=detection.confidence,
        method=detection.method,
        reason="orientation_already_correct",
    )
