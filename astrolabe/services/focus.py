from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import numpy as np


@dataclass(frozen=True)
class FocusConfig:
    detection_sigma: float = 5.0
    min_stars: int = 3
    aperture_radius_px: int = 8
    min_separation_px: float = 5.0
    blend_radius_px: float = 5.0
    min_footprint_pixels: int = 4
    max_elongation: float = 2.5
    saturation_level: float | None = None
    saturation_fraction: float = 0.98

    def __post_init__(self) -> None:
        if self.detection_sigma <= 0:
            raise ValueError("detection_sigma must be positive")
        if self.min_stars < 1:
            raise ValueError("min_stars must be at least 1")
        if self.aperture_radius_px < 2:
            raise ValueError("aperture_radius_px must be at least 2")
        if self.min_separation_px < 0 or self.blend_radius_px < 0:
            raise ValueError("separation radii must be non-negative")
        if self.min_footprint_pixels < 1:
            raise ValueError("min_footprint_pixels must be at least 1")
        if self.max_elongation < 1:
            raise ValueError("max_elongation must be at least 1")
        if self.saturation_level is not None and (
            not math.isfinite(self.saturation_level) or self.saturation_level <= 0
        ):
            raise ValueError("saturation_level must be a positive finite value")
        if not 0 < self.saturation_fraction <= 1:
            raise ValueError("saturation_fraction must be in (0, 1]")


@dataclass(frozen=True)
class FocusMeasurement:
    valid: bool
    hfr_px: float | None
    hfr_mad_px: float | None
    star_count: int
    rejected_star_count: int
    background: float | None
    noise_sigma: float | None
    message: str | None = None


@dataclass(frozen=True)
class _StarMeasurement:
    x: float
    y: float
    hfr_px: float


def _robust_sigma(values: np.ndarray, median: float) -> float:
    mad = float(np.median(np.abs(values - median)))
    return 1.4826 * mad


def _effective_noise(
    noise_sigma: float,
    pixels: np.ndarray,
    background: float,
    *,
    integer_pixels: bool,
) -> float:
    if noise_sigma > 0 and math.isfinite(noise_sigma):
        return noise_sigma
    peak = float(np.max(pixels))
    span = max(peak - background, 0.0)
    quantization_floor = 1.0 if integer_pixels else 0.0
    return max(
        quantization_floor,
        span * 1e-6,
        abs(background) * 1e-9,
        1e-12,
    )


def _local_maxima(pixels: np.ndarray, threshold: float) -> list[tuple[int, int, float]]:
    center = pixels[1:-1, 1:-1]
    mask = center > threshold
    neighbors = (
        pixels[:-2, :-2],
        pixels[:-2, 1:-1],
        pixels[:-2, 2:],
        pixels[1:-1, :-2],
        pixels[1:-1, 2:],
        pixels[2:, :-2],
        pixels[2:, 1:-1],
        pixels[2:, 2:],
    )
    for neighbor in neighbors:
        mask &= center >= neighbor
    ys, xs = np.nonzero(mask)
    candidates = [
        (int(y + 1), int(x + 1), float(pixels[y + 1, x + 1])) for y, x in zip(ys, xs)
    ]
    candidates.sort(key=lambda item: item[2], reverse=True)
    return candidates


def _suppress_close(
    candidates: list[tuple[int, int, float]], min_separation_px: float
) -> list[tuple[int, int, float]]:
    if min_separation_px <= 0:
        return candidates
    keep: list[tuple[int, int, float]] = []
    limit2 = min_separation_px * min_separation_px
    for candidate in candidates:
        y, x, _ = candidate
        if all(
            (y - kept_y) ** 2 + (x - kept_x) ** 2 > limit2 for kept_y, kept_x, _ in keep
        ):
            keep.append(candidate)
    return keep


