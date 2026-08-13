from __future__ import annotations

from math import pi, radians, tan
from typing import Any, Callable

import numpy as np

from ..domain import OpticalDesign
from .configuration import resolved_field_angles, sensor_angle_of_view
from .optiland_adapter import OptilandAdapter, scalar_value


QUALITY_PRESETS = {
    "preview": {"spot_rings": 6, "ray_points": 65, "curve_points": 33, "longitudinal_points": 33, "grid_points": 9},
    "standard": {"spot_rings": 10, "ray_points": 101, "curve_points": 51, "longitudinal_points": 51, "grid_points": 11},
    "high": {"spot_rings": 16, "ray_points": 161, "curve_points": 81, "longitudinal_points": 81, "grid_points": 15},
}


def normalized_options(options: dict[str, Any] | None = None, design: OpticalDesign | None = None) -> dict[str, Any]:
    source = options or {}
    quality = str(source.get("quality", "standard"))
    if quality == "design" and design is not None:
        values = {
            "spot_rings": design.settings.spot_ring_count,
            "ray_points": design.settings.ray_fan_point_count,
            "curve_points": design.settings.analysis_curve_point_count,
            "longitudinal_points": design.settings.analysis_curve_point_count,
            "grid_points": 11,
        }
    else:
        if quality not in QUALITY_PRESETS:
            quality = "standard"
        values = dict(QUALITY_PRESETS[quality])
    if quality not in {*QUALITY_PRESETS, "design"}:
        quality = "standard"
    maximum_frequency = min(max(float(source.get("max_frequency_lp_mm", 80.0)), 20.0), 400.0)
    for key in ("spot_rings", "ray_points", "curve_points", "longitudinal_points", "grid_points"):
        if key in source:
            values[key] = int(source[key])
    values["grid_points"] = min(max(int(values["grid_points"]), 5), 31)
    if values["grid_points"] % 2 == 0:
        values["grid_points"] += 1
    values.update({"quality": quality, "max_frequency_lp_mm": maximum_frequency})
    return values


def evaluate_performance(design: OpticalDesign, options: dict[str, Any] | None = None) -> dict[str, Any]:
    resolved = normalized_options(options, design)
    result: dict[str, Any] = {
        "valid": False,
        "engine": "Optiland",
        "method": "Weighted polychromatic geometric OTF with diffraction transfer",
        "options": resolved,
        "fields": [],
        "wavelengths_um": list(design.settings.wavelengths_um),
        "wavelength_weights": list(design.settings.wavelength_weights),
        "angle_of_view": sensor_angle_of_view(design.settings),
        "mtf": {},
        "spots": {},
        "ray_fan": {},
        "longitudinal": {},
        "field_curvature": {},
        "distortion": {},
        "distortion_grid": {},
        "petzval": {},
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
        field_angles = resolved_field_angles(design.settings)
        effective_focal_length = abs(float(system.paraxial.f2()))
        field_heights_mm = [_image_height_mm(effective_focal_length, angle) for angle in field_angles]
        result["angle_of_view"] = sensor_angle_of_view(design.settings, effective_focal_length)
        result["fields"] = [
            {
                "index": index,
                "fraction": float(field[1]),
                "angle_deg": field_angles[index],
                "image_height_mm": field_heights_mm[index],
                "label": _field_label(
                    float(field[1]),
                    field_angles[index],
                    field_heights_mm[index],
                ),
            }
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
            design.settings.wavelength_weights,
            field_angles,
            field_heights_mm,
        ),
    )
    if spot_analysis:
        result["spots"], result["mtf"] = spot_analysis

    result["ray_fan"] = run(
        "Transverse ray aberration",
        lambda: _ray_fan(
            system,
            fields,
            wavelengths,
            int(resolved["ray_points"]),
            field_angles,
            field_heights_mm,
        ),
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
        lambda: _field_curvature(
            system,
            wavelengths,
            int(resolved["curve_points"]),
            max(field_angles, default=0.0),
            effective_focal_length,
        ),
    ) or {}
    result["distortion"] = run(
        "Distortion",
        lambda: _distortion(
            system,
            wavelengths,
            int(resolved["curve_points"]),
            max(field_angles, default=0.0),
            effective_focal_length,
        ),
    ) or {}
    result["distortion_grid"] = run(
        "Grid distortion",
        lambda: _grid_distortion(
            system,
            design.settings.primary_wavelength_um,
            int(resolved["grid_points"]),
        ),
    ) or {}
    result["petzval"] = run(
        "Petzval sum",
        lambda: _petzval_sum(system, design.settings.primary_wavelength_um),
    ) or {}
    result["summary"] = _build_summary(result)
    result["valid"] = bool(result["spots"] and result["mtf"])
    return result


