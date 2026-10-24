"""
Pose Smoother — Exponential Moving Average + Kalman-lite filter.

Prevents jitter in AR by smoothing the corrected pose over time.
Instead of snapping to each new ML estimate, this blends the new pose
with the recent history to produce a stable, natural-feeling output.

Two modes:
  - EMA (Exponential Moving Average): Simple, fast, good enough for most cases.
    New = α * measurement + (1 - α) * previous
  - Adaptive: Adjusts smoothing factor based on confidence.
    High confidence → trust the new measurement more (lower smoothing).
    Low confidence → lean on the previous pose (higher smoothing).

Usage:
    smoother = PoseSmoother(alpha=0.3)
    smoothed = smoother.update(position=[1.0, 0.5, 2.0],
                                rotation=[0, 0, 0, 1],
                                confidence=0.8)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger


@dataclass
class SmoothedPose:
    """Output of the pose smoother."""
    position: list[float]
    rotation: list[float]
    confidence: float
    raw_position: list[float]    # unsmoothed input
    raw_rotation: list[float]    # unsmoothed input
    smoothing_applied: float     # effective alpha used


class PoseSmoother:
    """
    Smooths 6-DoF poses over time using adaptive EMA.

    Args:
        alpha:          Base smoothing factor (0 = no smoothing, 1 = no history).
                        0.3 is a good default for 10-15 FPS localization.
        confidence_weight: How much confidence affects alpha.
                        Higher = more aggressive trust of high-conf estimates.
        min_alpha:      Floor for alpha (always trust new data at least this much).
        max_alpha:      Ceiling for alpha.
        velocity_threshold: If position jumps more than this (meters), treat as
                        teleport and reset (don't smooth across floor changes).
    """

    def __init__(
        self,
        alpha: float = 0.3,
        confidence_weight: float = 0.5,
        min_alpha: float = 0.1,
        max_alpha: float = 0.9,
        velocity_threshold: float = 5.0,
    ):
        self.base_alpha = alpha
        self.confidence_weight = confidence_weight
        self.min_alpha = min_alpha
        self.max_alpha = max_alpha
        self.velocity_threshold = velocity_threshold

        self._prev_position: Optional[list[float]] = None
        self._prev_rotation: Optional[list[float]] = None
        self._frame_count: int = 0

        logger.debug(
            f"PoseSmoother created: alpha={alpha}, "
            f"conf_weight={confidence_weight}, "
            f"velocity_threshold={velocity_threshold}m"
        )

    def update(
        self,
        position: list[float],
        rotation: list[float],
        confidence: float = 0.5,
    ) -> SmoothedPose:
        """
        Feed a new pose estimate and get back a smoothed pose.

        Args:
            position:   [x, y, z] world coordinates
            rotation:   [x, y, z, w] quaternion
            confidence: 0.0 = ARCore passthrough, 1.0 = high-confidence ML

        Returns:
            SmoothedPose with blended position/rotation
        """
        self._frame_count += 1

        # First frame — no history to blend with
        if self._prev_position is None:
            self._prev_position = list(position)
            self._prev_rotation = list(rotation)
            return SmoothedPose(
                position=list(position),
                rotation=list(rotation),
                confidence=confidence,
                raw_position=list(position),
                raw_rotation=list(rotation),
                smoothing_applied=1.0,
            )

        # Check for teleport (large position jump → reset smoother)
        dist = self._distance(position, self._prev_position)
        if dist > self.velocity_threshold:
            logger.debug(
                f"Teleport detected ({dist:.2f}m > {self.velocity_threshold}m) "
                f"— resetting smoother"
            )
            self._prev_position = list(position)
            self._prev_rotation = list(rotation)
            return SmoothedPose(
                position=list(position),
                rotation=list(rotation),
                confidence=confidence,
                raw_position=list(position),
                raw_rotation=list(rotation),
                smoothing_applied=1.0,
            )

        # Adaptive alpha: higher confidence → trust new measurement more
        alpha = self.base_alpha + self.confidence_weight * confidence
        alpha = max(self.min_alpha, min(self.max_alpha, alpha))

        # EMA blend position
        smoothed_pos = [
            alpha * p_new + (1 - alpha) * p_old
            for p_new, p_old in zip(position, self._prev_position)
        ]

        # SLERP-lite for quaternion (linear interpolation + normalize)
        smoothed_rot = self._lerp_quaternion(
            self._prev_rotation, rotation, alpha
        )

        self._prev_position = smoothed_pos
        self._prev_rotation = smoothed_rot

        return SmoothedPose(
            position=smoothed_pos,
            rotation=smoothed_rot,
            confidence=confidence,
            raw_position=list(position),
            raw_rotation=list(rotation),
            smoothing_applied=alpha,
        )

    def reset(self) -> None:
        """Clear smoother state (e.g. on floor change or session restart)."""
        self._prev_position = None
        self._prev_rotation = None
        self._frame_count = 0
        logger.debug("PoseSmoother reset")

    @property
    def frame_count(self) -> int:
        return self._frame_count

    # ── Math helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _distance(a: list[float], b: list[float]) -> float:
        """Euclidean distance between two 3D points."""
        return math.sqrt(sum((ai - bi) ** 2 for ai, bi in zip(a, b)))

    @staticmethod
    def _lerp_quaternion(
        q1: list[float], q2: list[float], t: float
    ) -> list[float]:
        """
        Linear interpolation between two quaternions, then normalize.

        Not a true SLERP, but for small angular differences (typical in
        frame-to-frame localization) it's visually indistinguishable
        and much cheaper.
        """
        # Ensure shortest path (dot product check)
        dot = sum(a * b for a, b in zip(q1, q2))
        if dot < 0:
            q2 = [-x for x in q2]

        result = [
            (1 - t) * a + t * b
            for a, b in zip(q1, q2)
        ]

        # Normalize
        norm = math.sqrt(sum(x * x for x in result))
        if norm < 1e-10:
            return [0.0, 0.0, 0.0, 1.0]
        return [x / norm for x in result]
