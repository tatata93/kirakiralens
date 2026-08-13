from __future__ import annotations

from typing import Iterable

import numpy as np
import optiland.backend as be


DEFAULT_PUPIL_SAMPLES = (0.25, 0.5, 0.75, 1.0)


def longitudinal_aberration_metrics(
    system,
    wavelengths: Iterable[float],
    wavelength_weights: Iterable[float],
    primary_wavelength: float,
    pupil_samples: Iterable[float] = DEFAULT_PUPIL_SAMPLES,
) -> dict[str, float]:
    waves = [float(value) for value in wavelengths]
    if not waves:
        raise ValueError("At least one wavelength is required")
    pupils = np.asarray(list(pupil_samples), dtype=float)
    if pupils.size == 0 or np.any(pupils <= 0) or np.any(pupils > 1):
        raise ValueError("Pupil samples must be in the range (0, 1]")
    weights = _normalized_weights(wavelength_weights, len(waves))

    paraxial_intercepts = {}
    for wavelength in waves:
        ray = system.trace_generic(Hx=0, Hy=0, Px=0, Py=1e-4, wavelength=wavelength)
        paraxial_intercepts[wavelength] = float(_axial_intercepts(ray)[0])
    primary = min(waves, key=lambda value: abs(value - float(primary_wavelength)))
    common_reference = paraxial_intercepts[primary]

    weighted_mean_square = 0.0
    maximum_shift = 0.0
    primary_marginal = 0.0
    for wavelength, weight in zip(waves, weights, strict=True):
        rays = system.trace_generic(
            Hx=np.zeros_like(pupils),
            Hy=np.zeros_like(pupils),
            Px=np.zeros_like(pupils),
            Py=pupils,
            wavelength=wavelength,
        )
        shifts = _axial_intercepts(rays) - common_reference
        weighted_mean_square += weight * float(np.mean(shifts**2))
        maximum_shift = max(maximum_shift, float(np.max(np.abs(shifts))))
        if wavelength == primary:
            primary_marginal = abs(float(shifts[-1]))

    axial_color = max(paraxial_intercepts.values()) - min(paraxial_intercepts.values())
    return {
        "rms_um": float(np.sqrt(weighted_mean_square) * 1000.0),
        "maximum_abs_um": maximum_shift * 1000.0,
        "primary_lsa_um": primary_marginal * 1000.0,
        "axial_color_um": float(axial_color * 1000.0),
    }


def _axial_intercepts(rays) -> np.ndarray:
    y = np.asarray(be.to_numpy(rays.y), dtype=float).ravel()
    m = np.asarray(be.to_numpy(rays.M), dtype=float).ravel()
    n = np.asarray(be.to_numpy(rays.N), dtype=float).ravel()
    with np.errstate(divide="ignore", invalid="ignore"):
        intercepts = -y * n / m
    if not np.all(np.isfinite(intercepts)):
        raise ValueError("Axial ray does not intersect the optical axis")
    return intercepts


def _normalized_weights(values: Iterable[float], count: int) -> list[float]:
    weights = [max(float(value), 0.0) for value in list(values)[:count]]
    weights.extend([1.0] * (count - len(weights)))
    total = sum(weights)
    return [value / total for value in weights] if total > 0 else [1.0 / count] * count