def minimum_polychromatic_mtf(system, design: OpticalDesign, frequency_lp_mm: float = 40.0, rings: int = 3) -> float:
    fields = [tuple(map(float, field)) for field in system.fields.get_field_coords()]
    wavelengths = [float(value) for value in system.wavelengths.get_wavelengths()]
    _, mtf = _spot_and_mtf(
        system,
        fields,
        wavelengths,
        design.settings.primary_wavelength_um,
        max(int(rings), 2),
        max(float(frequency_lp_mm), 40.0),
        11,
        design.settings.wavelength_weights,
        resolved_field_angles(design.settings),
        [
            _image_height_mm(abs(float(system.paraxial.f2())), angle)
            for angle in resolved_field_angles(design.settings)
        ],
    )
    key = str(int(frequency_lp_mm))
    values = [
        direction
        for field in mtf["fields"]
        for direction in field.get("at", {}).get(key, {}).values()
    ]
    if not values:
        raise ValueError(f"MTF {frequency_lp_mm:g} lp/mm could not be evaluated")
    return float(min(values))


def _spot_and_mtf(
    system,
    fields,
    wavelengths,
    primary_wavelength,
    rings,
    max_frequency,
    curve_points,
    wavelength_weights,
    field_angles,
    field_heights_mm,
):
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
    f_number = abs(scalar_value(system.paraxial.FNO()))
    spectral_weights = np.asarray((wavelength_weights + [1.0] * len(wavelengths))[: len(wavelengths)], dtype=float)
    spectral_weights = _normalized_weights(spectral_weights)
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

        for spectral_weight, wavelength, wave_data in zip(spectral_weights, wavelengths, field_data, strict=True):
            x, y, intensity = _valid_rays(wave_data.x, wave_data.y, wave_data.intensity)
            x = x - center_x
            y = y - center_y
            weights = _normalized_weights(intensity) * spectral_weight
            all_x.append(x)
            all_y.append(y)
            all_weights.append(weights)
            wavelength_samples.append((wavelength, x, y, weights, spectral_weight))
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
                "angle_deg": field_angles[field_index],
                "image_height_mm": field_heights_mm[field_index],
                "label": _field_label(
                    float(fields[field_index][1]),
                    field_angles[field_index],
                    field_heights_mm[field_index],
                ),
                "rms_um": rms_um,
                "r80_um": r80_um,
                "series": series,
            }
        )

        tangential_complex = np.zeros(len(frequencies), dtype=complex)
        sagittal_complex = np.zeros(len(frequencies), dtype=complex)
        for wavelength, x, y, weights, spectral_weight in wavelength_samples:
            diffraction = _diffraction_mtf(frequencies, wavelength, f_number)
            normalized_ray_weights = _normalized_weights(weights)
            tangential_complex += _geometric_otf(y, normalized_ray_weights, frequencies) * diffraction * spectral_weight
            sagittal_complex += _geometric_otf(x, normalized_ray_weights, frequencies) * diffraction * spectral_weight
        tangential = np.abs(tangential_complex)
        sagittal = np.abs(sagittal_complex)
        mtf_fields.append(
            {
                "field": float(fields[field_index][1]),
                "angle_deg": field_angles[field_index],
                "image_height_mm": field_heights_mm[field_index],
                "label": _field_label(
                    float(fields[field_index][1]),
                    field_angles[field_index],
                    field_heights_mm[field_index],
                ),
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
            "spectral_weighting": "user weights (normalized)",
        },
    )


