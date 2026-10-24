"""
Tests for PoseSmoother (adaptive EMA + teleport detection).
"""

import math
import json
import pytest
from fastapi.testclient import TestClient

from app.localization.smoother import PoseSmoother
from app.main import app


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


# ── Unit tests (pure math, no server needed) ─────────────────────────────────

class TestPoseSmootherUnit:
    """Pure unit tests for the smoother logic."""

    def test_first_frame_is_raw(self):
        """First frame should pass through unsmoothed."""
        s = PoseSmoother(alpha=0.3)
        result = s.update([1.0, 2.0, 3.0], [0, 0, 0, 1], confidence=0.8)
        assert result.position == [1.0, 2.0, 3.0]
        assert result.smoothing_applied == 1.0

    def test_second_frame_is_smoothed(self):
        """Second frame should be blended with the first."""
        s = PoseSmoother(alpha=0.5, confidence_weight=0.0)
        s.update([0.0, 0.0, 0.0], [0, 0, 0, 1], confidence=0.5)
        result = s.update([2.0, 0.0, 0.0], [0, 0, 0, 1], confidence=0.5)
        # EMA: 0.5 * 2.0 + 0.5 * 0.0 = 1.0
        assert abs(result.position[0] - 1.0) < 0.01
        assert result.smoothing_applied == 0.5

    def test_high_confidence_trusts_new_more(self):
        """Higher confidence should shift alpha toward the new measurement."""
        s = PoseSmoother(alpha=0.3, confidence_weight=0.5)
        s.update([0.0, 0.0, 0.0], [0, 0, 0, 1], confidence=0.0)
        # confidence=1.0 → alpha = 0.3 + 0.5*1.0 = 0.8
        result = s.update([10.0, 0.0, 0.0], [0, 0, 0, 1], confidence=1.0)
        assert result.position[0] > 5.0  # close to 8.0

    def test_low_confidence_trusts_history(self):
        """Low confidence should lean on previous pose."""
        s = PoseSmoother(alpha=0.3, confidence_weight=0.5)
        s.update([0.0, 0.0, 0.0], [0, 0, 0, 1], confidence=0.0)
        # confidence=0.0 → alpha = 0.3 + 0.5*0.0 = 0.3
        # Use 3m jump (under 5m teleport threshold)
        result = s.update([3.0, 0.0, 0.0], [0, 0, 0, 1], confidence=0.0)
        assert result.position[0] < 1.5  # close to 0.9 (0.3 * 3.0)

    def test_teleport_resets(self):
        """Large position jump should skip smoothing (floor change)."""
        s = PoseSmoother(alpha=0.3, velocity_threshold=5.0)
        s.update([0.0, 0.0, 0.0], [0, 0, 0, 1], confidence=0.5)
        # Jump 100 meters — should be treated as teleport
        result = s.update([100.0, 0.0, 0.0], [0, 0, 0, 1], confidence=0.5)
        assert result.position[0] == 100.0
        assert result.smoothing_applied == 1.0

    def test_reset_clears_state(self):
        """After reset, next frame should be unsmoothed."""
        s = PoseSmoother(alpha=0.3)
        s.update([1.0, 0.0, 0.0], [0, 0, 0, 1], confidence=0.5)
        s.update([2.0, 0.0, 0.0], [0, 0, 0, 1], confidence=0.5)
        s.reset()
        result = s.update([5.0, 0.0, 0.0], [0, 0, 0, 1], confidence=0.5)
        assert result.position[0] == 5.0
        assert result.smoothing_applied == 1.0

    def test_quaternion_normalization(self):
        """Smoothed quaternion should always be unit length."""
        s = PoseSmoother(alpha=0.5, confidence_weight=0.0)
        s.update([0, 0, 0], [0, 0, 0, 1], confidence=0.5)
        result = s.update([0, 0, 0], [0.707, 0, 0, 0.707], confidence=0.5)
        norm = math.sqrt(sum(x**2 for x in result.rotation))
        assert abs(norm - 1.0) < 0.001

    def test_convergence_over_many_frames(self):
        """After many identical frames, should converge to that value."""
        s = PoseSmoother(alpha=0.3, confidence_weight=0.0)
        target = [5.0, 3.0, 1.0]
        s.update([0.0, 0.0, 0.0], [0, 0, 0, 1], confidence=0.5)
        for _ in range(50):
            result = s.update(target, [0, 0, 0, 1], confidence=0.5)
        for i in range(3):
            assert abs(result.position[i] - target[i]) < 0.01


# ── WebSocket integration (smoother wired in) ────────────────────────────────

def test_ws_localize_has_smoothing_alpha(client):
    """WebSocket localize response should include smoothing_alpha field."""
    with client.websocket_connect("/v1/ws/localize") as ws:
        ws.receive_text()  # connected msg
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
        assert "smoothing_alpha" in data


def test_ws_reset_smoother(client):
    """reset_smoother message should return smoother_reset confirmation."""
    with client.websocket_connect("/v1/ws/localize") as ws:
        ws.receive_text()  # connected msg
        ws.send_text(json.dumps({"type": "reset_smoother"}))
        data = json.loads(ws.receive_text())
        assert data["type"] == "smoother_reset"
