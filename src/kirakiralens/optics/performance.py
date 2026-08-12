from __future__ import annotations

from math import pi
from typing import Any, Callable

import numpy as np

from ..domain import OpticalDesign
from .optiland_adapter import OptilandAdapter


QUALITY_PRESETS = {
    "preview": {"spot_rings": 6, "ray_points": 65, "curve_points": 33, "longitudinal_points": 33},
    "standard": {"spot_rings": 10, "ray_points": 101, "curve_points": 51, "longitudinal_points": 51},
    "high": {"spot_rings": 16, "ray_points": 161, "curve_points": 81, "longitudinal_points": 81},
}


def normalized_options(options: dict[str, Any] | None = None) -> dict[str, Any]:
    source = options or {}
    quality = str(source.get("quality", "standard"))
    if quality not in QUALITY_PRESETS:
        quality = "standard"
    maximum_frequency = min(max(float(source.get("max_frequency_lp_mm", 80.0)), 20.0), 400.0)
    values = dict(QUALITY_PRESETS[quality])
    values.update({"quality": quality, "max_frequency_lp_mm": maximum_frequency})
    return values


def evaluate_performance(design: OpticalDesign, options: dict[str, Any] | None = None) -> dict[str, Any]:
    resolved = normalized_options(options)
    result: dict[str, Any] = {
        "valid": False,
        "engine": "Optiland",
        "method": "Equal-weight polychromatic geometric OTF with diffraction transfer",
        "options": resolved,
        "fields": [],
        "wavelengths_um": list(design.settings.wavelengths_um),
        "mtf": {},
        "spots": {},
        "ray_fan": {},
        "longitudinal": {},
        "field_curvature": {},
        "distortion": {},
        "summary": {},
        "warnings": [],
    }
    if not design.elements:
        result["warnings"].append("No lens elements")
        return result

    try:
        import optiland

        system = OptilandAdapter().to_optic(design)
        result["engine"] = f"Optiland {getattr(optiland, '__version__', 'unknown')}"
        fields = [tuple(map(float, field)) for field in system.fields.get_field_coords()]
        wavelengths = [float(value) for value in system.wavelengths.get_wavelengths()]
        result["fields"] = [
            {"index": index, "fraction": float(field[1]), "label": _field_label(float(field[1]))}
            for index, field in enumerate(fields)
        ]
        result["wavelengths_um"] = wavelengths
    except Exception as exc:
        result["warnings"].append(f"Optical system: {type(exc).__name__}: {exc}")
        return result

    def run(name: str, operation: Callable[[], Any]) -> Any:
        try:
            return operation()
        except Exception as exc:
            result["warnings"].append(f"{name}: {type(exc).__name__}: {exc}")
            return None

    spot_analysis = run(
        "Spot diagram",
        lambda: _spot_and_mtf(
            system,
            fields,
            wavelengths,
            design.settings.primary_wavelength_um,
            int(resolved["spot_rings"]),
            float(resolved["max_frequency_lp_mm"]),
            int(resolved["curve_points"]),
        ),
    )
    if spot_analysis:
        result["spots"], result["mtf"] = spot_analysis

    result["ray_fan"] = run(
        "Transverse ray aberration",
        lambda: _ray_fan(system, fields, wavelengths, int(resolved["ray_points"])),
    ) or {}
    result["longitudinal"] = run(
        "Longitudinal aberration",
        lambda: _longitudinal_aberration(
            system,
            wavelengths,
            design.settings.primary_wavelength_um,
            int(resolved["longitudinal_points"]),
        ),
    ) or {}
    result["field_curvature"] = run(
        "Field curvature",
        lambda: _field_curvature(system, wavelengths, int(resolved["curve_points"])),
    ) or {}
    result["distortion"] = run(
        "Distortion",
        lambda: _distortion(system, wavelengths, int(resolved["curve_points"])),
    ) or {}
    result["summary"] = _build_summary(result)
    result["valid"] = bool(result["spots"] and result["mtf"])
    return result


