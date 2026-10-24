"""
Reference Frame Ingestion Engine.

Handles the full workflow of adding a new reference image to the system:
  1. Decode base64 image → save as JPG to disk
  2. Pre-compute ML features (via FeatureExtractor)
  3. Store metadata in SQLite
  4. Notify GlobalRetriever to rebuild FAISS index

Can be called from:
  - API endpoint (single-frame upload from Unity mapping mode)
  - CLI script (bulk ingestion from folder + CSV)
"""

from __future__ import annotations

import base64
import hashlib
import time
from pathlib import Path
from typing import Optional

import numpy as np
from loguru import logger

from app.localization.storage import ReferenceFrame, ReferenceFrameStore


class IngestionEngine:
    """
    Ingests reference images into the localization database.

    Args:
        store:      SQLite reference frame store
        image_dir:  Directory to save raw reference images
        feature_dir: Directory to save pre-computed feature vectors (.npz)
    """

    def __init__(
        self,
        store: ReferenceFrameStore,
        image_dir: str | Path = "data/reference_images",
        feature_dir: str | Path = "data/reference_features",
    ):
        self.store = store
        self.image_dir = Path(image_dir)
        self.feature_dir = Path(feature_dir)
        self.image_dir.mkdir(parents=True, exist_ok=True)
        self.feature_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            f"IngestionEngine ready — images: {self.image_dir}, "
            f"features: {self.feature_dir}"
        )

    def ingest_base64(
        self,
        image_base64: str,
        position: list[float],
        rotation: list[float],
        floor: int = 0,
        filename: Optional[str] = None,
    ) -> ReferenceFrame:
        """
        Ingest a single reference frame from base64-encoded image data.

        Args:
            image_base64: Base64-encoded JPG/PNG image
            position:     [x, y, z] world coordinates
            rotation:     [x, y, z, w] quaternion
            floor:        Floor index
            filename:     Optional custom filename (auto-generated if not provided)

        Returns:
            The created ReferenceFrame with its database ID
        """
        t0 = time.perf_counter()

        # ── 1. Decode image ──────────────────────────────────────────
        try:
            image_bytes = base64.b64decode(image_base64)
        except Exception as exc:
            raise ValueError(f"Invalid base64 image data: {exc}")

        if len(image_bytes) < 100:
            raise ValueError(
                f"Image data too small ({len(image_bytes)} bytes) — likely not a real image"
            )

        # ── 2. Generate filename from content hash ───────────────────
        if not filename:
            content_hash = hashlib.md5(image_bytes).hexdigest()[:12]
            filename = f"ref_{floor}_{content_hash}.jpg"

        # ── 3. Save image to disk ────────────────────────────────────
        image_path = self.image_dir / filename
        image_path.write_bytes(image_bytes)

        # ── 4. Pre-compute features (stub — writes dummy .npz) ──────
        feature_filename = Path(filename).stem + ".npz"
        feature_path = self.feature_dir / feature_filename
        self._extract_and_save_features(image_bytes, feature_path)

        # ── 5. Store metadata in SQLite ──────────────────────────────
        frame = ReferenceFrame(
            filename=filename,
            floor=floor,
            pos_x=position[0],
            pos_y=position[1],
            pos_z=position[2],
            rot_x=rotation[0],
            rot_y=rotation[1],
            rot_z=rotation[2],
            rot_w=rotation[3] if len(rotation) > 3 else 1.0,
            feature_path=str(feature_path),
            created_at=time.time(),
        )
        self.store.insert(frame)

        elapsed = (time.perf_counter() - t0) * 1000
        logger.info(
            f"Ingested frame #{frame.id}: {filename} "
            f"floor={floor} pos={position} ({elapsed:.1f}ms)"
        )
        return frame

    def ingest_file(
        self,
        image_path: str | Path,
        position: list[float],
        rotation: list[float],
        floor: int = 0,
    ) -> ReferenceFrame:
        """
        Ingest a reference frame from a file on disk.
        Used by the bulk ingestion CLI script.
        """
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        image_bytes = image_path.read_bytes()
        image_b64 = base64.b64encode(image_bytes).decode("ascii")
        return self.ingest_base64(
            image_base64=image_b64,
            position=position,
            rotation=rotation,
            floor=floor,
            filename=image_path.name,
        )

    def _extract_and_save_features(
        self, image_bytes: bytes, output_path: Path
    ) -> None:
        """
        Extract ML features and save as .npz.

        Currently writes a dummy feature vector. When real SuperPoint
        is wired in, this will call self.extractor.extract() and save
        the keypoints + descriptors.
        """
        # Dummy features for now — 256-dim random vector
        dummy_descriptors = np.random.randn(100, 256).astype(np.float32)
        dummy_keypoints = np.random.rand(100, 2).astype(np.float32) * 640
        np.savez_compressed(
            str(output_path),
            descriptors=dummy_descriptors,
            keypoints=dummy_keypoints,
        )

    @property
    def stats(self) -> dict:
        """Return ingestion stats for the API."""
        return {
            "total_frames": self.store.count(),
            "image_dir": str(self.image_dir),
            "feature_dir": str(self.feature_dir),
            "images_on_disk": len(list(self.image_dir.glob("*.jpg")))
                              + len(list(self.image_dir.glob("*.png"))),
        }
