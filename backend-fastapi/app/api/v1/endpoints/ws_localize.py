"""
WebSocket /v1/ws/localize

Real-time pose streaming for Unity client.

Protocol (JSON messages):
  Client → Server:
    {
      "type": "localize",
      "image_base64": "...",
      "arcore_pose": {"position": [x,y,z], "rotation": [x,y,z,w]},
      "timestamp": 1700000000.0,
      "floor": 0
    }
    {
      "type": "ping"
    }

  Server → Client:
    {
      "type": "pose",
      "pose": {"position": [...], "rotation": [...], "confidence": 0.8, "nearest_node_id": "lobby"},
      "timestamp": 1700000000.0,
      "latency_ms": 12.3
    }
    {
      "type": "pong"
    }
    {
      "type": "error",
      "message": "..."
    }

Benefits over HTTP POST:
  - No TCP handshake per frame → ~10× lower latency
  - Persistent connection → server can push updates
  - Binary frame support possible in future
"""

from __future__ import annotations

import time
import json
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from app.core import state
from app.core.sessions import SessionManager
from app.localization.smoother import PoseSmoother

router = APIRouter()
session_manager = SessionManager()


# ── Connection manager ───────────────────────────────────────────────────────

class ConnectionManager:
    """
    Tracks active WebSocket connections.
    Useful for broadcasting (future: multi-user map, shared sessions).
    """

    def __init__(self):
        self.active: dict[str, WebSocket] = {}  # connection_id → ws
        self._counter: int = 0

    async def connect(self, websocket: WebSocket) -> str:
        """Accept connection and return a unique ID."""
        await websocket.accept()
        self._counter += 1
        conn_id = f"ws_{self._counter}"
        self.active[conn_id] = websocket
        logger.info(f"WebSocket connected: {conn_id} | active={len(self.active)}")
        return conn_id

    def disconnect(self, conn_id: str) -> None:
        self.active.pop(conn_id, None)
        logger.info(f"WebSocket disconnected: {conn_id} | active={len(self.active)}")

    @property
    def count(self) -> int:
        return len(self.active)


manager = ConnectionManager()


# ── WebSocket endpoint ───────────────────────────────────────────────────────

@router.websocket("")
async def ws_localize(websocket: WebSocket):
    """
    Real-time localization over WebSocket.

    Unity client sends localize frames as JSON; server responds with
    corrected poses. Connection stays open for the entire session.
    Each connection gets its own PoseSmoother to prevent AR jitter.
    """
    conn_id = await manager.connect(websocket)
    smoother = PoseSmoother(alpha=0.3, confidence_weight=0.5)
    session = session_manager.create(conn_id)

    # Send initial status
    await _send_json(websocket, {
        "type": "connected",
        "connection_id": conn_id,
        "nav_map_loaded": state.navigator.is_loaded,
        "localization_loaded": state.localization.is_loaded,
    })

    try:
        while True:
            # Receive message
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send_error(websocket, "Invalid JSON")
                continue

            msg_type = msg.get("type", "")

            if msg_type == "ping":
                await _send_json(websocket, {"type": "pong"})

            elif msg_type == "localize":
                await _handle_localize(websocket, msg, smoother, session)

            elif msg_type == "reset_smoother":
                smoother.reset()
                await _send_json(websocket, {"type": "smoother_reset"})

            elif msg_type == "nearest_node":
                await _handle_nearest_node(websocket, msg)

            elif msg_type == "session_info":
                await _send_json(websocket, {
                    "type": "session_info",
                    **session.summary,
                })

            else:
                await _send_error(websocket, f"Unknown message type: {msg_type!r}")

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.exception(f"WebSocket error [{conn_id}]: {exc}")
    finally:
        session_manager.remove(conn_id)
        manager.disconnect(conn_id)


# ── Message handlers ─────────────────────────────────────────────────────────

