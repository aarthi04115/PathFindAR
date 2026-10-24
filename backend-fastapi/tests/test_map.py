"""
Tests for map discovery endpoints (GET /v1/map/*).
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


# ── GET /v1/map/info ─────────────────────────────────────────────────────────

def test_map_info(client):
    """Building info returns metadata."""
    response = client.get("/v1/map/info")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Sample Building"
    assert data["floors"] == 2
    assert data["floor_height_m"] == 4.0
    assert data["total_nodes"] > 0
    assert data["total_edges"] > 0


# ── GET /v1/map/nodes ────────────────────────────────────────────────────────

def test_map_nodes_all(client):
    """Returns all nodes when no filters applied."""
    response = client.get("/v1/map/nodes")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["total"] == 20  # sample map has 20 nodes


def test_map_nodes_filter_floor(client):
    """Filter nodes by floor."""
    response = client.get("/v1/map/nodes", params={"floor": 0})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["floor_filter"] == 0
    for node in data["nodes"]:
        assert node["floor"] == 0


def test_map_nodes_filter_type(client):
    """Filter nodes by type."""
    response = client.get("/v1/map/nodes", params={"type": "room"})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["type_filter"] == "room"
    for node in data["nodes"]:
        assert node["type"] == "room"


def test_map_nodes_filter_floor_and_type(client):
    """Combined floor + type filter."""
    response = client.get("/v1/map/nodes", params={"floor": 1, "type": "room"})
    assert response.status_code == 200
    data = response.json()
    for node in data["nodes"]:
        assert node["floor"] == 1
        assert node["type"] == "room"
    # Floor 1 rooms: room_201, room_202
    assert data["total"] == 2


# ── GET /v1/map/pois ─────────────────────────────────────────────────────────

def test_map_pois(client):
    """POIs exclude corridors and junctions."""
    response = client.get("/v1/map/pois")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["total"] > 0
    for poi in data["pois"]:
        assert poi["type"] not in ("corridor", "junction")


def test_map_pois_have_aliases(client):
    """Some POIs should have aliases (e.g. toilet_gf → ['toilet', 'restroom', 'wc'])."""
    response = client.get("/v1/map/pois")
    data = response.json()
    toilet = next((p for p in data["pois"] if p["id"] == "toilet_gf"), None)
    assert toilet is not None
    assert len(toilet["aliases"]) > 0
    assert "toilet" in toilet["aliases"]


# ── GET /v1/map/node/{id} ────────────────────────────────────────────────────

def test_map_node_detail(client):
    """Get single node by ID."""
    response = client.get("/v1/map/node/lobby")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "lobby"
    assert data["label"] == "Lobby"
    assert len(data["position"]) == 3


def test_map_node_not_found(client):
    """Unknown node ID returns 404."""
    response = client.get("/v1/map/node/does_not_exist")
    assert response.status_code == 404
