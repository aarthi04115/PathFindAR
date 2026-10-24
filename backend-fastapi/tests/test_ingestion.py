"""
Tests for reference frame ingestion (Phase D).

Covers:
  - SQLite storage (CRUD)
  - POST /v1/ingest/frame — single-frame upload
  - GET  /v1/ingest/stats — database statistics
  - GET  /v1/ingest/frames — list ingested frames
  - DELETE /v1/ingest/frame/{id} — remove a frame
  - Error conditions
"""

import base64
import os
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def _make_fake_image_b64(size: int = 1000) -> str:
    """Generate a fake image payload (random bytes, large enough to pass validation)."""
    return base64.b64encode(os.urandom(size)).decode("ascii")


# ── POST /v1/ingest/frame ────────────────────────────────────────────────────

def test_ingest_frame(client):
    """Upload a reference frame and get back its ID."""
    payload = {
        "image_base64": _make_fake_image_b64(),
        "position": [1.5, 0.0, 3.2],
        "rotation": [0.0, 0.0, 0.0, 1.0],
        "floor": 0,
    }
    response = client.post("/v1/ingest/frame", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["frame_id"] >= 1
    assert data["floor"] == 0
    assert data["position"] == [1.5, 0.0, 3.2]
    assert "filename" in data


def test_ingest_frame_custom_filename(client):
    """Upload with a custom filename."""
    import uuid
    unique_name = f"custom_test_{uuid.uuid4().hex[:8]}.jpg"
    payload = {
        "image_base64": _make_fake_image_b64(),
        "position": [2.0, 0.0, 4.0],
        "rotation": [0.0, 0.0, 0.0, 1.0],
        "floor": 1,
        "filename": unique_name,
    }
    response = client.post("/v1/ingest/frame", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["filename"] == unique_name
    assert data["floor"] == 1


def test_ingest_frame_too_small(client):
    """Image data that's too small should be rejected."""
    payload = {
        "image_base64": base64.b64encode(b"tiny").decode(),
        "position": [0.0, 0.0, 0.0],
        "rotation": [0.0, 0.0, 0.0, 1.0],
        "floor": 0,
    }
    response = client.post("/v1/ingest/frame", json=payload)
    assert response.status_code == 400
    assert "too small" in response.json()["detail"].lower()


def test_ingest_frame_missing_position(client):
    """Missing required position field returns 422."""
    payload = {
        "image_base64": _make_fake_image_b64(),
        "floor": 0,
    }
    response = client.post("/v1/ingest/frame", json=payload)
    assert response.status_code == 422


# ── GET /v1/ingest/stats ─────────────────────────────────────────────────────

def test_ingest_stats(client):
    """Stats endpoint reports frame count."""
    response = client.get("/v1/ingest/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["total_frames"] >= 1  # we ingested at least 1 frame above
    assert "image_dir" in data
    assert "feature_dir" in data


# ── GET /v1/ingest/frames ────────────────────────────────────────────────────

def test_list_frames(client):
    """List all ingested frames."""
    response = client.get("/v1/ingest/frames")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["total"] >= 1
    frame = data["frames"][0]
    assert "id" in frame
    assert "filename" in frame
    assert len(frame["position"]) == 3
    assert len(frame["rotation"]) == 4


def test_list_frames_filter_floor(client):
    """Filter frames by floor."""
    response = client.get("/v1/ingest/frames", params={"floor": 1})
    assert response.status_code == 200
    data = response.json()
    for frame in data["frames"]:
        assert frame["floor"] == 1


# ── DELETE /v1/ingest/frame/{id} ─────────────────────────────────────────────

def test_delete_frame(client):
    """Ingest a frame then delete it."""
    # First ingest one
    payload = {
        "image_base64": _make_fake_image_b64(),
        "position": [9.0, 0.0, 9.0],
        "rotation": [0.0, 0.0, 0.0, 1.0],
        "floor": 0,
        "filename": "to_delete.jpg",
    }
    resp = client.post("/v1/ingest/frame", json=payload)
    frame_id = resp.json()["frame_id"]

    # Delete it
    resp = client.delete(f"/v1/ingest/frame/{frame_id}")
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    # Verify it's gone
    resp = client.delete(f"/v1/ingest/frame/{frame_id}")
    assert resp.status_code == 404


def test_delete_nonexistent_frame(client):
    """Deleting a non-existent frame returns 404."""
    response = client.delete("/v1/ingest/frame/99999")
    assert response.status_code == 404
