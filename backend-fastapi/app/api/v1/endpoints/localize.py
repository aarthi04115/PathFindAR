"""
POST /v1/localize

Accepts a camera frame (base64 JPG) + ARCore pose + timestamp.
Returns corrected pose (position, rotation) + confidence score.

This is what the Unity client calls every 1–2 seconds to fix drift.
"""

import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from loguru import logger

from app.core import state

router = APIRouter()


# ── Request / Response schemas ───────────────────────────────────────────────

class ARCorePose(BaseModel):
    """Pose from ARCore (Unity left-handed coordinate system)."""
    position: list[float] = Field(..., min_length=3, max_length=3, description="[x, y, z]")
    rotation: list[float] = Field(..., min_length=4, max_length=4, description="[x, y, z, w] quaternion")


class LocalizeRequest(BaseModel):
    """Payload from Unity client."""
    image_base64: str = Field(..., description="Camera frame as base64-encoded JPG")
    arcore_pose: ARCorePose = Field(..., description="Current ARCore-estimated pose")
    timestamp: float = Field(..., description="Unix timestamp (seconds)")
    floor: Optional[int] = Field(0, description="Current floor index")


class CorrectedPose(BaseModel):
    """Backend-corrected pose in Unity world coordinates."""
    position: list[float] = Field(..., description="[x, y, z] corrected position")
    rotation: list[float] = Field(..., description="[x, y, z, w] corrected quaternion")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Pose confidence (0=passthrough, 1=fully corrected)")
    nearest_node_id: Optional[str] = Field(None, description="Closest navigation graph node")
    blur_score: Optional[float] = Field(None, description="Frame sharpness score (debug)")


class LocalizeResponse(BaseModel):
    """Response sent back to Unity."""
    success: bool
    pose: Optional[CorrectedPose] = None
    message: str = ""
    latency_ms: float = 0.0


# ── Endpoint ─────────────────────────────────────────────────────────────────

@router.post("", response_model=LocalizeResponse)
async def localize(request: LocalizeRequest):
    """
    Process a camera frame and return corrected indoor position.

    Pipeline: Frame → Blur Check → SuperPoint → NetVLAD Retrieval → SuperGlue → PnP → Map Snap
    Returns the ARCore pose unchanged (confidence=0) when the pipeline cannot improve it.
    """
    t0 = time.perf_counter()
    logger.info(
        f"Localize request — ts={request.timestamp:.3f}, floor={request.floor}"
    )

    if not state.localization.is_loaded:
        raise HTTPException(status_code=503, detail="Localization pipeline not ready")

    try:
        result = state.localization.localize(
            image_base64=request.image_base64,
            arcore_pose={
                "position": request.arcore_pose.position,
                "rotation": request.arcore_pose.rotation,
            },
        )
    except Exception as exc:
        logger.exception(f"Localization pipeline error: {exc}")
        raise HTTPException(status_code=500, detail="Internal localization error")

    latency_ms = (time.perf_counter() - t0) * 1000
    confidence = result.get("confidence", 0.0)

    return LocalizeResponse(
        success=True,
        pose=CorrectedPose(
            position=result["position"],
            rotation=result["rotation"],
            confidence=confidence,
            nearest_node_id=result.get("nearest_node_id"),
            blur_score=result.get("blur_score"),
        ),
        message=(
            "Corrected pose" if confidence > 0
            else "Passthrough — ARCore pose returned unchanged"
        ),
        latency_ms=round(latency_ms, 2),
    )
