"""
POST /v1/ingest/*

Reference frame ingestion endpoints:
  - POST /v1/ingest/frame   — Upload a single reference image with known pose
  - GET  /v1/ingest/stats   — Ingestion database statistics
  - GET  /v1/ingest/frames  — List ingested frames (paginated)
  - DELETE /v1/ingest/frame/{id} — Remove a reference frame
"""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from loguru import logger

from app.core import state

router = APIRouter()


# ── Request / Response schemas ───────────────────────────────────────────────

class IngestFrameRequest(BaseModel):
    """Upload a reference image with its known 6-DoF pose."""
    image_base64: str = Field(..., description="Base64-encoded JPG/PNG image")
    position: list[float] = Field(
        ..., min_length=3, max_length=3,
        description="[x, y, z] world coordinates"
    )
    rotation: list[float] = Field(
        default=[0.0, 0.0, 0.0, 1.0], min_length=4, max_length=4,
        description="[x, y, z, w] quaternion rotation"
    )
    floor: int = Field(default=0, description="Floor index")
    filename: Optional[str] = Field(
        default=None,
        description="Optional filename (auto-generated from content hash if omitted)"
    )


class IngestFrameResponse(BaseModel):
    success: bool
    frame_id: int
    filename: str
    floor: int
    position: list[float]
    message: str


class FrameInfo(BaseModel):
    id: int
    filename: str
    floor: int
    position: list[float]
    rotation: list[float]
    feature_path: str


class IngestStatsResponse(BaseModel):
    total_frames: int
    image_dir: str
    feature_dir: str
    images_on_disk: int


class FrameListResponse(BaseModel):
    success: bool
    frames: list[FrameInfo]
    total: int
    floor_filter: Optional[int] = None


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/frame", response_model=IngestFrameResponse)
async def ingest_frame(req: IngestFrameRequest):
    """
    Upload a single reference image with its known pose.

    Used during a "mapping walk" — the operator walks through the building
    with the app in mapping mode, capturing images at known locations.
    The server saves the image, pre-computes ML features, and adds it
    to the reference database.
    """
    if not state.ingestion_engine:
        raise HTTPException(
            status_code=503,
            detail="Ingestion engine not initialized"
        )

    try:
        frame = state.ingestion_engine.ingest_base64(
            image_base64=req.image_base64,
            position=req.position,
            rotation=req.rotation,
            floor=req.floor,
            filename=req.filename,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error(f"Ingestion failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {exc}")

    return IngestFrameResponse(
        success=True,
        frame_id=frame.id,
        filename=frame.filename,
        floor=frame.floor,
        position=frame.position,
        message=f"Frame ingested successfully (#{frame.id})",
    )


@router.get("/stats", response_model=IngestStatsResponse)
async def get_ingestion_stats():
    """How many reference frames have been ingested."""
    if not state.ingestion_engine:
        raise HTTPException(status_code=503, detail="Ingestion engine not initialized")
    return state.ingestion_engine.stats


@router.get("/frames", response_model=FrameListResponse)
async def list_frames(
    floor: Optional[int] = None,
):
    """List all ingested reference frames, optionally filtered by floor."""
    if not state.ingestion_engine:
        raise HTTPException(status_code=503, detail="Ingestion engine not initialized")

    frames = state.ingestion_engine.store.get_all(floor=floor)
    return FrameListResponse(
        success=True,
        frames=[
            FrameInfo(
                id=f.id,
                filename=f.filename,
                floor=f.floor,
                position=f.position,
                rotation=f.rotation,
                feature_path=f.feature_path,
            )
            for f in frames
        ],
        total=len(frames),
        floor_filter=floor,
    )


@router.delete("/frame/{frame_id}")
async def delete_frame(frame_id: int):
    """Remove a reference frame by ID."""
    if not state.ingestion_engine:
        raise HTTPException(status_code=503, detail="Ingestion engine not initialized")

    deleted = state.ingestion_engine.store.delete(frame_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Frame #{frame_id} not found")

    return {"success": True, "message": f"Frame #{frame_id} deleted"}