def _spot_and_mtf(system, fields, wavelengths, primary_wavelength, rings, max_frequency, curve_points):
    from optiland.analysis import SpotDiagram

    analysis = SpotDiagram(
        system,
        fields=fields,
        wavelengths=wavelengths,
        num_rings=rings,
        distribution="hexapolar",
        coordinates="local",
    )
    primary_index = min(range(len(wavelengths)), key=lambda index: abs(wavelengths[index] - primary_wavelength))
    base_frequencies = np.linspace(0.0, max_frequency, curve_points)
    frequencies = np.array(sorted(set(base_frequencies.tolist() + [10.0, 20.0, 40.0])))
    frequencies = frequencies[frequencies <= max_frequency]
    f_number = abs(float(system.paraxial.FNO()))
    spot_fields = []
    mtf_fields = []

    for field_index, field_data in enumerate(analysis.data):
        primary = field_data[primary_index]
        primary_x, primary_y, primary_i = _valid_rays(primary.x, primary.y, primary.intensity)
        center_x = _weighted_mean(primary_x, primary_i)
        center_y = _weighted_mean(primary_y, primary_i)
        series = []
        wavelength_samples = []
        all_x: list[np.ndarray] = []
        all_y: list[np.ndarray] = []
        all_weights: list[np.ndarray] = []

        for wavelength, wave_data in zip(wavelengths, field_data, strict=True):
            x, y, intensity = _valid_rays(wave_data.x, wave_data.y, wave_data.intensity)
            x = x - center_x
            y = y - center_y
            weights = _normalized_weights(intensity) / len(wavelengths)
            all_x.append(x)
            all_y.append(y)
            all_weights.append(weights)
            wavelength_samples.append((wavelength, x, y, weights))
            series.append(
                {
                    "wavelength_um": wavelength,
                    "x_um": _float_list(x * 1000.0),
                    "y_um": _float_list(y * 1000.0),
                }
            )

        combined_x = np.concatenate(all_x)
        combined_y = np.concatenate(all_y)
        combined_weights = np.concatenate(all_weights)
        radii = np.hypot(combined_x, combined_y)
        rms_um = float(np.sqrt(np.sum(combined_weights * radii**2) / np.sum(combined_weights)) * 1000.0)
        r80_um = float(_weighted_quantile(radii, combined_weights, 0.8) * 1000.0)
        spot_fields.append(
            {
                "field": float(fields[field_index][1]),
                "label": _field_label(float(fields[field_index][1])),
                "rms_um": rms_um,
                "r80_um": r80_um,
                "series": series,
            }
        )

        tangential_complex = np.zeros(len(frequencies), dtype=complex)
        sagittal_complex = np.zeros(len(frequencies), dtype=complex)
        for wavelength, x, y, weights in wavelength_samples:
            diffraction = _diffraction_mtf(frequencies, wavelength, f_number)
            tangential_complex += _geometric_otf(y, weights, frequencies) * diffraction / len(wavelengths)
            sagittal_complex += _geometric_otf(x, weights, frequencies) * diffraction / len(wavelengths)
        tangential = np.abs(tangential_complex)
        sagittal = np.abs(sagittal_complex)
        mtf_fields.append(
            {
                "field": float(fields[field_index][1]),
                "label": _field_label(float(fields[field_index][1])),
                "tangential": _float_list(tangential),
                "sagittal": _float_list(sagittal),
                "at": {
                    str(int(frequency)): {
                        "tangential": float(np.interp(frequency, frequencies, tangential)),
                        "sagittal": float(np.interp(frequency, frequencies, sagittal)),
                    }
                    for frequency in (10.0, 20.0, 40.0)
                    if frequency <= max_frequency
                },
            }
        )

    return (
        {
            "airy_radius_um": 1.22 * f_number * float(primary_wavelength),
            "fields": spot_fields,
        },
        {
            "frequencies_lp_mm": _float_list(frequencies),
            "fields": mtf_fields,
            "spectral_weighting": "equal",
        },
    )


def _ray_fan(system, fields, wavelengths, num_points):
    from optiland.analysis import RayFan

    analysis = RayFan(system, fields=fields, wavelengths=wavelengths, num_points=num_points)
    output_fields = []
    for field in fields:
        data = analysis.data[f"{field}"]
        tangential = []
        sagittal = []
        tangential_values = []
        sagittal_values = []
        for wavelength in wavelengths:
            wave = data[f"{wavelength}"]
            pupil_y, error_y = _valid_fan(analysis.data["Py"], wave["y"], wave["intensity_y"])
            pupil_x, error_x = _valid_fan(analysis.data["Px"], wave["x"], wave["intensity_x"])
            error_y_um = error_y * 1000.0
            error_x_um = error_x * 1000.0
            tangential_values.append(error_y_um)
            sagittal_values.append(error_x_um)
            tangential.append(
                {"wavelength_um": wavelength, "pupil": _float_list(pupil_y), "error_um": _float_list(error_y_um)}
            )
            sagittal.append(
                {"wavelength_um": wavelength, "pupil": _float_list(pupil_x), "error_um": _float_list(error_x_um)}
            )
        all_errors = np.concatenate(tangential_values + sagittal_values)
        output_fields.append(
            {
                "field": float(field[1]),
                "label": _field_label(float(field[1])),
                "tangential": tangential,
                "sagittal": sagittal,
                "rms_um": float(np.sqrt(np.mean(all_errors**2))),
                "peak_to_valley_um": float(np.max(all_errors) - np.min(all_errors)),
            }
        )
    return {"fields": output_fields}


