from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from math import radians, sqrt, tan
from time import monotonic
from typing import Any, Callable

import numpy as np

from ..domain import OpticalDesign
from .configuration import resolved_field_weights
from .optiland_adapter import OptilandAdapter


@dataclass(slots=True)
class VariableCandidate:
    kind: str
    label: str
    element_index: int
    surface_index: int
    surface_number: int
    minimum: float
    maximum: float


DEFAULT_AUTOMATIC_OPTIONS: dict[str, Any] = {
    "method": "local",
    "time_limit_seconds": 60,
    "max_evaluations": 500,
    "vary_radii": True,
    "vary_thicknesses": False,
    "vary_air_gaps": True,
    "vary_image_plane": False,
    "efl_weight": 3.0,
    "bfl_weight": 2.0,
    "spot_weight": 10.0,
    "distortion_weight": 1.0,
    "spot_rings": 5,
    "seed": 1,
}


def normalized_automatic_options(options: dict[str, Any] | None = None) -> dict[str, Any]:
    result = dict(DEFAULT_AUTOMATIC_OPTIONS)
    result.update(options or {})
    result["method"] = "global" if result["method"] == "global" else "local"
    result["time_limit_seconds"] = min(max(float(result["time_limit_seconds"]), 1.0), 86400.0)
    result["max_evaluations"] = min(max(int(result["max_evaluations"]), 10), 1000000)
    result["spot_rings"] = min(max(int(result["spot_rings"]), 2), 12)
    result["seed"] = int(result["seed"])
    for key in ("efl_weight", "bfl_weight", "spot_weight", "distortion_weight"):
        result[key] = min(max(float(result[key]), 0.0), 1000.0)
    for key in ("vary_radii", "vary_thicknesses", "vary_air_gaps", "vary_image_plane"):
        result[key] = bool(result[key])
    return result


def variable_candidates(design: OpticalDesign, options: dict[str, Any] | None = None) -> list[VariableCandidate]:
    resolved = normalized_automatic_options(options)
    candidates: list[VariableCandidate] = []
    surface_number = 1
    for element_index, element in enumerate(design.elements):
        prescription_variable = not element.is_catalog and not element.element_locked
        for surface_index, surface in enumerate(element.surfaces):
            is_last_surface = surface_index == len(element.surfaces) - 1
            if (
                resolved["vary_radii"]
                and prescription_variable
                and not surface.radius_locked
                and not surface.is_plane
            ):
                radius = float(surface.radius_mm)
                absolute = abs(radius)
                low = max(absolute * 0.25, 2.0)
                high = min(max(absolute * 4.0, 100.0), 5000.0)
                minimum, maximum = (low, high) if radius > 0 else (-high, -low)
                candidates.append(
                    VariableCandidate(
                        "radius",
                        f"L{element_index + 1} S{surface_index + 1} 曲率半径",
                        element_index,
                        surface_index,
                        surface_number,
                        minimum,
                        maximum,
                    )
                )
            if (
                not is_last_surface
                and resolved["vary_thicknesses"]
                and prescription_variable
                and not surface.thickness_locked
            ):
                value = surface.thickness_after_mm
                candidates.append(
                    VariableCandidate(
                        "thickness",
                        f"L{element_index + 1} S{surface_index + 1} 面間隔",
                        element_index,
                        surface_index,
                        surface_number,
                        0.2,
                        min(max(value * 3.0, 12.0), 100.0),
                    )
                )
            if is_last_surface and not element.gap_locked and not element.element_locked:
                is_image_plane = element_index == len(design.elements) - 1
                enabled = resolved["vary_image_plane"] if is_image_plane else resolved["vary_air_gaps"]
                if enabled:
                    minimum = max(element.gap_min_mm, 0.0)
                    maximum = element.gap_max_mm or max(element.gap_after_mm * 4.0 + 5.0, 20.0)
                    if is_image_plane and design.settings.back_focus_hard:
                        tolerance = max(design.settings.back_focus_tolerance_mm, 1e-3)
                        minimum = max(minimum, design.settings.back_focus_target_mm - tolerance)
                        maximum = min(maximum, design.settings.back_focus_target_mm + tolerance)
                    if maximum > minimum:
                        candidates.append(
                            VariableCandidate(
                                "image_gap" if is_image_plane else "air_gap",
                                "像面位置" if is_image_plane else f"L{element_index + 1} 後方空気間隔",
                                element_index,
                                surface_index,
                                surface_number,
                                minimum,
                                maximum,
                            )
                        )
            surface_number += 1
    return candidates


