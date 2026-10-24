"""
Abstract base classes for localization model stages.

Using ABCs + dependency injection means:
  - Tests/dev use MockFeatureExtractor, MockMatcher, etc.
  - Production swaps in SuperPoint, SuperGlue, NetVLAD — zero endpoint changes.
  - Each stage is independently replaceable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Any


# ── Shared data types ─────────────────────────────────────────────────────────

@dataclass
class Features:
    """Keypoints + descriptors extracted from a single image frame."""
    keypoints: Any          # np.ndarray shape (N, 2) — (x, y) pixel coords
    descriptors: Any        # np.ndarray shape (N, D) — feature descriptors
    scores: Any             # np.ndarray shape (N,)   — confidence per keypoint
    image_size: tuple[int, int] = (0, 0)  # (W, H)


@dataclass
class Match:
    """A matched keypoint pair between two frames."""
    kp_idx_a: int           # index in Features A
    kp_idx_b: int           # index in Features B
    confidence: float = 1.0


@dataclass
class Matches:
    """Collection of keypoint matches between two frames."""
    matches: list[Match] = field(default_factory=list)
    num_inliers: int = 0

    @property
    def is_reliable(self) -> bool:
        return self.num_inliers >= 8   # minimum for PnP


@dataclass
class Pose:
    """6-DoF camera pose in world coordinates."""
    position: list[float]              # [x, y, z]
    rotation: list[float]              # [x, y, z, w] quaternion
    confidence: float = 0.0           # 0–1
    num_inliers: int = 0


@dataclass
class CandidateFrame:
    """A reference frame retrieved by global retrieval."""
    frame_id: str
    score: float                       # similarity score (higher = better)
    position: Optional[list[float]] = None
    rotation: Optional[list[float]] = None


# ── Abstract model interfaces ─────────────────────────────────────────────────

class FeatureExtractor(ABC):
    """
    Extracts local features (keypoints + descriptors) from a greyscale image.
    Implementation: SuperPoint, SIFT, ORB, etc.
    """

    @abstractmethod
    def extract(self, grey_image: Any) -> Features:
        """
        Args:
            grey_image: np.ndarray (H, W) greyscale uint8

        Returns:
            Features with keypoints, descriptors, and scores.
        """

    @abstractmethod
    def load(self, model_path: str) -> None:
        """Load model weights from disk."""


class DescriptorMatcher(ABC):
    """
    Matches features between a query and reference frame.
    Implementation: SuperGlue, NN-matcher, LightGlue, etc.
    """

    @abstractmethod
    def match(self, query: Features, reference: Features) -> Matches:
        """
        Args:
            query:     Features from the live camera frame.
            reference: Features from a stored reference frame.

        Returns:
            Matches including inlier count.
        """

    @abstractmethod
    def load(self, model_path: str) -> None:
        """Load model weights from disk."""


class GlobalRetriever(ABC):
    """
    Retrieves the top-K most similar reference frames given a query image.
    Implementation: NetVLAD + FAISS, HF-Net, DINOv2, etc.
    """

    @abstractmethod
    def retrieve(self, grey_image: Any, top_k: int = 5) -> list[CandidateFrame]:
        """
        Args:
            grey_image: np.ndarray (H, W) greyscale uint8
            top_k:      Number of candidates to return.

        Returns:
            Ranked list of CandidateFrames (best first).
        """

    @abstractmethod
    def build_index(self, frames_dir: str) -> None:
        """Build / load FAISS index from reference frame database."""


class PoseEstimator(ABC):
    """
    Estimates 6-DoF camera pose from 2D–3D correspondences.
    Implementation: PnP + RANSAC via OpenCV.
    """

    @abstractmethod
    def estimate(
        self,
        matches: Matches,
        query_features: Features,
        reference_features: Features,
        reference_pose: Pose,
        camera_matrix: Any,  # np.ndarray (3,3)
    ) -> Optional[Pose]:
        """
        Returns refined Pose or None if estimation fails.
        """
