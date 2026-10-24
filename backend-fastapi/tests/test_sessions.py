"""
Tests for session tracking and floor change detection.
"""

import json
import pytest
from fastapi.testclient import TestClient

from app.core.sessions import Session, SessionManager
from app.main import app


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


# ── Unit tests (SessionManager) ──────────────────────────────────────────────

class TestSessionUnit:

    def test_create_and_remove(self):
        mgr = SessionManager()
        session = mgr.create("test_1")
        assert mgr.active_count == 1
        summary = mgr.remove("test_1")
        assert mgr.active_count == 0
        assert summary["connection_id"] == "test_1"

    def test_record_pose(self):
        session = Session(connection_id="test")
        session.record_pose([1.0, 0.0, 2.0], [0, 0, 0, 1], floor=0, confidence=0.8)
        assert session.total_frames == 1
        assert session.total_localizations == 1
        assert session.last_pose.position == [1.0, 0.0, 2.0]

    def test_floor_transition_detected(self):
        session = Session(connection_id="test")
        result = session.record_pose([0, 0, 0], [0, 0, 0, 1], floor=0)
        assert result is None  # no transition

        result = session.record_pose([0, 4, 0], [0, 0, 0, 1], floor=1)
        assert result is not None
        assert result.from_floor == 0
        assert result.to_floor == 1
        assert session.current_floor == 1
        assert len(session.floor_transitions) == 1

    def test_no_transition_same_floor(self):
        session = Session(connection_id="test")
        session.record_pose([0, 0, 0], [0, 0, 0, 1], floor=0)
        result = session.record_pose([1, 0, 0], [0, 0, 0, 1], floor=0)
        assert result is None

    def test_avg_confidence(self):
        session = Session(connection_id="test")
        session.record_pose([0, 0, 0], [0, 0, 0, 1], floor=0, confidence=0.6)
        session.record_pose([1, 0, 0], [0, 0, 0, 1], floor=0, confidence=0.8)
        assert abs(session.avg_confidence - 0.7) < 0.01

    def test_summary_contains_all_fields(self):
        session = Session(connection_id="test")
        session.record_pose([1, 2, 3], [0, 0, 0, 1], floor=0, confidence=0.5)
        s = session.summary
        assert "connection_id" in s
        assert "duration_sec" in s
        assert "current_floor" in s
        assert "total_frames" in s
        assert "avg_confidence" in s
        assert "last_position" in s

    def test_pose_history_ring_buffer(self):
        session = Session(connection_id="test")
        for i in range(150):
            session.record_pose([float(i), 0, 0], [0, 0, 0, 1], floor=0)
        # Ring buffer maxlen=100
        assert len(session.pose_history) == 100
        assert session.total_frames == 150


# ── WebSocket integration ────────────────────────────────────────────────────

def test_ws_session_info(client):
    """session_info message returns session stats."""
    with client.websocket_connect("/v1/ws/localize") as ws:
        ws.receive_text()  # connected msg

        # Send a localize frame first
        ws.send_text(json.dumps({
            "type": "localize",
            "arcore_pose": {"position": [1, 0, 2], "rotation": [0, 0, 0, 1]},
            "floor": 0,
        }))
        ws.receive_text()  # pose response

        # Request session info
        ws.send_text(json.dumps({"type": "session_info"}))
        data = json.loads(ws.receive_text())
        assert data["type"] == "session_info"
        assert data["total_frames"] == 1
        assert data["current_floor"] == 0


def test_ws_floor_change_detected(client):
    """Floor change should be reported in the pose response."""
    with client.websocket_connect("/v1/ws/localize") as ws:
        ws.receive_text()  # connected msg

        # Frame on floor 0
        ws.send_text(json.dumps({
            "type": "localize",
            "arcore_pose": {"position": [1, 0, 2], "rotation": [0, 0, 0, 1]},
            "floor": 0,
        }))
        data = json.loads(ws.receive_text())
        assert "floor_changed" not in data

        # Frame on floor 1 — should trigger floor_changed
        ws.send_text(json.dumps({
            "type": "localize",
            "arcore_pose": {"position": [1, 4, 2], "rotation": [0, 0, 0, 1]},
            "floor": 1,
        }))
        data = json.loads(ws.receive_text())
        assert "floor_changed" in data
        assert data["floor_changed"]["from"] == 0
        assert data["floor_changed"]["to"] == 1


def test_health_includes_active_sessions(client):
    """Health check should report active_sessions count."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "active_sessions" in data
    assert data["active_sessions"] >= 0


def test_sessions_endpoint(client):
    """GET /sessions should return session list."""
    response = client.get("/sessions")
    assert response.status_code == 200
    data = response.json()
    assert "active_sessions" in data
    assert "sessions" in data