def _ray_fan(system, fields, wavelengths, num_points, field_angles, field_heights_mm):
    from optiland.analysis import RayFan

    analysis = RayFan(system, fields=fields, wavelengths=wavelengths, num_points=num_points)
    output_fields = []
    for field_index, field in enumerate(fields):
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
                "angle_deg": field_angles[field_index],
                "image_height_mm": field_heights_mm[field_index],
                "label": _field_label(
                    float(field[1]),
                    field_angles[field_index],
                    field_heights_mm[field_index],
                ),
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


def _field_curvature(system, wavelengths, num_points, maximum_field_angle_deg, effective_focal_length_mm):
    from optiland.analysis import FieldCurvature

    analysis = FieldCurvature(system, wavelengths=wavelengths, num_points=num_points)
    field = np.linspace(0.0, 1.0, num_points)
    image_height_mm = [
        _image_height_mm(effective_focal_length_mm, maximum_field_angle_deg * float(fraction))
        for fraction in field
    ]
    series = []
    for wavelength, wave_data in zip(wavelengths, analysis.data, strict=True):
        series.append(
            {
                "wavelength_um": wavelength,
                "tangential_mm": _float_list(wave_data[0]),
                "sagittal_mm": _float_list(wave_data[1]),
            }
        )
    return {
        "field": _float_list(field),
        "image_height_mm": image_height_mm,
        "maximum_image_height_mm": max(image_height_mm, default=0.0),
        "series": series,
    }


def _distortion(system, wavelengths, num_points, maximum_field_angle_deg, effective_focal_length_mm):
    from optiland.analysis import Distortion

    analysis = Distortion(system, wavelengths=wavelengths, num_points=num_points, distortion_type="f-tan")
    field = np.linspace(0.0, 1.0, num_points)
    image_height_mm = [
        _image_height_mm(effective_focal_length_mm, maximum_field_angle_deg * float(fraction))
        for fraction in field
    ]
    series = [
        {"wavelength_um": wavelength, "percent": _float_list(values)}
        for wavelength, values in zip(wavelengths, analysis.data, strict=True)
    ]
    return {
        "field": _float_list(field),
        "image_height_mm": image_height_mm,
        "maximum_image_height_mm": max(image_height_mm, default=0.0),
        "series": series,
    }


def _grid_distortion(system, primary_wavelength, num_points):
    import warnings

    import optiland.backend as be
    from optiland.analysis import GridDistortion

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        analysis = GridDistortion(
            system,
            wavelength=float(primary_wavelength),
            num_points=int(num_points),
            distortion_type="f-tan",
        )
    ideal_x = np.asarray(be.to_numpy(analysis.data["xp"]), dtype=float)
    ideal_y = np.asarray(be.to_numpy(analysis.data["yp"]), dtype=float)
    real_x = np.asarray(be.to_numpy(analysis.data["xr"]), dtype=float)
    real_y = np.asarray(be.to_numpy(analysis.data["yr"]), dtype=float)
    ideal_radius = np.hypot(ideal_x, ideal_y)
    displacement = np.hypot(ideal_x - real_x, ideal_y - real_y)
    valid = (
        np.isfinite(ideal_radius)
        & np.isfinite(displacement)
        & np.isfinite(real_x)
        & np.isfinite(real_y)
        & (ideal_radius > 1e-12)
    )
    maximum_distortion = float(np.max(100.0 * displacement[valid] / ideal_radius[valid])) if np.any(valid) else None
    maximum_displacement = float(np.max(displacement[valid])) if np.any(valid) else None
    return {
        "wavelength_um": float(primary_wavelength),
        "grid_points": int(num_points),
        "ideal_x_mm": _nested_float_list(ideal_x),
        "ideal_y_mm": _nested_float_list(ideal_y),
        "real_x_mm": _nested_float_list(real_x),
        "real_y_mm": _nested_float_list(real_y),
        "maximum_distortion_percent": maximum_distortion,
        "maximum_displacement_mm": maximum_displacement,
        "model": "f-tan chief-ray grid",
    }


