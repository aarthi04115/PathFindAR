"""
Frame Preprocessing for Localization Pipeline

Stages:
  1. Base64 decode → raw bytes
  2. Decode bytes → BGR numpy array (OpenCV)
  3. Blur detection via Laplacian variance
  4. Resize to max dimension whilst preserving aspect ratio
  5. Greyscale conversion for feature extraction

All heavy numpy/cv2 imports are guarded so the app still imports without
the [ml] extras installed — it just won't be able to preprocess real frames.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from typing import Optional

from loguru import logger

try:
    import cv2
    import numpy as np
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False
    logger.warning(
        "opencv-python-headless not installed — frame preprocessing unavailable. "
        "Install with: pip install 'pathfindar-backend[ml]'"
    )


# ── Result types ─────────────────────────────────────────────────────────────

@dataclass
class PreprocessResult:
    """Output of the preprocessing stage."""
    ok: bool
    error: Optional[str] = None
    # Set when ok=True
    bgr: Optional[object] = None          # np.ndarray BGR (H×W×3)
    grey: Optional[object] = None         # np.ndarray greyscale (H×W)
    blur_score: float = 0.0              # Laplacian variance; higher = sharper
    original_size: tuple[int, int] = (0, 0)  # (W, H) before resize
    resized_size: tuple[int, int] = (0, 0)   # (W, H) after resize


# ── Public API ────────────────────────────────────────────────────────────────

def preprocess(
    image_base64: str,
    max_size: int = 640,
    blur_threshold: float = 100.0,
) -> PreprocessResult:
    """
    Full preprocessing pipeline for a base64-encoded JPG/PNG frame.

    Args:
        image_base64:   Base64-encoded image from Unity client.
        max_size:       Maximum dimension (width or height) after resize.
        blur_threshold: Frames with Laplacian variance below this are rejected.

    Returns:
        PreprocessResult — check `.ok` before using `.bgr` / `.grey`.
    """
    if not _CV2_AVAILABLE:
        return PreprocessResult(ok=False, error="OpenCV not installed")

    # 1. Base64 → bytes
    raw = _decode_base64(image_base64)
    if raw is None:
        return PreprocessResult(ok=False, error="Invalid base64 encoding")

    # 2. Bytes → BGR image
    bgr = _decode_image(raw)
    if bgr is None:
        return PreprocessResult(ok=False, error="Could not decode image bytes")

    h, w = bgr.shape[:2]
    original_size = (w, h)

    # 3. Blur detection
    grey = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    blur_score = _laplacian_variance(grey)
    if blur_score < blur_threshold:
        logger.debug(f"Frame rejected — blur score {blur_score:.1f} < threshold {blur_threshold:.1f}")
        return PreprocessResult(
            ok=False,
            error=f"Frame too blurry (score={blur_score:.1f}, threshold={blur_threshold:.1f})",
            blur_score=blur_score,
            original_size=original_size,
        )

    # 4. Resize
    bgr_resized = _resize(bgr, max_size)
    grey_resized = cv2.cvtColor(bgr_resized, cv2.COLOR_BGR2GRAY)
    rh, rw = bgr_resized.shape[:2]

    logger.debug(
        f"Frame preprocessed: {w}×{h} → {rw}×{rh}, blur={blur_score:.1f}"
    )
    return PreprocessResult(
        ok=True,
        bgr=bgr_resized,
        grey=grey_resized,
        blur_score=blur_score,
        original_size=original_size,
        resized_size=(rw, rh),
    )


# ── Private helpers ───────────────────────────────────────────────────────────

def _decode_base64(b64: str) -> Optional[bytes]:
    """Decode base64 string → bytes, handling padding issues gracefully."""
    try:
        # Strip data-URI prefix if present (e.g. "data:image/jpeg;base64,...")
        if "," in b64:
            b64 = b64.split(",", 1)[1]
        # Pad to multiple of 4
        b64 += "=" * (-len(b64) % 4)
        return base64.b64decode(b64)
    except (binascii.Error, ValueError) as exc:
        logger.debug(f"Base64 decode error: {exc}")
        return None


def _decode_image(raw: bytes) -> Optional[object]:
    """Decode raw bytes → BGR numpy array using OpenCV."""
    try:
        buf = np.frombuffer(raw, dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if img is None or img.size == 0:
            return None
        return img
    except Exception as exc:
        logger.debug(f"Image decode error: {exc}")
        return None


def _laplacian_variance(grey_img: object) -> float:
    """
    Compute Laplacian variance as a sharpness/blur metric.
    Higher = sharper. Typical threshold: 50–150.
    """
    return float(cv2.Laplacian(grey_img, cv2.CV_64F).var())


def _resize(img: object, max_size: int) -> object:
    """
    Resize image so the longest dimension equals max_size.
    Maintains aspect ratio. No-op if already small enough.
    """
    h, w = img.shape[:2]
    if max(h, w) <= max_size:
        return img
    scale = max_size / max(h, w)
    new_w = int(w * scale)
    new_h = int(h * scale)
    return cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
