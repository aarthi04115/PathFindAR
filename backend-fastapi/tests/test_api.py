"""
API tests for PathFindAR backend.

Covers:
  - Health check
  - POST /v1/localize  — passthrough mode (no CV2 in test env)
  - GET  /v1/route     — real A* on sample map
  - Error conditions   — missing params, bad node IDs
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client():
    """Session-scoped client — runs lifespan once for all tests."""
    with TestClient(app) as c:
        yield c


# ── Health ────────────────────────────────────────────────────────────────────

def test_health_check(client):
    """Health endpoint returns OK with map/model status fields."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "pathfindar-backend"
    assert "nav_map_loaded" in data
    assert "localization_loaded" in data


# ── Localize ──────────────────────────────────────────────────────────────────

def test_localize_post_passthrough(client):
    """
    POST /v1/localize returns corrected pose.
    Without real CV2, preprocessing fails → passthrough with confidence=0.
    """
    payload = {
        "image_base64": "dGVzdA==",   # base64("test") — not a real image
        "arcore_pose": {
            "position": [1.0, 0.5, 2.0],
            "rotation": [0.0, 0.0, 0.0, 1.0],
        },
        "timestamp": 1700000000.0,
        "floor": 0,
    }
    response = client.post("/v1/localize", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["pose"]["position"] == [1.0, 0.5, 2.0]
    assert data["pose"]["confidence"] == 0.0   # passthrough mode
    assert "latency_ms" in data


def test_localize_get_rejected(client):
    """GET /v1/localize should return 405 (POST only)."""
    response = client.get("/v1/localize")
    assert response.status_code == 405


def test_localize_missing_required_fields(client):
    """POST /v1/localize without required fields returns 422."""
    response = client.post("/v1/localize", json={"timestamp": 123.0})
    assert response.status_code == 422


# ── Route (A*) ────────────────────────────────────────────────────────────────

def test_route_entrance_to_room_101(client):
    """A* should find a path from entrance to room_101."""
    response = client.get("/v1/route", params={
        "start_node": "entrance",
        "destination": "room_101",
        "floor": 0,
    })
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    waypoints = data["waypoints"]
    assert len(waypoints) >= 2
    assert waypoints[0]["node_id"] == "entrance"
    assert waypoints[-1]["node_id"] == "room_101"
    assert data["total_distance"] > 0
    assert data["estimated_time_sec"] > 0
    assert "latency_ms" in data


def test_route_cross_floor(client):
    """A* should route from ground floor to floor 1 via stairwell/elevator."""
    response = client.get("/v1/route", params={
        "start_node": "entrance",
        "destination": "room_201",
        "floor": 0,
    })
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    node_ids = [wp["node_id"] for wp in data["waypoints"]]
    vertical_nodes = {"stairwell_gf", "elevator_gf", "stairwell_f1", "elevator_f1"}
    assert any(nid in vertical_nodes for nid in node_ids), (
        f"Expected vertical transition in path, got: {node_ids}"
    )


def test_route_poi_alias(client):
    """Should resolve 'toilet' alias to the nearest toilet node."""
    response = client.get("/v1/route", params={
        "start_node": "entrance",
        "destination": "toilet",
        "floor": 0,
    })
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["waypoints"][-1]["node_id"] == "toilet_gf"


def test_route_same_start_and_end(client):
    """Route from a node to itself returns a single-waypoint route."""
    response = client.get("/v1/route", params={
        "start_node": "lobby",
        "destination": "lobby",
        "floor": 0,
    })
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert len(data["waypoints"]) == 1
    assert data["total_distance"] == 0.0


def test_route_unknown_node(client):
    """Unknown node ID should return 404."""
    response = client.get("/v1/route", params={
        "start_node": "entrance",
        "destination": "nonexistent_room_999",
        "floor": 0,
    })
    assert response.status_code == 404


def test_route_missing_params(client):
    """GET /v1/route without required params returns 422."""
    response = client.get("/v1/route")
    assert response.status_code == 422


def test_route_waypoints_have_required_fields(client):
    """Every returned waypoint must have the full schema."""
    response = client.get("/v1/route", params={
        "start_node": "lobby",
        "destination": "room_102",
        "floor": 0,
    })
    assert response.status_code == 200
    for wp in response.json()["waypoints"]:
        assert "node_id" in wp
        assert "position" in wp
        assert len(wp["position"]) == 3
        assert "floor" in wp
        assert "is_turn" in wp