def _inferred_saturation_level(
    original: np.ndarray, configured: float | None
) -> float | None:
    if configured is not None:
        return configured
    if np.issubdtype(original.dtype, np.integer):
        return float(np.iinfo(original.dtype).max)
    return None


def _measure_star(
    pixels: np.ndarray,
    y: int,
    x: int,
    peak: float,
    noise_sigma: float,
    saturation_level: float | None,
    config: FocusConfig,
) -> _StarMeasurement | None:
    radius = config.aperture_radius_px
    height, width = pixels.shape
    if x < radius or y < radius or x >= width - radius or y >= height - radius:
        return None
    if (
        saturation_level is not None
        and peak >= saturation_level * config.saturation_fraction
    ):
        return None

    patch = pixels[y - radius : y + radius + 1, x - radius : x + radius + 1]
    border = np.concatenate(
        (patch[0, :], patch[-1, :], patch[1:-1, 0], patch[1:-1, -1])
    )
    local_background = float(np.median(border))
    signal = np.clip(patch - local_background, 0.0, None)
    total_flux = float(np.sum(signal))
    if total_flux <= 0 or not math.isfinite(total_flux):
        return None

    peak_signal = max(peak - local_background, 0.0)
    footprint_threshold = max(3.0 * noise_sigma, 0.05 * peak_signal)
    footprint = signal > footprint_threshold
    if int(np.count_nonzero(footprint)) < config.min_footprint_pixels:
        return None

    yy, xx = np.indices(patch.shape, dtype=float)
    cx = float(np.sum(signal * xx) / total_flux)
    cy = float(np.sum(signal * yy) / total_flux)

    shape_weights = np.where(signal >= 0.05 * peak_signal, signal, 0.0)
    shape_flux = float(np.sum(shape_weights))
    if shape_flux <= 0:
        return None
    dx = xx - cx
    dy = yy - cy
    mxx = float(np.sum(shape_weights * dx * dx) / shape_flux)
    myy = float(np.sum(shape_weights * dy * dy) / shape_flux)
    mxy = float(np.sum(shape_weights * dx * dy) / shape_flux)
    trace = mxx + myy
    disc = math.sqrt(max((mxx - myy) ** 2 + 4.0 * mxy * mxy, 0.0))
    lambda_max = 0.5 * (trace + disc)
    lambda_min = 0.5 * (trace - disc)
    if lambda_min <= 1e-6:
        return None
    elongation = math.sqrt(lambda_max / lambda_min)
    if elongation > config.max_elongation:
        return None

    distances = np.sqrt(dx * dx + dy * dy).ravel()
    fluxes = signal.ravel()
    order = np.argsort(distances)
    distances = distances[order]
    fluxes = fluxes[order]
    cumulative = np.cumsum(fluxes)
    half_flux = 0.5 * cumulative[-1]
    idx = int(np.searchsorted(cumulative, half_flux, side="left"))
    if idx == 0:
        hfr = float(distances[0])
    else:
        f0 = float(cumulative[idx - 1])
        f1 = float(cumulative[idx])
        r0 = float(distances[idx - 1])
        r1 = float(distances[idx])
        if f1 <= f0 or r1 <= r0:
            hfr = r1
        else:
            hfr = r0 + (half_flux - f0) * (r1 - r0) / (f1 - f0)
    if not math.isfinite(hfr) or hfr <= 0:
        return None
    return _StarMeasurement(
        x=x - radius + cx,
        y=y - radius + cy,
        hfr_px=hfr,
    )


