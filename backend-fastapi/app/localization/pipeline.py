"""
Localization Pipeline Orchestrator

Full pipeline (mock-ready, real-model-ready):
  Frame (base64)
    → Preprocessing (blur check, resize)
    → GlobalRetriever (NetVLAD/FAISS) — top-K candidate frames
    → FeatureExtractor (SuperPoint) — keypoints for query + candidate
    → DescriptorMatcher (SuperGlue) — match keypoints
    → PoseEstimator (PnP + RANSAC) — 6-DoF pose
    → Map snap (nearest node from IndoorNavigator)

All model stages are injected via constructor (Strategy pattern).
Default: mock models. Swap by passing real implementations.
"""

from __future__ import annotations

from typing import Optional

from loguru import logger

from app.core.config import settings
from app.localization.models.base import (
    DescriptorMatcher,
    FeatureExtractor,
    GlobalRetriever,
    Pose,
    PoseEstimator,
)
from app.localization.models.mock import (
    MockDescriptorMatcher,
    MockFeatureExtractor,
    MockGlobalRetriever,
    MockPoseEstimator,
)
from app.localization.preprocessing import preprocess


class LocalizationPipeline:
    """
    Full localization pipeline with injectable model stages.

    Usage (mock, works out of the box):
        pipeline = LocalizationPipeline()
        pipeline.load_models()
        result = pipeline.localize(frame_bytes, arcore_pose)

    Usage (real models):
        pipeline = LocalizationPipeline(
            extractor=SuperPointExtractor(),
            matcher=SuperGlueMatcher(),
            retriever=NetVLADRetriever(),
            pose_estimator=PnPEstimator(),
        )
        pipeline.load_models()
    """

    def __init__(
        self,
        extractor: Optional[FeatureExtractor] = None,
        matcher: Optional[DescriptorMatcher] = None,
        retriever: Optional[GlobalRetriever] = None,
        pose_estimator: Optional[PoseEstimator] = None,
    ):
        self.extractor = extractor or MockFeatureExtractor(
            n_keypoints=settings.MAX_KEYPOINTS
        )
        self.matcher = matcher or MockDescriptorMatcher()
        self.retriever = retriever or MockGlobalRetriever()
        self.pose_estimator = pose_estimator or MockPoseEstimator()
        self.is_loaded: bool = False
        logger.info(
            f"LocalizationPipeline created — "
            f"extractor={type(self.extractor).__name__}, "
            f"matcher={type(self.matcher).__name__}, "
            f"retriever={type(self.retriever).__name__}"
        )

    def load_models(self) -> None:
        """Load / initialise all model stages."""
        model_dir = settings.MODEL_PATH
        self.extractor.load(f"{model_dir}/{settings.SUPERPOINT_MODEL}")
        self.matcher.load(f"{model_dir}/{settings.SUPERGLUE_MODEL}")
        self.retriever.build_index(settings.DATA_PATH)
        self.is_loaded = True
        logger.info("LocalizationPipeline models ready")

    def localize(self, image_base64: str, arcore_pose: dict) -> dict:
        """
        Main entry point — localize from a base64 camera frame.

        Args:
            image_base64: Base64-encoded JPG from Unity.
            arcore_pose:  {"position": [x,y,z], "rotation": [x,y,z,w]}

        Returns:
            {
              "position": [x, y, z],
              "rotation": [x, y, z, w],
              "confidence": float,       # 0 = passthrough; 1 = fully corrected
              "nearest_node_id": str | None,
              "blur_score": float,
            }
        """
        # ── 1. Preprocess frame ──────────────────────────────────────────────
        prep = preprocess(
            image_base64,
            max_size=settings.FRAME_MAX_SIZE,
            blur_threshold=settings.BLUR_THRESHOLD,
        )
        if not prep.ok:
            logger.debug(f"Preprocessing failed: {prep.error} — passthrough")
            return self._passthrough(arcore_pose, blur_score=prep.blur_score,
                                     note=prep.error)

        # ── 2. Global retrieval — top candidate frames ───────────────────────
        candidates = self.retriever.retrieve(prep.grey, top_k=5)
        if not candidates:
            logger.debug("No retrieval candidates — passthrough")
            return self._passthrough(arcore_pose, blur_score=prep.blur_score)

        best_candidate = candidates[0]

        # ── 3. Feature extraction — query ────────────────────────────────────
        query_features = self.extractor.extract(prep.grey)

        # ── 4. Feature extraction — reference (mock reuses same extractor) ───
        ref_features = self.extractor.extract(prep.grey)  # placeholder

        # ── 5. Descriptor matching ───────────────────────────────────────────
        matches = self.matcher.match(query_features, ref_features)
        if not matches.is_reliable:
            logger.debug(f"Too few inliers ({matches.num_inliers}) — passthrough")
            return self._passthrough(arcore_pose, blur_score=prep.blur_score)

        # ── 6. Pose estimation ───────────────────────────────────────────────
        ref_pose = Pose(
            position=best_candidate.position or [0.0, 0.0, 0.0],
            rotation=best_candidate.rotation or [0.0, 0.0, 0.0, 1.0],
        )
        estimated = self.pose_estimator.estimate(
            matches=matches,
            query_features=query_features,
            reference_features=ref_features,
            reference_pose=ref_pose,
            camera_matrix=None,  # TODO: pass real camera intrinsics
        )

        if estimated is None or estimated.confidence < settings.POSE_CONFIDENCE_THRESHOLD:
            logger.debug("Pose estimate below confidence threshold — passthrough")
            return self._passthrough(arcore_pose, blur_score=prep.blur_score)

        # ── 7. Map snap ──────────────────────────────────────────────────────
        nearest_node_id = self._snap_to_map(estimated.position)

        logger.info(
            f"Localized: pos={[round(p, 3) for p in estimated.position]}, "
            f"conf={estimated.confidence:.2f}, node={nearest_node_id}"
        )
        return {
            "position": estimated.position,
            "rotation": estimated.rotation,
            "confidence": estimated.confidence,
            "nearest_node_id": nearest_node_id,
            "blur_score": prep.blur_score,
        }

    # ── Private helpers ──────────────────────────────────────────────────────

    def _passthrough(
        self,
        arcore_pose: dict,
        blur_score: float = 0.0,
        note: Optional[str] = None,
    ) -> dict:
        """Return ARCore pose unchanged (no backend correction)."""
        return {
            "position": arcore_pose["position"],
            "rotation": arcore_pose["rotation"],
            "confidence": 0.0,
            "nearest_node_id": None,
            "blur_score": blur_score,
            "_passthrough_reason": note,
        }

    def _snap_to_map(self, position: list[float]) -> Optional[str]:
        """Find nearest graph node to estimated position."""
        try:
            from app.core import state
            if state.navigator.is_loaded:
                return state.navigator.get_nearest_node(position)
        except Exception as exc:
            logger.debug(f"Map snap failed: {exc}")
        return None
