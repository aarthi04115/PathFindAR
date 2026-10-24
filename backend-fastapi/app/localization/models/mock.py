"""
Mock model implementations for development / testing.

These return plausible dummy data so the full localization pipeline
can run end-to-end without real model weights.
Swap in real implementations by subclassing the ABCs in base.py.
"""

from __future__ import annotations

import random
from typing import Any, Optional

from loguru import logger

from app.localization.models.base import (
    CandidateFrame,
    DescriptorMatcher,
    FeatureExtractor,
    Features,
    GlobalRetriever,
    Match,
    Matches,
    Pose,
    PoseEstimator,
)

try:
    import numpy as np
    _NP = True
except ImportError:
    _NP = False


# ── Mock Feature Extractor (SuperPoint stub) ──────────────────────────────────

class MockFeatureExtractor(FeatureExtractor):
    """
    Returns N random keypoints and zero-padded descriptors.
    Sufficient to exercise the matching and pose pipeline logic.
    """

    def __init__(self, n_keypoints: int = 64, descriptor_dim: int = 256):
        self.n_keypoints = n_keypoints
        self.descriptor_dim = descriptor_dim
        self._loaded = False

    def load(self, model_path: str) -> None:
        logger.info(f"MockFeatureExtractor: pretending to load from {model_path}")
        self._loaded = True

    def extract(self, grey_image: Any) -> Features:
        if _NP:
            h, w = (grey_image.shape[:2] if hasattr(grey_image, "shape")
                    else (480, 640))
            kps = np.random.rand(self.n_keypoints, 2) * np.array([w, h])
            descs = np.random.rand(self.n_keypoints, self.descriptor_dim).astype("float32")
            scores = np.random.rand(self.n_keypoints).astype("float32")
            return Features(keypoints=kps, descriptors=descs, scores=scores,
                            image_size=(w, h))
        # Fallback without numpy
        return Features(keypoints=[], descriptors=[], scores=[])


# ── Mock Descriptor Matcher (SuperGlue stub) ──────────────────────────────────

class MockDescriptorMatcher(DescriptorMatcher):
    """
    Returns a fixed number of random matches with mid-confidence.
    Always reports enough inliers to pass is_reliable.
    """

    def __init__(self, n_matches: int = 30):
        self.n_matches = n_matches
        self._loaded = False

    def load(self, model_path: str) -> None:
        logger.info(f"MockDescriptorMatcher: pretending to load from {model_path}")
        self._loaded = True

    def match(self, query: Features, reference: Features) -> Matches:
        n = min(self.n_matches,
                len(query.keypoints) if hasattr(query.keypoints, "__len__") else 0,
                len(reference.keypoints) if hasattr(reference.keypoints, "__len__") else 0)
        matches = [
            Match(kp_idx_a=i, kp_idx_b=i, confidence=random.uniform(0.5, 0.95))
            for i in range(n)
        ]
        return Matches(matches=matches, num_inliers=n)


# ── Mock Global Retriever (NetVLAD/FAISS stub) ────────────────────────────────

class MockGlobalRetriever(GlobalRetriever):
    """
    Returns a list of dummy candidate frames.
    Useful until a real reference frame database is built.
    """

    _DUMMY_FRAMES = [
        CandidateFrame("ref_001", 0.92, [1.0, 0.0, 2.0], [0.0, 0.0, 0.0, 1.0]),
        CandidateFrame("ref_002", 0.85, [3.0, 0.0, 2.0], [0.0, 0.0, 0.0, 1.0]),
        CandidateFrame("ref_003", 0.71, [5.0, 0.0, 5.0], [0.0, 0.1, 0.0, 1.0]),
    ]

    def build_index(self, frames_dir: str) -> None:
        logger.info(f"MockGlobalRetriever: skipping index build for {frames_dir}")

    def retrieve(self, grey_image: Any, top_k: int = 5) -> list[CandidateFrame]:
        return self._DUMMY_FRAMES[:top_k]


# ── Mock Pose Estimator (PnP stub) ────────────────────────────────────────────

class MockPoseEstimator(PoseEstimator):
    """
    Returns a trivially perturbed version of the reference pose.
    Confidence is always 0 to signal 'not a real estimate'.
    """

    def estimate(
        self,
        matches: Matches,
        query_features: Features,
        reference_features: Features,
        reference_pose: Pose,
        camera_matrix: Any,
    ) -> Optional[Pose]:
        if not matches.is_reliable:
            logger.debug("MockPoseEstimator: not enough inliers for pose")
            return None
        # Slightly perturb the reference pose
        pos = [p + random.uniform(-0.05, 0.05) for p in reference_pose.position]
        return Pose(
            position=pos,
            rotation=reference_pose.rotation,
            confidence=0.0,   # signals 'mock result'
            num_inliers=matches.num_inliers,
        )
