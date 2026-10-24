"""
Reference Frame Storage — SQLite backend.

Stores metadata for reference images used by the localization pipeline:
  - Image filename on disk
  - 6-DoF pose (position + quaternion rotation)
  - Floor index
  - Feature vector path (pre-computed by FeatureExtractor)

Schema is auto-created on first use. No migrations needed.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from loguru import logger


@dataclass
class ReferenceFrame:
    """A single reference image with its known pose."""
    id: Optional[int] = None
    filename: str = ""
    floor: int = 0
    pos_x: float = 0.0
    pos_y: float = 0.0
    pos_z: float = 0.0
    rot_x: float = 0.0
    rot_y: float = 0.0
    rot_z: float = 0.0
    rot_w: float = 1.0
    feature_path: str = ""       # path to pre-computed .npz features
    created_at: float = field(default_factory=time.time)

    @property
    def position(self) -> list[float]:
        return [self.pos_x, self.pos_y, self.pos_z]

    @property
    def rotation(self) -> list[float]:
        return [self.rot_x, self.rot_y, self.rot_z, self.rot_w]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS frames (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    filename     TEXT    NOT NULL UNIQUE,
    floor        INTEGER NOT NULL DEFAULT 0,
    pos_x        REAL    NOT NULL DEFAULT 0.0,
    pos_y        REAL    NOT NULL DEFAULT 0.0,
    pos_z        REAL    NOT NULL DEFAULT 0.0,
    rot_x        REAL    NOT NULL DEFAULT 0.0,
    rot_y        REAL    NOT NULL DEFAULT 0.0,
    rot_z        REAL    NOT NULL DEFAULT 0.0,
    rot_w        REAL    NOT NULL DEFAULT 1.0,
    feature_path TEXT    NOT NULL DEFAULT '',
    created_at   REAL    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_frames_floor ON frames(floor);
"""


class ReferenceFrameStore:
    """
    SQLite-backed store for reference frame metadata.

    Usage:
        store = ReferenceFrameStore("data/reference_frames.db")
        frame_id = store.insert(ReferenceFrame(...))
        frames = store.get_all(floor=0)
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        count = self._conn.execute("SELECT COUNT(*) FROM frames").fetchone()[0]
        logger.info(f"ReferenceFrameStore ready: {self.db_path} ({count} frames)")

    def insert(self, frame: ReferenceFrame) -> int:
        """Insert a reference frame, returns its ID."""
        cur = self._conn.execute(
            """
            INSERT INTO frames
                (filename, floor, pos_x, pos_y, pos_z,
                 rot_x, rot_y, rot_z, rot_w, feature_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                frame.filename, frame.floor,
                frame.pos_x, frame.pos_y, frame.pos_z,
                frame.rot_x, frame.rot_y, frame.rot_z, frame.rot_w,
                frame.feature_path, frame.created_at,
            ),
        )
        self._conn.commit()
        frame.id = cur.lastrowid
        logger.debug(f"Inserted frame #{frame.id}: {frame.filename}")
        return frame.id

    def get_by_id(self, frame_id: int) -> Optional[ReferenceFrame]:
        """Fetch a single frame by its ID."""
        row = self._conn.execute(
            "SELECT * FROM frames WHERE id = ?", (frame_id,)
        ).fetchone()
        return self._row_to_frame(row) if row else None

    def get_by_filename(self, filename: str) -> Optional[ReferenceFrame]:
        """Fetch a single frame by filename."""
        row = self._conn.execute(
            "SELECT * FROM frames WHERE filename = ?", (filename,)
        ).fetchone()
        return self._row_to_frame(row) if row else None

    def get_all(self, floor: Optional[int] = None) -> list[ReferenceFrame]:
        """Fetch all frames, optionally filtered by floor."""
        if floor is not None:
            rows = self._conn.execute(
                "SELECT * FROM frames WHERE floor = ? ORDER BY id", (floor,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM frames ORDER BY id"
            ).fetchall()
        return [self._row_to_frame(r) for r in rows]

    def count(self, floor: Optional[int] = None) -> int:
        """Count frames, optionally filtered by floor."""
        if floor is not None:
            return self._conn.execute(
                "SELECT COUNT(*) FROM frames WHERE floor = ?", (floor,)
            ).fetchone()[0]
        return self._conn.execute("SELECT COUNT(*) FROM frames").fetchone()[0]

    def delete(self, frame_id: int) -> bool:
        """Delete a frame by ID. Returns True if a row was deleted."""
        cur = self._conn.execute("DELETE FROM frames WHERE id = ?", (frame_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def clear(self) -> int:
        """Delete all frames. Returns count of deleted rows."""
        cur = self._conn.execute("DELETE FROM frames")
        self._conn.commit()
        logger.warning(f"Cleared all reference frames ({cur.rowcount} deleted)")
        return cur.rowcount

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    @staticmethod
    def _row_to_frame(row: sqlite3.Row) -> ReferenceFrame:
        return ReferenceFrame(
            id=row["id"],
            filename=row["filename"],
            floor=row["floor"],
            pos_x=row["pos_x"],
            pos_y=row["pos_y"],
            pos_z=row["pos_z"],
            rot_x=row["rot_x"],
            rot_y=row["rot_y"],
            rot_z=row["rot_z"],
            rot_w=row["rot_w"],
            feature_path=row["feature_path"],
            created_at=row["created_at"],
        )
