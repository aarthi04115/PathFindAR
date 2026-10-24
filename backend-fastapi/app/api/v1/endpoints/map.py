"""
GET /v1/map/*

Map discovery endpoints for Unity client:
  - GET /v1/map/info     — building metadata (name, floors, coordinate system)
  - GET /v1/map/nodes    — all navigable nodes (filterable by floor, type)
  - GET /v1/map/pois     — named points of interest (destinations for picker UI)
  - GET /v1/map/node/{id} — single node detail
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from loguru import logger

from app.core import state

router = APIRouter()


# ── Response schemas ─────────────────────────────────────────────────────────

class BuildingInfo(BaseModel):
    """High-level building metadata."""
    name: str
    floors: int
    floor_height_m: float
    coordinate_system: str
    total_nodes: int
    total_edges: int


class NodeInfo(BaseModel):
    """A single navigable node."""
    id: str
    label: str
    position: list[float] = Field(..., description="[x, y, z] Unity coords")
    floor: int
    type: str = Field(..., description="poi | room | corridor | junction | stairwell | elevator")
    tags: list[str] = []


class POI(BaseModel):
    """A named point-of-interest (destination for nav picker UI)."""
    id: str
    label: str
    position: list[float]
    floor: int
    type: str
    tags: list[str] = []
    aliases: list[str] = Field(default=[], description="Alternative names for this POI")


class MapNodesResponse(BaseModel):
    success: bool
    nodes: list[NodeInfo] = []
    total: int = 0
    floor_filter: Optional[int] = None
    type_filter: Optional[str] = None


class MapPOIsResponse(BaseModel):
    success: bool
    pois: list[POI] = []
    total: int = 0


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/info", response_model=BuildingInfo)
async def get_map_info():
    """
    Building metadata — name, floor count, coordinate system.
    Unity client calls this once on startup to configure the AR scene.
    """
    nav = state.navigator
    if not nav.is_loaded:
        raise HTTPException(status_code=503, detail="Map not loaded")

    # Read building metadata from the raw map data
    import json
    from pathlib import Path
    from app.core.config import settings

    map_path = Path(settings.DATA_PATH) / settings.MAP_FILE
    with map_path.open("r") as f:
        raw = json.load(f)

    building = raw.get("building", {})
    return BuildingInfo(
        name=building.get("name", "Unknown"),
        floors=building.get("floors", 1),
        floor_height_m=building.get("floor_height_m", 3.0),
        coordinate_system=building.get("coordinate_system", "unity_world"),
        total_nodes=len(nav.nodes),
        total_edges=nav.graph.number_of_edges(),
    )


@router.get("/nodes", response_model=MapNodesResponse)
async def get_map_nodes(
    floor: Optional[int] = Query(None, description="Filter by floor index"),
    type: Optional[str] = Query(None, description="Filter by node type (room, poi, corridor, etc.)"),
):
    """
    All navigable nodes in the building graph.
    Unity uses this to render available destination markers on the AR map.

    Filterable by floor and/or node type.
    """
    nav = state.navigator
    if not nav.is_loaded:
        raise HTTPException(status_code=503, detail="Map not loaded")

    nodes = []
    for nid, node in nav.nodes.items():
        if floor is not None and node.floor != floor:
            continue
        if type is not None and node.type != type:
            continue
        nodes.append(NodeInfo(
            id=node.id,
            label=node.label,
            position=node.position,
            floor=node.floor,
            type=node.type,
            tags=node.tags,
        ))

    logger.debug(f"Map nodes query: floor={floor}, type={type} → {len(nodes)} results")
    return MapNodesResponse(
        success=True,
        nodes=nodes,
        total=len(nodes),
        floor_filter=floor,
        type_filter=type,
    )


@router.get("/pois", response_model=MapPOIsResponse)
async def get_map_pois():
    """
    Points of interest — rooms, labs, facilities, etc.
    These are the selectable destinations in the Unity navigation picker.

    Excludes corridor/junction nodes (internal graph nodes not useful as destinations).
    Also includes POI aliases (e.g. "toilet" → "Toilets (GF)").
    """
    nav = state.navigator
    if not nav.is_loaded:
        raise HTTPException(status_code=503, detail="Map not loaded")

    # Inverse alias map: node_id → [aliases]
    node_aliases: dict[str, list[str]] = {}
    for alias, targets in nav.poi_aliases.items():
        for target in targets:
            node_aliases.setdefault(target, []).append(alias)

    # POI types = anything that's not purely a graph junction/corridor
    poi_types = {"poi", "room", "stairwell", "elevator"}
    pois = []
    for nid, node in nav.nodes.items():
        if node.type not in poi_types:
            continue
        pois.append(POI(
            id=node.id,
            label=node.label,
            position=node.position,
            floor=node.floor,
            type=node.type,
            tags=node.tags,
            aliases=node_aliases.get(node.id, []),
        ))

    # Sort: POIs first, then rooms, then vertical transitions
    type_order = {"poi": 0, "room": 1, "elevator": 2, "stairwell": 3}
    pois.sort(key=lambda p: (p.floor, type_order.get(p.type, 99), p.label))

    logger.debug(f"Map POIs query → {len(pois)} results")
    return MapPOIsResponse(success=True, pois=pois, total=len(pois))


@router.get("/node/{node_id}", response_model=NodeInfo)
async def get_node_detail(node_id: str):
    """
    Single node detail by ID.
    Unity uses this for inspecting a specific waypoint or destination.
    """
    nav = state.navigator
    if not nav.is_loaded:
        raise HTTPException(status_code=503, detail="Map not loaded")

    node = nav.get_node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id!r}")

    return NodeInfo(
        id=node.id,
        label=node.label,
        position=node.position,
        floor=node.floor,
        type=node.type,
        tags=node.tags,
    )
