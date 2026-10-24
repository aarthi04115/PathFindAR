"""
Session Manager — Tracks active user sessions.

Each WebSocket connection creates a session that records:
  - Connection ID and timestamps
  - Pose history (ring buffer of recent positions)
  - Current floor
  - Floor transition events
  - Frame count and localization stats

Usage:
    session = SessionManager.create("ws_1")
    session.record_pose([1.0, 0.5, 2.0], [0,0,0,1], floor=0, confidence=0.8)
    print(session.summary)
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger


@dataclass
class PoseRecord:
    """A single recorded pose in the session history."""
    position: list[float]
    rotation: list[float]
    floor: int
    confidence: float
    timestamp: float
    nearest_node_id: Optional[str] = None


@dataclass
class FloorTransition:
    """Records a floor change event."""
    from_floor: int
    to_floor: int
    timestamp: float
    position: list[float]


@dataclass
class Session:
    """
    Active user session tied to a WebSocket connection.

    Maintains a ring buffer of recent poses (default 100) for
    trajectory analysis without unbounded memory growth.
    """
    connection_id: str
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)

    # State
    current_floor: int = 0
    total_frames: int = 0
    total_localizations: int = 0

    # History (ring buffers)
    pose_history: deque[PoseRecord] = field(
        default_factory=lambda: deque(maxlen=100)
    )
    floor_transitions: list[FloorTransition] = field(default_factory=list)

    # Stats
    avg_confidence: float = 0.0
    _confidence_sum: float = 0.0

    def record_pose(
        self,
        position: list[float],
        rotation: list[float],
        floor: int = 0,
        confidence: float = 0.0,
        nearest_node_id: Optional[str] = None,
    ) -> Optional[FloorTransition]:
        """
        Record a new pose and return a FloorTransition if floor changed.
        """
        self.last_active = time.time()
        self.total_frames += 1
        if confidence > 0:
            self.total_localizations += 1

        # Track confidence
        self._confidence_sum += confidence
        self.avg_confidence = self._confidence_sum / self.total_frames

        record = PoseRecord(
            position=list(position),
            rotation=list(rotation),
            floor=floor,
            confidence=confidence,
            timestamp=time.time(),
            nearest_node_id=nearest_node_id,
        )
        self.pose_history.append(record)

        # Detect floor change
        transition = None
        if floor != self.current_floor:
            transition = FloorTransition(
                from_floor=self.current_floor,
                to_floor=floor,
                timestamp=time.time(),
                position=list(position),
            )
            self.floor_transitions.append(transition)
            logger.info(
                f"[{self.connection_id}] Floor transition: "
                f"{self.current_floor} → {floor}"
            )
            self.current_floor = floor

        return transition

    @property
    def duration_sec(self) -> float:
        return time.time() - self.created_at

    @property
    def last_pose(self) -> Optional[PoseRecord]:
        return self.pose_history[-1] if self.pose_history else None

    @property
    def summary(self) -> dict:
        """Session summary for API responses."""
        return {
            "connection_id": self.connection_id,
            "created_at": self.created_at,
            "duration_sec": round(self.duration_sec, 1),
            "current_floor": self.current_floor,
            "total_frames": self.total_frames,
            "total_localizations": self.total_localizations,
            "avg_confidence": round(self.avg_confidence, 3),
            "floor_transitions": len(self.floor_transitions),
            "last_position": self.last_pose.position if self.last_pose else None,
        }


class SessionManager:
    """
    Manages all active sessions.

    Thread-safe for single-worker uvicorn (no async lock needed).
    """

    def __init__(self):
        self._sessions: dict[str, Session] = {}

    def create(self, connection_id: str) -> Session:
        """Create a new session for a WebSocket connection."""
        session = Session(connection_id=connection_id)
        self._sessions[connection_id] = session
        logger.info(f"Session created: {connection_id}")
        return session

    def get(self, connection_id: str) -> Optional[Session]:
        return self._sessions.get(connection_id)

    def remove(self, connection_id: str) -> Optional[dict]:
        """
        Remove session and return its final summary.
        Useful for logging session stats on disconnect.
        """
        session = self._sessions.pop(connection_id, None)
        if session:
            summary = session.summary
            logger.info(
                f"Session ended: {connection_id} — "
                f"{summary['total_frames']} frames, "
                f"{summary['duration_sec']}s, "
                f"{summary['floor_transitions']} floor changes"
            )
            return summary
        return None

    @property
    def active_count(self) -> int:
        return len(self._sessions)

    @property
    def all_summaries(self) -> list[dict]:
        return [s.summary for s in self._sessions.values()]
