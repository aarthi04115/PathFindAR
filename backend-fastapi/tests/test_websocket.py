"""
Tests for WebSocket /v1/ws/localize endpoint.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


# ── Connection ───────────────────────────────────────────────────────────────

def test_ws_connect_and_receive_status(client):
    """WebSocket should accept and send a 'connected' message."""
    with client.websocket_connect("/v1/ws/localize") as ws:
        data = json.loads(ws.receive_text())
        assert data["type"] == "connected"
        assert "connection_id" in data
        assert "nav_map_loaded" in data
        assert "localization_loaded" in data


# ── Ping / Pong ──────────────────────────────────────────────────────────────

def test_ws_ping_pong(client):
    """Ping should return pong."""
    with client.websocket_connect("/v1/ws/localize") as ws:
        ws.receive_text()  # consume connected msg
        ws.send_text(json.dumps({"type": "ping"}))
        data = json.loads(ws.receive_text())
        assert data["type"] == "pong"


# ── Localize ─────────────────────────────────────────────────────────────────

def test_ws_localize_passthrough(client):
    """Localize frame should return a pose response (passthrough mode)."""
    with client.websocket_connect("/v1/ws/localize") as ws:
        ws.receive_text()  # consume connected msg
        ws.send_text(json.dumps({
            "type": "localize",
            "image_base64": "dGVzdA==",
            "arcore_pose": {
                "position": [1.0, 0.5, 2.0],
                "rotation": [0.0, 0.0, 0.0, 1.0],
            },
            "timestamp": 1700000000.0,
        }))
        data = json.loads(ws.receive_text())
        assert data["type"] == "pose"
        assert data["pose"]["position"] == [1.0, 0.5, 2.0]
        assert data["pose"]["confidence"] == 0.0  # passthrough
        assert "latency_ms" in data


def test_ws_localize_missing_pose(client):
    """Missing arcore_pose should return error."""
    with client.websocket_connect("/v1/ws/localize") as ws:
        ws.receive_text()
        ws.send_text(json.dumps({
            "type": "localize",
            "image_base64": "dGVzdA==",
        }))
        data = json.loads(ws.receive_text())
        assert data["type"] == "error"
        assert "arcore_pose" in data["message"]


# ── Nearest Node ─────────────────────────────────────────────────────────────

def test_ws_nearest_node(client):
    """nearest_node should return the closest graph node."""
    with client.websocket_connect("/v1/ws/localize") as ws:
        ws.receive_text()
        ws.send_text(json.dumps({
            "type": "nearest_node",
            "position": [0.0, 0.0, 0.0],
            "floor": 0,
        }))
        data = json.loads(ws.receive_text())
        assert data["type"] == "nearest_node"
        assert data["node_id"] is not None
        assert data["node_id"] == "entrance"  # closest to [0,0,0]


# ── Error handling ───────────────────────────────────────────────────────────

def test_ws_invalid_json(client):
    """Invalid JSON should return error, not crash."""
    with client.websocket_connect("/v1/ws/localize") as ws:
        ws.receive_text()
        ws.send_text("not valid json {{{")
        data = json.loads(ws.receive_text())
        assert data["type"] == "error"
        assert "Invalid JSON" in data["message"]


def test_ws_unknown_type(client):
    """Unknown message type should return error."""
    with client.websocket_connect("/v1/ws/localize") as ws:
        ws.receive_text()
        ws.send_text(json.dumps({"type": "foobar"}))
        data = json.loads(ws.receive_text())
        assert data["type"] == "error"
        assert "Unknown" in data["message"]