async def _handle_localize(
    ws: WebSocket, msg: dict, smoother: PoseSmoother, session=None
) -> None:
    """Process a localize frame, smooth the result, record in session."""
    t0 = time.perf_counter()

    # Validate required fields
    image_b64 = msg.get("image_base64")
    arcore_pose = msg.get("arcore_pose")
    timestamp = msg.get("timestamp", time.time())
    floor = msg.get("floor", session.current_floor if session else 0)

    if not arcore_pose:
        await _send_error(ws, "Missing 'arcore_pose' field")
        return

    position = arcore_pose.get("position")
    rotation = arcore_pose.get("rotation")
    if not position or not rotation:
        await _send_error(ws, "arcore_pose must have 'position' and 'rotation'")
        return

    if not state.localization.is_loaded:
        # Still smooth even in passthrough mode
        smoothed = smoother.update(position, rotation, confidence=0.0)

        # Record in session + detect floor change
        floor_event = None
        if session:
            floor_event = session.record_pose(
                smoothed.position, smoothed.rotation,
                floor=floor, confidence=0.0,
            )
            if floor_event:
                smoother.reset()
                smoothed = smoother.update(position, rotation, confidence=0.0)

        response = {
            "type": "pose",
            "pose": {
                "position": smoothed.position,
                "rotation": smoothed.rotation,
                "confidence": 0.0,
                "nearest_node_id": None,
            },
            "timestamp": timestamp,
            "latency_ms": 0.0,
            "smoothing_alpha": smoothed.smoothing_applied,
            "note": "Localization pipeline not loaded — passthrough (smoothed)",
        }
        if floor_event:
            response["floor_changed"] = {
                "from": floor_event.from_floor,
                "to": floor_event.to_floor,
            }
        await _send_json(ws, response)
        return

    # Run localization pipeline
    try:
        result = state.localization.localize(
            image_base64=image_b64 or "",
            arcore_pose={"position": position, "rotation": rotation},
        )
    except Exception as exc:
        logger.error(f"Localization error: {exc}")
        await _send_error(ws, f"Localization error: {exc}")
        return

    # Apply pose smoothing
    confidence = result.get("confidence", 0.0)
    smoothed = smoother.update(
        position=result["position"],
        rotation=result["rotation"],
        confidence=confidence,
    )

    # Record in session + detect floor change
    floor_event = None
    if session:
        floor_event = session.record_pose(
            smoothed.position, smoothed.rotation,
            floor=floor, confidence=confidence,
            nearest_node_id=result.get("nearest_node_id"),
        )
        if floor_event:
            # Floor changed — reset smoother so we don't blend across floors
            smoother.reset()
            smoothed = smoother.update(
                result["position"], result["rotation"], confidence=confidence
            )

    latency_ms = (time.perf_counter() - t0) * 1000

    response = {
        "type": "pose",
        "pose": {
            "position": smoothed.position,
            "rotation": smoothed.rotation,
            "confidence": confidence,
            "nearest_node_id": result.get("nearest_node_id"),
        },
        "timestamp": timestamp,
        "latency_ms": round(latency_ms, 2),
        "smoothing_alpha": round(smoothed.smoothing_applied, 3),
    }
    if floor_event:
        response["floor_changed"] = {
            "from": floor_event.from_floor,
            "to": floor_event.to_floor,
        }
    await _send_json(ws, response)


async def _handle_nearest_node(ws: WebSocket, msg: dict) -> None:
    """
    Lightweight: just find the nearest graph node to a position.
    Useful when Unity doesn't need full localization, just a map snap.
    """
    position = msg.get("position")
    floor = msg.get("floor")
    if not position or len(position) != 3:
        await _send_error(ws, "'position' must be [x, y, z]")
        return

    if not state.navigator.is_loaded:
        await _send_error(ws, "Navigation map not loaded")
        return

    node_id = state.navigator.get_nearest_node(position, floor=floor)
    node = state.navigator.get_node(node_id) if node_id else None

    await _send_json(ws, {
        "type": "nearest_node",
        "node_id": node_id,
        "label": node.label if node else None,
        "node_position": node.position if node else None,
        "floor": node.floor if node else None,
    })


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _send_json(ws: WebSocket, data: dict) -> None:
    await ws.send_text(json.dumps(data))


async def _send_error(ws: WebSocket, message: str) -> None:
    logger.debug(f"WS error response: {message}")
    await _send_json(ws, {"type": "error", "message": message})
