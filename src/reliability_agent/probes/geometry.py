"""Field-of-view drift via ORB features + RANSAC similarity (4 DOF) against a reference bank.

The motion model is a similarity (`cv2.estimateAffinePartial2D`: translation, rotation, scale),
not a full 8-DOF homography: on a smooth scene `equalizeHist` turns sensor noise into hundreds of
spurious ORB keypoints, and a homography fitted through them still finds ~60 % "inliers" while its
translation estimate jitters by tens of pixels (SIMULATION, wall σ 0.7–4: p95 27–48 px, max 94 px,
rotation up to 3°), which met the `fov_shift` rule on a camera at rest. The rigid model cannot
bend to the noise (same scenes: p95 2.4–4.6 px, rotation ≤ 1°) and reports a real 40 px shift,
a 5° rotation or a slow pan within a pixel / a tenth of a degree. The metric keeps its contract
name `homography_inlier_ratio` (inlier share of the fitted model)."""

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
        H, mask = cv2.estimateAffinePartial2D(
            src, dst, method=cv2.RANSAC, ransacReprojThreshold=self.reproj_px
        )
        if H is None:
            return ProbeResult(
                "geometry", quality="failed", unknown_reason="motion model failed",
                values={"match_count": float(len(matches)), "homography_inlier_ratio": 0.0},
            )
        inliers = float(mask.sum()) / len(matches)
        return ProbeResult(
            "geometry",
            values={
                "match_count": float(len(matches)),
                "homography_inlier_ratio": inliers,
                "translation_px": float(math.hypot(H[0, 2], H[1, 2])),
                "rotation_deg": float(math.degrees(math.atan2(H[1, 0], H[0, 0]))),
            },
        )
