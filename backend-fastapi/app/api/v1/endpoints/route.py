"""
GET /v1/route

Accepts start position + destination, returns ordered waypoints.
Unity uses these to render AR navigation arrows.
"""

import time
from typing import Optional

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field
from loguru import logger

from app.core import state

router = APIRouter()


# ── Response schemas ────────────────────────────────────────────────────────

class Waypoint(BaseModel):
    """Single navigation waypoint in Unity world coordinates."""
    node_id: str = Field(..., description="Graph node ID")
    label: str = Field("", description="Human-readable label")
    position: list[float] = Field(..., min_length=3, max_length=3, description="[x, y, z] Unity coords")
    floor: int = Field(0, description="Floor index")
    is_turn: bool = Field(False, description="Whether this is a turn point")
    turn_direction: Optional[str] = Field(None, description="'left' | 'right' | None")


class RouteResponse(BaseModel):
    """Navigation route for Unity AR rendering."""
    success: bool
    waypoints: list[Waypoint] = []
    total_distance: float = Field(0.0, description="Total path distance in metres")
    estimated_time_sec: float = Field(0.0, description="Estimated walk time in seconds")
    message: str = ""
    latency_ms: float = 0.0


# ── Endpoint ────────────────────────────────────────────────────────────────

@router.get("", response_model=RouteResponse)
async def get_route(
    start_node: str = Query(..., description="Starting node ID, POI alias, or 'current'"),
    destination: str = Query(..., description="Destination node ID or POI alias"),
    floor: int = Query(0, description="Current floor (used for alias resolution)"),
    accessible_only: bool = Query(False, description="Prefer wheelchair-accessible routes"),
):
    """
    Compute shortest path from start to destination using A*.

    Returns ordered waypoints with turn indicators for AR rendering.
    Node IDs and POI aliases (e.g. 'toilet', 'cafeteria') are both accepted.
    """
    t0 = time.perf_counter()
    logger.info(f"Route request — start={start_node!r}, dest={destination!r}, floor={floor}")

    if not state.navigator.is_loaded:
        raise HTTPException(status_code=503, detail="Navigation map not loaded yet")

    try:
        result = state.navigator.find_route(
            start_node=start_node,
            end_node=destination,
            floor=floor,
            accessible_only=accessible_only,
        )
    except ValueError as exc:
        logger.warning(f"Route error: {exc}")
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        logger.error(f"Navigator runtime error: {exc}")
        raise HTTPException(status_code=503, detail=str(exc))

    latency_ms = (time.perf_counter() - t0) * 1000

    waypoints = [Waypoint(**wp) for wp in result["waypoints"]]

    return RouteResponse(
        success=True,
        waypoints=waypoints,
        total_distance=result["total_distance"],
        estimated_time_sec=result["estimated_time_sec"],
        message=f"Route computed: {len(waypoints)} waypoints",
        latency_ms=round(latency_ms, 2),
    )