def _petzval_sum(system, primary_wavelength):
    import optiland.backend as be

    indices = np.asarray(be.to_numpy(system.n(float(primary_wavelength))), dtype=float).ravel()
    radii = np.asarray(be.to_numpy(system.surface_group.radii), dtype=float).ravel()
    contributions = []
    petzval_sum = 0.0
    for surface_number in range(1, len(radii) - 1):
        radius = float(radii[surface_number])
        n_before = float(indices[surface_number - 1])
        n_after = float(indices[surface_number])
        contribution = 0.0
        if np.isfinite(radius) and abs(radius) > 1e-12 and n_before > 0 and n_after > 0:
            contribution = (n_after - n_before) / (radius * n_before * n_after)
        petzval_sum += contribution
        surface = system.surface_group.surfaces[surface_number]
        contributions.append(
            {
                "surface_number": surface_number,
                "comment": str(surface.comment),
                "curvature_per_mm": float(contribution),
            }
        )
    radius_mm = -1.0 / petzval_sum if abs(petzval_sum) > 1e-15 else None
    transverse_sum = None
    longitudinal_sum = None
    try:
        transverse_sum = float(be.sum(system.aberrations.TPC()))
        longitudinal_sum = float(be.sum(system.aberrations.PC()))
    except Exception:
        pass
    return {
        "curvature_per_mm": float(petzval_sum),
        "radius_mm": radius_mm,
        "transverse_third_order_mm": transverse_sum,
        "longitudinal_third_order_mm": longitudinal_sum,
        "wavelength_um": float(primary_wavelength),
        "surface_contributions": contributions,
        "radius_convention": "R = -1 / Petzval sum",
    }


def _build_summary(result: dict[str, Any]) -> dict[str, Any]:
    mtf_fields = result.get("mtf", {}).get("fields", [])
    spot_fields = result.get("spots", {}).get("fields", [])
    fan_fields = result.get("ray_fan", {}).get("fields", [])
    field_series = result.get("field_curvature", {}).get("series", [])
    distortion_series = result.get("distortion", {}).get("series", [])
    petzval = result.get("petzval", {})
    distortion_grid = result.get("distortion_grid", {})
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
                "field_fraction": mtf_field.get("field"),
                "image_height_mm": mtf_field.get("image_height_mm"),
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
            "petzval_sum_per_mm": petzval.get("curvature_per_mm"),
            "petzval_radius_mm": petzval.get("radius_mm"),
            "grid_max_distortion_percent": distortion_grid.get("maximum_distortion_percent"),
        },
    }


def _nested_float_list(values) -> list[list[float | None]]:
    array = np.asarray(values, dtype=float)
    return [
        [float(value) if np.isfinite(value) else None for value in row]
        for row in array
    ]


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


def _field_label(
    fraction: float,
    angle_deg: float | None = None,
    image_height_mm: float | None = None,
) -> str:
    angle = "" if angle_deg is None else f" / {angle_deg:.2f}°"
    height = "" if image_height_mm is None else f" / {image_height_mm:.2f} mm"
    if abs(fraction) < 1e-6:
        return f"中心 0%{height}{angle}"
    if abs(fraction - 1.0) < 1e-6:
        return f"隅 100%{height}{angle}"
    return f"像高 {fraction:.0%}{height}{angle}"


def _image_height_mm(effective_focal_length_mm: float, field_angle_deg: float) -> float:
    return abs(float(effective_focal_length_mm)) * tan(radians(abs(float(field_angle_deg))))