def _longitudinal_aberration(system, wavelengths, primary_wavelength, num_points):
    pupil = np.linspace(0.02, 1.0, num_points)
    paraxial_intercepts: dict[float, float] = {}
    series = []
    for wavelength in wavelengths:
        reference_ray = system.trace_generic(Hx=0, Hy=0, Px=0, Py=1e-4, wavelength=wavelength)
        paraxial_intercepts[wavelength] = _axial_intercept(reference_ray)[0]
    primary = min(wavelengths, key=lambda wavelength: abs(wavelength - primary_wavelength))
    common_reference = paraxial_intercepts[primary]
    for wavelength in wavelengths:
        rays = system.trace_generic(
            Hx=np.zeros_like(pupil),
            Hy=np.zeros_like(pupil),
            Px=np.zeros_like(pupil),
            Py=pupil,
            wavelength=wavelength,
        )
        intercept = _axial_intercept(rays) - common_reference
        series.append({"wavelength_um": wavelength, "focus_shift_mm": _float_list(intercept)})
    primary_series = next(item for item in series if item["wavelength_um"] == primary)
    primary_lsa_um = abs(float(primary_series["focus_shift_mm"][-1])) * 1000.0
    axial_color_um = (max(paraxial_intercepts.values()) - min(paraxial_intercepts.values())) * 1000.0
    return {
        "pupil": _float_list(pupil),
        "series": series,
        "primary_lsa_um": primary_lsa_um,
        "axial_color_um": float(axial_color_um),
    }


def _field_curvature(system, wavelengths, num_points):
    from optiland.analysis import FieldCurvature

    analysis = FieldCurvature(system, wavelengths=wavelengths, num_points=num_points)
    field = np.linspace(0.0, 1.0, num_points)
    series = []
    for wavelength, wave_data in zip(wavelengths, analysis.data, strict=True):
        series.append(
            {
                "wavelength_um": wavelength,
                "tangential_mm": _float_list(wave_data[0]),
                "sagittal_mm": _float_list(wave_data[1]),
            }
        )
    return {"field": _float_list(field), "series": series}


def _distortion(system, wavelengths, num_points):
    from optiland.analysis import Distortion

    analysis = Distortion(system, wavelengths=wavelengths, num_points=num_points, distortion_type="f-tan")
    field = np.linspace(0.0, 1.0, num_points)
    series = [
        {"wavelength_um": wavelength, "percent": _float_list(values)}
        for wavelength, values in zip(wavelengths, analysis.data, strict=True)
    ]
    return {"field": _float_list(field), "series": series}