class OptimizationTimeLimit(RuntimeError):
    pass


def run_automatic_design(
    source_design: OpticalDesign,
    options: dict[str, Any] | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    from optiland import optimization
    from scipy import optimize

    resolved = normalized_automatic_options(options)
    design = deepcopy(source_design)
    candidates = variable_candidates(design, resolved)
    if not candidates:
        return {"valid": False, "error": "変更可能な変数がありません", "options": resolved}

    system = OptilandAdapter().to_optic(design)
    problem = optimization.OptimizationProblem()
    for candidate in candidates:
        variable_type = "radius" if candidate.kind == "radius" else "thickness"
        problem.add_variable(
            system,
            variable_type,
            surface_number=candidate.surface_number,
            min_val=candidate.minimum,
            max_val=candidate.maximum,
        )

    target_efl = max(abs(design.settings.focal_length_target_mm), 1e-3)
    if resolved["efl_weight"] > 0:
        problem.add_operand(
            operand_type="f2",
            target=design.settings.focal_length_target_mm,
            weight=sqrt(resolved["efl_weight"]) / target_efl,
            input_data={"optic": system},
        )

    fields = [tuple(map(float, field)) for field in system.fields.get_field_coords()]
    field_weights = _normalized_positive(resolved_field_weights(design.settings), len(fields))
    wavelengths = [float(value) for value in system.wavelengths.get_wavelengths()]
    wavelength_weights = _normalized_positive(design.settings.wavelength_weights, len(wavelengths))
    airy_radius_mm = max(1.22 * design.settings.primary_wavelength_um * 1e-3 * design.settings.f_number_target, 1e-5)
    spot_operand_indices: list[int] = []
    if resolved["spot_weight"] > 0:
        for field_index, field in enumerate(fields):
            for wavelength_index, wavelength in enumerate(wavelengths):
                share = field_weights[field_index] * wavelength_weights[wavelength_index]
                problem.add_operand(
                    operand_type="rms_spot_size",
                    target=0.0,
                    weight=sqrt(resolved["spot_weight"] * share) / airy_radius_mm,
                    input_data={
                        "optic": system,
                        "surface_number": -1,
                        "Hx": field[0],
                        "Hy": field[1],
                        "num_rays": resolved["spot_rings"],
                        "wavelength": wavelength,
                        "distribution": "hexapolar",
                    },
                )
                spot_operand_indices.append(len(problem.operands) - 1)

    if resolved["distortion_weight"] > 0 and fields:
        primary = design.settings.primary_wavelength_um
        field_angles = np.asarray(system.fields.y_fields, dtype=float).ravel()
        for field_index, field in enumerate(fields):
            angle = float(field_angles[field_index])
            if abs(angle) < 1e-9:
                continue
            ideal_height = design.settings.focal_length_target_mm * tan(radians(angle))
            scale = max(abs(ideal_height) * 0.02, 0.01)
            problem.add_operand(
                operand_type="real_y_intercept_lcs",
                target=ideal_height,
                weight=sqrt(resolved["distortion_weight"] * field_weights[field_index]) / scale,
                input_data={
                    "optic": system,
                    "surface_number": -1,
                    "Hx": field[0],
                    "Hy": field[1],
                    "Px": 0.0,
                    "Py": 0.0,
                    "wavelength": primary,
                },
            )

    start = monotonic()
    deadline = start + resolved["time_limit_seconds"]
    x0 = np.asarray([float(variable.value) for variable in problem.variables], dtype=float)
    bounds = [tuple(map(float, variable.bounds)) for variable in problem.variables]
    best_x = x0.copy()
    best_score = float("inf")
    evaluations = 0
    last_report = 0.0

    def objective(values) -> float:
        nonlocal best_x, best_score, evaluations, last_report
        if monotonic() >= deadline or evaluations >= resolved["max_evaluations"]:
            raise OptimizationTimeLimit
        evaluations += 1
        try:
            for variable, value in zip(problem.variables, values, strict=True):
                variable.update(float(value))
            problem.update_optics()
            score = float(problem.sum_squared())
            image_distance = _current_image_distance(design, candidates, problem)
            tolerance = max(design.settings.back_focus_tolerance_mm, 0.1)
            score += resolved["bfl_weight"] * (
                (image_distance - design.settings.back_focus_target_mm) / tolerance
            ) ** 2
            if not np.isfinite(score):
                score = 1e30
        except Exception:
            score = 1e30
        if score < best_score:
            best_score = score
            best_x = np.asarray(values, dtype=float).copy()
        now = monotonic()
        if progress is not None and (now - last_report >= 0.5 or evaluations == 1):
            progress(
                {
                    "evaluations": evaluations,
                    "best_score": best_score,
                    "elapsed_seconds": now - start,
                    "time_limit_seconds": resolved["time_limit_seconds"],
                }
            )
            last_report = now
        return score

    initial_score = objective(x0)
    try:
        if resolved["method"] == "global":
            optimize.differential_evolution(
                objective,
                bounds,
                maxiter=max(1, resolved["max_evaluations"] // max(len(bounds) * 8, 1)),
                popsize=5,
                polish=True,
                seed=resolved["seed"],
                workers=1,
                updating="immediate",
            )
        else:
            optimize.minimize(
                objective,
                x0,
                method="Powell",
                bounds=bounds,
                options={"maxiter": resolved["max_evaluations"], "maxfev": resolved["max_evaluations"], "disp": False},
            )
    except OptimizationTimeLimit:
        pass

    for variable, value in zip(problem.variables, best_x, strict=True):
        variable.update(float(value))
    problem.update_optics()
    changes = _apply_variables_to_design(design, candidates, problem)
    metrics = _final_metrics(system, problem, spot_operand_indices, design)
    if progress is not None:
        progress(
            {
                "evaluations": evaluations,
                "best_score": best_score,
                "elapsed_seconds": monotonic() - start,
                "time_limit_seconds": resolved["time_limit_seconds"],
            }
        )
    return {
        "valid": np.isfinite(best_score) and best_score < 1e29,
        "design": design.to_dict(),
        "initial_score": initial_score,
        "best_score": best_score,
        "evaluations": evaluations,
        "elapsed_seconds": monotonic() - start,
        "variables": [asdict(candidate) for candidate in candidates],
        "changes": changes,
        "metrics": metrics,
        "options": resolved,
        "method": "Optiland real-ray merit / SciPy Powell" if resolved["method"] == "local" else "Optiland real-ray merit / SciPy differential evolution",
    }


def _normalized_positive(values: list[float], count: int) -> list[float]:
    result = [max(float(value), 0.0) for value in values[:count]]
    result.extend([1.0] * (count - len(result)))
    total = sum(result)
    return [value / total for value in result] if total > 0 else [1.0 / count] * count


def _current_image_distance(design, candidates, problem) -> float:
    for candidate, variable in zip(candidates, problem.variables, strict=True):
        if candidate.kind == "image_gap":
            return float(variable.variable.get_value())
    return design.elements[-1].gap_after_mm


def _apply_variables_to_design(design, candidates, problem) -> list[dict[str, Any]]:
    changes = []
    for candidate, variable in zip(candidates, problem.variables, strict=True):
        value = float(variable.variable.get_value())
        element = design.elements[candidate.element_index]
        surface = element.surfaces[candidate.surface_index]
        if candidate.kind == "radius":
            old_value = surface.radius_mm
            surface.radius_mm = value
        elif candidate.kind == "thickness":
            old_value = surface.thickness_after_mm
            surface.thickness_after_mm = value
        else:
            old_value = element.gap_after_mm
            element.gap_after_mm = value
        changes.append({"label": candidate.label, "before": old_value, "after": value})
    return changes


def _final_metrics(system, problem, spot_operand_indices, design) -> dict[str, float | None]:
    spot_values = []
    for index in spot_operand_indices:
        try:
            spot_values.append(float(problem.operands[index].value) * 1000.0)
        except Exception:
            pass
    return {
        "effective_focal_length_mm": float(system.paraxial.f2()),
        "image_distance_mm": design.elements[-1].gap_after_mm,
        "maximum_rms_spot_um": max(spot_values, default=None),
        "diffraction_airy_radius_um": 1.22
        * design.settings.primary_wavelength_um
        * design.settings.f_number_target,
    }