class FocusAnalyzer:
    def __init__(self, config: FocusConfig | None = None):
        self.config = config or FocusConfig()

    def measure(
        self, frame: Any, *, saturation_level: float | None = None
    ) -> FocusMeasurement:
        original = np.asarray(frame)
        if original.ndim != 2 or original.size == 0:
            return FocusMeasurement(
                False,
                None,
                None,
                0,
                0,
                None,
                None,
                "focus frame must be a non-empty 2D monochrome array",
            )
        if not np.issubdtype(original.dtype, np.number):
            return FocusMeasurement(
                False,
                None,
                None,
                0,
                0,
                None,
                None,
                "focus frame must contain numeric pixels",
            )
        pixels = original.astype(np.float64, copy=False)
        if not np.all(np.isfinite(pixels)):
            return FocusMeasurement(
                False,
                None,
                None,
                0,
                0,
                None,
                None,
                "focus frame contains non-finite pixels",
            )

        background = float(np.median(pixels))
        noise_sigma = _robust_sigma(pixels, background)
        effective_noise = _effective_noise(
            noise_sigma,
            pixels,
            background,
            integer_pixels=np.issubdtype(original.dtype, np.integer),
        )
        threshold = background + self.config.detection_sigma * effective_noise
        raw_candidates = _local_maxima(pixels, threshold)
        candidates = _suppress_close(raw_candidates, self.config.min_separation_px)
        configured_saturation = self.config.saturation_level
        inferred_saturation = _inferred_saturation_level(
            original,
            configured_saturation
            if configured_saturation is not None
            else saturation_level,
        )

        accepted: list[_StarMeasurement] = []
        rejected = len(raw_candidates) - len(candidates)
        for y, x, peak in candidates:
            if self.config.blend_radius_px > 0:
                blend2 = self.config.blend_radius_px**2
                if any(
                    (y - other_y) ** 2 + (x - other_x) ** 2 <= blend2
                    and other_peak >= 0.25 * peak
                    for other_y, other_x, other_peak in raw_candidates
                    if other_y != y or other_x != x
                ):
                    rejected += 1
                    continue
            star = _measure_star(
                pixels,
                y,
                x,
                peak,
                effective_noise,
                inferred_saturation,
                self.config,
            )
            if star is None:
                rejected += 1
            else:
                accepted.append(star)

        if len(accepted) < self.config.min_stars:
            return FocusMeasurement(
                valid=False,
                hfr_px=None,
                hfr_mad_px=None,
                star_count=len(accepted),
                rejected_star_count=rejected,
                background=background,
                noise_sigma=noise_sigma,
                message=(
                    f"need at least {self.config.min_stars} usable stars; "
                    f"found {len(accepted)}"
                ),
            )

        hfr_values = np.array([star.hfr_px for star in accepted], dtype=float)
        median_hfr = float(np.median(hfr_values))
        hfr_mad = float(np.median(np.abs(hfr_values - median_hfr)))
        return FocusMeasurement(
            valid=True,
            hfr_px=median_hfr,
            hfr_mad_px=hfr_mad,
            star_count=len(accepted),
            rejected_star_count=rejected,
            background=background,
            noise_sigma=noise_sigma,
        )


class FocusService:
    """Backend-agnostic focus orchestration over Astrolabe Image objects."""

    def __init__(self, camera_backend=None, analyzer: FocusAnalyzer | None = None):
        self._camera = camera_backend
        self._analyzer = analyzer or FocusAnalyzer()

    def measure_pixels(
        self, pixels: Any, *, saturation_level: float | None = None
    ) -> FocusMeasurement:
        return self._analyzer.measure(pixels, saturation_level=saturation_level)

    def measure_image(self, image) -> FocusMeasurement:
        from astrolabe.camera.pixels import image_to_pixels

        frame = image_to_pixels(image)
        return self._analyzer.measure(
            frame.pixels,
            saturation_level=frame.saturation_level,
        )

    def capture_and_measure(
        self,
        exposure_s: float,
        gain: float | None = None,
        binning: int | None = None,
        roi: tuple[int, int, int, int] | None = None,
    ) -> FocusMeasurement:
        if self._camera is None:
            raise RuntimeError("capture_and_measure requires a camera backend")
        image = self._camera.capture(
            exposure_s=exposure_s,
            gain=gain,
            binning=binning,
            roi=roi,
        )
        return self.measure_image(image)
