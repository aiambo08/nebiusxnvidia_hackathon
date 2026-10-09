"""Field-of-view drift via ORB features against a reference bank (ADR-006).

Two RANSAC fits over the same cross-checked matches:
- an 8-DOF homography supplies `homography_inlier_ratio`, the measurement-quality gate the
  `fov_shift` rule was calibrated on (a 10–15° yaw/tilt of a real camera is a perspective
  change that a rigid model fits poorly: similarity inliers fall to 0.2–0.3);
- a 4-DOF similarity (`cv2.estimateAffinePartial2D`) supplies `translation_px` and
  `rotation_deg`: on a smooth scene `equalizeHist` turns sensor noise into hundreds of spurious
  keypoints and the homography bends to them (SIMULATION, wall σ 0.7–4 at rest: translation
  p95 27–48 px, max 94 px, rotation up to 3°, i.e. a false `fov_shift`), while the rigid model
  cannot (p95 2.4–4.6 px, ≤ 1°) and still reports real shifts, rotations and slow pans.
`translation_px` is the displacement of the image origin (`H[:, 2]`), so an in-plane rotation
about the centre also contributes to it."""

from __future__ import annotations

import math

import cv2
import numpy as np

from reliability_agent.probes.base import ProbeResult


class GeometryProbe:
    def __init__(self, n_features: int = 500, min_matches: int = 12, reproj_px: float = 5.0):
        self.orb = cv2.ORB_create(nfeatures=n_features)
        self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        self.min_matches = min_matches
        self.reproj_px = reproj_px
        self._refs: list[tuple[list, np.ndarray]] = []

    def set_reference(self, gray: np.ndarray, *, append: bool = False, max_refs: int = 4) -> bool:
        kp, des = self.orb.detectAndCompute(gray, None)
        if des is None or len(kp) < self.min_matches:
            return False
        if not append:
            self._refs.clear()
        self._refs.append((kp, des))
        del self._refs[:-max_refs]
        return True

    @property
    def has_reference(self) -> bool:
        return bool(self._refs)

    def measure(self, gray: np.ndarray) -> ProbeResult:
        if not self._refs:
            return ProbeResult("geometry", quality="no_reference", unknown_reason="no reference")
        kp, des = self.orb.detectAndCompute(gray, None)
        if des is None or len(kp) < self.min_matches:
            return ProbeResult(
                "geometry", quality="low_texture", unknown_reason="too few keypoints",
                values={"match_count": float(0 if des is None else len(kp))},
            )
        best: ProbeResult | None = None
        for rkp, rdes in self._refs:  # best-matching reference (multi-reference bank)
            res = self._against(kp, des, rkp, rdes)
            if best is None or res.values.get("homography_inlier_ratio", 0) > best.values.get(
                "homography_inlier_ratio", 0
            ):
                best = res
        assert best is not None
        return best

    def _against(self, kp, des, rkp, rdes) -> ProbeResult:
        matches = self.matcher.match(rdes, des)
        if len(matches) < self.min_matches:
            return ProbeResult(
                "geometry", quality="failed", unknown_reason="not enough matches",
                values={"match_count": float(len(matches)), "homography_inlier_ratio": 0.0},
            )
        src = np.float32([rkp[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
        dst = np.float32([kp[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)
        H, mask = cv2.findHomography(src, dst, cv2.RANSAC, self.reproj_px)
        if H is None:
            return ProbeResult(
                "geometry", quality="failed", unknown_reason="homography failed",
                values={"match_count": float(len(matches)), "homography_inlier_ratio": 0.0},
            )
        motion, _ = cv2.estimateAffinePartial2D(
            src, dst, method=cv2.RANSAC, ransacReprojThreshold=self.reproj_px
        )
        if motion is None:  # never fall back to the homography's motion: on a wall it is the noise
            return ProbeResult(
                "geometry", quality="failed", unknown_reason="rigid motion fit failed",
                values={"match_count": float(len(matches)),
                        "homography_inlier_ratio": float(mask.sum()) / len(matches)},
            )
        inliers = float(mask.sum()) / len(matches)
        return ProbeResult(
            "geometry",
            values={
                "match_count": float(len(matches)),
                "homography_inlier_ratio": inliers,
                "translation_px": float(math.hypot(motion[0, 2], motion[1, 2])),
                "rotation_deg": float(math.degrees(math.atan2(motion[1, 0], motion[0, 0]))),
            },
        )