def _build_summary(result: dict[str, Any]) -> dict[str, Any]:
    mtf_fields = result.get("mtf", {}).get("fields", [])
    spot_fields = result.get("spots", {}).get("fields", [])
    fan_fields = result.get("ray_fan", {}).get("fields", [])
    field_series = result.get("field_curvature", {}).get("series", [])
    distortion_series = result.get("distortion", {}).get("series", [])
    mtf40_values = [direction
                    for field in mtf_fields
                    for direction in field.get("at", {}).get("40", {}).values()]
    edge_astigmatism = None
    if field_series:
        primary_index = len(field_series) // 2
        primary = field_series[primary_index]
        tangential_edge = _last_finite(primary["tangential_mm"])
        sagittal_edge = _last_finite(primary["sagittal_mm"])
        if tangential_edge is not None and sagittal_edge is not None:
            edge_astigmatism = abs(tangential_edge - sagittal_edge)
    edge_distortion = (
        _last_finite(distortion_series[len(distortion_series) // 2]["percent"])
        if distortion_series
        else None
    )
    return {
        "field_rows": [
            {
                "label": mtf_field["label"],
                "mtf10_t": mtf_field.get("at", {}).get("10", {}).get("tangential"),
                "mtf10_s": mtf_field.get("at", {}).get("10", {}).get("sagittal"),
                "mtf20_t": mtf_field.get("at", {}).get("20", {}).get("tangential"),
                "mtf20_s": mtf_field.get("at", {}).get("20", {}).get("sagittal"),
                "mtf40_t": mtf_field.get("at", {}).get("40", {}).get("tangential"),
                "mtf40_s": mtf_field.get("at", {}).get("40", {}).get("sagittal"),
                "rms_spot_um": spot_fields[index]["rms_um"] if index < len(spot_fields) else None,
                "r80_um": spot_fields[index]["r80_um"] if index < len(spot_fields) else None,
            }
            for index, mtf_field in enumerate(mtf_fields)
        ],
        "merit_metrics": {
            "mtf40_min": min(mtf40_values) if mtf40_values else None,
            "corner_rms_spot_um": spot_fields[-1]["rms_um"] if spot_fields else None,
            "max_ray_fan_rms_um": max((field["rms_um"] for field in fan_fields), default=None),
            "edge_distortion_percent": edge_distortion,
            "edge_astigmatism_mm": edge_astigmatism,
            "primary_longitudinal_spherical_um": result.get("longitudinal", {}).get("primary_lsa_um"),
            "axial_color_um": result.get("longitudinal", {}).get("axial_color_um"),
        },
    }


def _valid_rays(x_values, y_values, intensity_values):
    x = np.asarray(x_values, dtype=float).ravel()
    y = np.asarray(y_values, dtype=float).ravel()
    intensity = np.asarray(intensity_values, dtype=float).ravel()
    mask = np.isfinite(x) & np.isfinite(y) & np.isfinite(intensity) & (intensity > 0)
    if not np.any(mask):
        raise ValueError("No valid rays reached the image plane")
    return x[mask], y[mask], intensity[mask]


def _valid_fan(pupil_values, error_values, intensity_values):
    pupil = np.asarray(pupil_values, dtype=float).ravel()
    error = np.asarray(error_values, dtype=float).ravel()
    intensity = np.asarray(intensity_values, dtype=float).ravel()
    mask = np.isfinite(pupil) & np.isfinite(error) & np.isfinite(intensity) & (intensity > 0)
    if not np.any(mask):
        raise ValueError("No valid fan rays reached the image plane")
    return pupil[mask], error[mask]


def _weighted_mean(values: np.ndarray, weights: np.ndarray) -> float:
    normalized = _normalized_weights(weights)
    return float(np.sum(values * normalized))


def _normalized_weights(weights: np.ndarray) -> np.ndarray:
    values = np.asarray(weights, dtype=float)
    total = float(np.sum(values))
    if total <= 0:
        return np.full(values.shape, 1.0 / len(values))
    return values / total


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, quantile: float) -> float:
    order = np.argsort(values)
    sorted_values = values[order]
    cumulative = np.cumsum(weights[order])
    cumulative /= cumulative[-1]
    return float(np.interp(quantile, cumulative, sorted_values))


def _geometric_otf(coordinates_mm: np.ndarray, weights: np.ndarray, frequencies: np.ndarray) -> np.ndarray:
    phase = -2j * pi * frequencies[:, None] * coordinates_mm[None, :]
    return np.sum(np.exp(phase) * weights[None, :], axis=1) / np.sum(weights)


def _diffraction_mtf(frequencies: np.ndarray, wavelength_um: float, f_number: float) -> np.ndarray:
    cutoff = 1.0 / (wavelength_um * 1e-3 * f_number)
    ratio = np.clip(frequencies / cutoff, 0.0, 1.0)
    transfer = 2.0 / pi * (np.arccos(ratio) - ratio * np.sqrt(np.maximum(1.0 - ratio**2, 0.0)))
    transfer[frequencies >= cutoff] = 0.0
    return transfer


def _axial_intercept(rays) -> np.ndarray:
    y = np.asarray(rays.y, dtype=float).ravel()
    m = np.asarray(rays.M, dtype=float).ravel()
    n = np.asarray(rays.N, dtype=float).ravel()
    with np.errstate(divide="ignore", invalid="ignore"):
        intercept = -y * n / m
    if not np.all(np.isfinite(intercept)):
        raise ValueError("Axial ray does not intersect the optical axis")
    return intercept


def _float_list(values) -> list[float | None]:
    array = np.asarray(values, dtype=float).ravel()
    return [float(value) if np.isfinite(value) else None for value in array]


def _last_finite(values: list[float | None]) -> float | None:
    for value in reversed(values):
        if value is not None and np.isfinite(value):
            return float(value)
    return None


def _field_label(fraction: float) -> str:
    if abs(fraction) < 1e-6:
        return "中心"
    if abs(fraction - 1.0) < 1e-6:
        return "隅"
    return f"像高 {fraction:.0%}"
