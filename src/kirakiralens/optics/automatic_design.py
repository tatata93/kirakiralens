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
    "vary_image_plane": True,
    "efl_weight": 3.0,
    "bfl_weight": 2.0,
    "spot_weight": 10.0,
    "distortion_weight": 1.0,
    "track_weight": 1.0,
    "spot_rings": 5,
    "seed": 1,
    "target_efl_mm": None,
    "efl_tolerance_mm": 0.5,
    "efl_hard": False,
    "target_f_number": None,
    "bfl_constraint": "target",
    "target_bfl_mm": None,
    "minimum_bfl_mm": 0.0,
    "maximum_bfl_mm": 1000.0,
    "bfl_tolerance_mm": 0.5,
    "bfl_hard": False,
    "maximum_total_track_mm": None,
    "track_tolerance_mm": 1.0,
    "track_hard": False,
    "discrete_search": False,
    "discrete_evaluations": 80,
    "discrete_beam_width": 6,
    "result_count": 10,
    "mtf_screen_count": 3,
    "allow_orientation_search": True,
    "allow_order_search": True,
    "allow_element_count_search": False,
    "allow_stop_search": False,
    "minimum_element_count": 1,
    "maximum_element_count": 8,
    "candidate_pool": [],
    "topology_pool": [],
    "classic_form": "",
    "classic_seed_design": None,
}


def normalized_automatic_options(options: dict[str, Any] | None = None) -> dict[str, Any]:
    result = dict(DEFAULT_AUTOMATIC_OPTIONS)
    result.update(options or {})
    result["method"] = "global" if result["method"] == "global" else "local"
    result["time_limit_seconds"] = min(max(float(result["time_limit_seconds"]), 1.0), 86400.0)
    result["max_evaluations"] = min(max(int(result["max_evaluations"]), 10), 1000000)
    result["spot_rings"] = min(max(int(result["spot_rings"]), 2), 12)
    result["seed"] = int(result["seed"])
    result["target_efl_mm"] = None if result["target_efl_mm"] is None else max(float(result["target_efl_mm"]), 0.1)
    result["target_f_number"] = None if result["target_f_number"] is None else min(max(float(result["target_f_number"]), 0.5), 64.0)
    result["target_bfl_mm"] = None if result["target_bfl_mm"] is None else max(float(result["target_bfl_mm"]), 0.0)
    result["minimum_bfl_mm"] = max(float(result["minimum_bfl_mm"]), 0.0)
    result["maximum_bfl_mm"] = max(float(result["maximum_bfl_mm"]), result["minimum_bfl_mm"])
    result["efl_tolerance_mm"] = max(float(result["efl_tolerance_mm"]), 1e-3)
    result["bfl_tolerance_mm"] = max(float(result["bfl_tolerance_mm"]), 1e-3)
    result["maximum_total_track_mm"] = (
        None
        if result["maximum_total_track_mm"] in {None, 0, 0.0}
        else max(float(result["maximum_total_track_mm"]), 0.1)
    )
    result["track_tolerance_mm"] = max(float(result["track_tolerance_mm"]), 1e-3)
    if result["bfl_constraint"] not in {"off", "target", "minimum", "range"}:
        result["bfl_constraint"] = "target"
    result["discrete_evaluations"] = min(max(int(result["discrete_evaluations"]), 1), 100000)
    result["discrete_beam_width"] = min(max(int(result["discrete_beam_width"]), 1), 100)
    result["result_count"] = min(max(int(result["result_count"]), 1), 50)
    result["mtf_screen_count"] = min(max(int(result["mtf_screen_count"]), 0), result["result_count"])
    result["minimum_element_count"] = min(max(int(result["minimum_element_count"]), 1), 20)
    result["maximum_element_count"] = min(
        max(int(result["maximum_element_count"]), result["minimum_element_count"]),
        20,
    )
    if result["classic_form"] not in {"", "triplet", "tessar", "double_gauss"}:
        result["classic_form"] = ""
    for key in ("efl_weight", "bfl_weight", "spot_weight", "distortion_weight", "track_weight"):
        result[key] = min(max(float(result[key]), 0.0), 1000.0)
    for key in (
        "vary_radii",
        "vary_thicknesses",
        "vary_air_gaps",
        "vary_image_plane",
        "efl_hard",
        "bfl_hard",
        "track_hard",
        "discrete_search",
        "allow_orientation_search",
        "allow_order_search",
        "allow_element_count_search",
        "allow_stop_search",
    ):
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
                    maximum = (
                        element.gap_max_mm
                        if element.gap_max_mm is not None
                        else max(element.gap_after_mm * 4.0 + 5.0, 20.0)
                    )
                    if is_image_plane and element.gap_max_mm is None:
                        if resolved["bfl_constraint"] == "target" and resolved["target_bfl_mm"] is not None:
                            maximum = max(maximum, resolved["target_bfl_mm"] + resolved["bfl_tolerance_mm"])
                        elif resolved["bfl_constraint"] == "minimum":
                            maximum = max(maximum, resolved["minimum_bfl_mm"] + resolved["bfl_tolerance_mm"])
                        elif resolved["bfl_constraint"] == "range":
                            maximum = max(maximum, resolved["maximum_bfl_mm"])
                    if is_image_plane and resolved["bfl_hard"]:
                        tolerance = resolved["bfl_tolerance_mm"]
                        if resolved["bfl_constraint"] == "target":
                            target = resolved["target_bfl_mm"]
                            if target is not None:
                                minimum = max(minimum, target - tolerance)
                                maximum = min(maximum, target + tolerance)
                        elif resolved["bfl_constraint"] == "minimum":
                            minimum = max(minimum, resolved["minimum_bfl_mm"])
                        elif resolved["bfl_constraint"] == "range":
                            minimum = max(minimum, resolved["minimum_bfl_mm"])
                            maximum = min(maximum, resolved["maximum_bfl_mm"])
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
    overall_start = monotonic()
    deadline = overall_start + resolved["time_limit_seconds"]
    design = deepcopy(source_design)
    if not design.elements:
        return {"valid": False, "error": "探索するレンズがありません", "options": _public_options(resolved)}
    target_efl = resolved["target_efl_mm"] or design.settings.focal_length_target_mm
    target_f_number = resolved["target_f_number"] or design.settings.f_number_target
    target_bfl = resolved["target_bfl_mm"]
    if target_bfl is None:
        target_bfl = design.settings.back_focus_target_mm
    resolved["target_efl_mm"] = target_efl
    resolved["target_f_number"] = target_f_number
    resolved["target_bfl_mm"] = target_bfl
    design.settings.focal_length_target_mm = target_efl
    design.settings.f_number_target = target_f_number
    source_image_distance = design.elements[-1].gap_after_mm if design.elements else None
    if resolved["classic_form"]:
        seed_data = resolved.get("classic_seed_design")
        if not isinstance(seed_data, dict):
            return {"valid": False, "error": "古典型の初期構成がありません", "options": _public_options(resolved)}
        design = OpticalDesign.from_dict(seed_data)
        design.settings.focal_length_target_mm = target_efl
        design.settings.f_number_target = target_f_number
    discrete_result: dict[str, Any] | None = None
    if resolved["discrete_search"]:
        from .discrete_search import run_discrete_search

        discrete_result = run_discrete_search(design, resolved, deadline, progress)
        if not discrete_result.get("valid"):
            return {**discrete_result, "options": _public_options(resolved)}
        design = discrete_result["design"]
    candidates = variable_candidates(design, resolved)
    if not candidates:
        if discrete_result is None:
            return {"valid": False, "error": "変更可能な変数がありません", "options": _public_options(resolved)}
        if not discrete_result.get("constraints_satisfied", True):
            return {
                "valid": False,
                "error": "必須にした焦点距離、バックフォーカス、または全長条件を満たす構成が見つかりませんでした",
                "evaluations": discrete_result.get("evaluations", 0),
                "best_score": discrete_result.get("best_score"),
                "metrics": discrete_result.get("metrics", {}),
                "options": _public_options(resolved),
                "candidates": discrete_result.get("candidates", []),
                "topology": discrete_result.get("topology"),
            }
        if source_image_distance is not None and abs(design.elements[-1].gap_after_mm - source_image_distance) > 1e-9:
            design.settings.auto_focus_enabled = False
        return {
            "valid": True,
            "design": design.to_dict(),
            "initial_score": discrete_result.get("initial_score"),
            "best_score": discrete_result.get("best_score"),
            "evaluations": discrete_result.get("evaluations", 0),
            "elapsed_seconds": monotonic() - overall_start,
            "variables": [],
            "changes": discrete_result.get("changes", []),
            "metrics": discrete_result.get("metrics", {}),
            "options": _public_options(resolved),
            "method": "カタログ離散ビーム探索",
            "targets": _target_summary(resolved),
            "discrete": _discrete_summary(discrete_result),
            "candidates": discrete_result.get("candidates", []),
            "topology": discrete_result.get("topology"),
        }

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

    if resolved["efl_weight"] > 0:
        problem.add_operand(
            operand_type="f2",
            target=target_efl,
            weight=sqrt(resolved["efl_weight"]) / resolved["efl_tolerance_mm"],
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

    start = overall_start
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
            score += _back_focus_penalty(image_distance, resolved)
            total_track = _current_total_track(system)
            score += _track_penalty(total_track, resolved)
            efl = float(system.paraxial.f2())
            if resolved["efl_hard"] and abs(efl - target_efl) > resolved["efl_tolerance_mm"]:
                score += 1e6 * ((abs(efl - target_efl) / resolved["efl_tolerance_mm"]) ** 2)
            if resolved["bfl_hard"] and not _back_focus_satisfied(image_distance, resolved):
                score += 1e6 * max(_back_focus_violation(image_distance, resolved), 1.0) ** 2
            if resolved["track_hard"] and not _track_satisfied(total_track, resolved):
                score += 1e6 * max(_track_violation(total_track, resolved), 1.0) ** 2
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

    if monotonic() >= deadline:
        initial_score = float(problem.sum_squared()) + _back_focus_penalty(design.elements[-1].gap_after_mm, resolved)
        initial_score += _track_penalty(_current_total_track(system), resolved)
        best_score = initial_score
    else:
        initial_score = objective(x0)
    try:
        if monotonic() >= deadline:
            raise OptimizationTimeLimit
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
    changes = (discrete_result.get("changes", []) if discrete_result else []) + _apply_variables_to_design(design, candidates, problem)
    if any(candidate.kind == "image_gap" for candidate in candidates):
        design.settings.auto_focus_enabled = False
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
    constraints_satisfied = (
        (not resolved["efl_hard"] or abs(float(system.paraxial.f2()) - target_efl) <= resolved["efl_tolerance_mm"])
        and (not resolved["bfl_hard"] or _back_focus_satisfied(design.elements[-1].gap_after_mm, resolved))
        and (not resolved["track_hard"] or _track_satisfied(_current_total_track(system), resolved))
    )
    ranked_candidates = _optimized_candidate_list(discrete_result, design, best_score, metrics, resolved)
    return {
        "valid": np.isfinite(best_score) and best_score < 1e29 and constraints_satisfied,
        "constraints_satisfied": constraints_satisfied,
        "design": design.to_dict(),
        "initial_score": initial_score,
        "best_score": best_score,
        "evaluations": evaluations + (discrete_result.get("evaluations", 0) if discrete_result else 0),
        "elapsed_seconds": monotonic() - overall_start,
        "variables": [asdict(candidate) for candidate in candidates],
        "changes": changes,
        "metrics": metrics,
        "options": _public_options(resolved),
        "method": (
            ("カタログ離散ビーム探索 + " if discrete_result else "")
            + ("Optiland実光線 / SciPy Powell" if resolved["method"] == "local" else "Optiland実光線 / SciPy differential evolution")
        ),
        "targets": _target_summary(resolved),
        "discrete": _discrete_summary(discrete_result),
        "candidates": ranked_candidates,
        "topology": discrete_result.get("topology") if discrete_result else None,
    }


def _normalized_positive(values: list[float], count: int) -> list[float]:
    result = [max(float(value), 0.0) for value in values[:count]]
    result.extend([1.0] * (count - len(result)))
    total = sum(result)
    return [value / total for value in result] if total > 0 else [1.0 / count] * count


def _target_summary(options: dict[str, Any]) -> dict[str, Any]:
    return {
        "effective_focal_length_mm": options["target_efl_mm"],
        "f_number": options["target_f_number"],
        "bfl_constraint": options["bfl_constraint"],
        "target_bfl_mm": options["target_bfl_mm"],
        "minimum_bfl_mm": options["minimum_bfl_mm"],
        "maximum_bfl_mm": options["maximum_bfl_mm"],
        "maximum_total_track_mm": options["maximum_total_track_mm"],
    }


def _discrete_summary(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {key: value for key, value in result.items() if key not in {"design", "candidates"}}


def _public_options(options: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in options.items()
        if key not in {"candidate_pool", "topology_pool", "classic_seed_design"}
    }


def _optimized_candidate_list(
    discrete_result: dict[str, Any] | None,
    design: OpticalDesign,
    score: float,
    metrics: dict[str, float | None],
    options: dict[str, Any],
) -> list[dict[str, Any]]:
    if discrete_result is None:
        return []
    candidates = list(discrete_result.get("candidates", []))
    optimized = {
        "rank": 1,
        "stage": "continuous_optimized",
        "score": score,
        "design": design.to_dict(),
        "metrics": metrics,
        "topology": discrete_result.get("topology"),
        "constraints_satisfied": True,
        "parts": _parts_summary(design),
    }
    result = [optimized, *candidates[1: options["result_count"]]]
    for rank, candidate in enumerate(result, 1):
        candidate["rank"] = rank
    return result


def _parts_summary(design: OpticalDesign) -> list[dict[str, Any]]:
    return [
        {
            "position": index + 1,
            "manufacturer": element.manufacturer,
            "part_number": element.part_number,
            "name": element.name,
            "shape": element.shape,
            "orientation_reversed": element.orientation_reversed,
            "diameter_mm": element.outer_diameter_mm,
            "gap_after_mm": element.gap_after_mm,
        }
        for index, element in enumerate(design.elements)
    ]


def _back_focus_violation(image_distance: float, options: dict[str, Any]) -> float:
    mode = options["bfl_constraint"]
    tolerance = options["bfl_tolerance_mm"]
    if mode == "off":
        return 0.0
    if mode == "target":
        return abs(image_distance - options["target_bfl_mm"]) / tolerance
    if mode == "minimum":
        return max(0.0, options["minimum_bfl_mm"] - image_distance) / tolerance
    if mode == "range":
        below = max(0.0, options["minimum_bfl_mm"] - image_distance)
        above = max(0.0, image_distance - options["maximum_bfl_mm"])
        return max(below, above) / tolerance
    return 0.0


def _back_focus_penalty(image_distance: float, options: dict[str, Any]) -> float:
    return options["bfl_weight"] * _back_focus_violation(image_distance, options) ** 2


def _back_focus_satisfied(image_distance: float, options: dict[str, Any]) -> bool:
    mode = options["bfl_constraint"]
    tolerance = options["bfl_tolerance_mm"]
    if mode == "target":
        return abs(image_distance - options["target_bfl_mm"]) <= tolerance
    if mode == "minimum":
        return image_distance >= options["minimum_bfl_mm"]
    if mode == "range":
        return options["minimum_bfl_mm"] <= image_distance <= options["maximum_bfl_mm"]
    return True


def _track_violation(total_track_mm: float, options: dict[str, Any]) -> float:
    maximum = options["maximum_total_track_mm"]
    if maximum is None:
        return 0.0
    return max(0.0, total_track_mm - maximum) / options["track_tolerance_mm"]


def _track_penalty(total_track_mm: float, options: dict[str, Any]) -> float:
    return options["track_weight"] * _track_violation(total_track_mm, options) ** 2


def _track_satisfied(total_track_mm: float, options: dict[str, Any]) -> bool:
    maximum = options["maximum_total_track_mm"]
    return maximum is None or total_track_mm <= maximum


def _current_image_distance(design, candidates, problem) -> float:
    for candidate, variable in zip(candidates, problem.variables, strict=True):
        if candidate.kind == "image_gap":
            return float(variable.variable.get_value())
    return design.elements[-1].gap_after_mm


def _current_total_track(system) -> float:
    return sum(float(surface.thickness) for surface in system.surface_group.surfaces[1:-1])


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
    edge_distortion = None
    mtf40_min = None
    try:
        from optiland.analysis import Distortion

        distortion = Distortion(
            system,
            wavelengths=[design.settings.primary_wavelength_um],
            num_points=5,
            distortion_type="f-tan",
        )
        edge_distortion = float(np.asarray(distortion.data, dtype=float).ravel()[-1])
    except Exception:
        pass
    try:
        from .performance import minimum_polychromatic_mtf

        mtf40_min = minimum_polychromatic_mtf(system, design, 40.0, 3)
    except Exception:
        pass
    total_track = sum(
        element.gap_after_mm + sum(surface.thickness_after_mm for surface in element.surfaces[:-1])
        for element in design.elements
    )
    return {
        "effective_focal_length_mm": float(system.paraxial.f2()),
        "image_f_number": float(system.paraxial.FNO()),
        "image_distance_mm": design.elements[-1].gap_after_mm,
        "maximum_rms_spot_um": max(spot_values, default=None),
        "mtf40_min": mtf40_min,
        "edge_distortion_percent": edge_distortion,
        "total_track_mm": total_track,
        "maximum_outer_diameter_mm": max((element.outer_diameter_mm for element in design.elements), default=None),
        "diffraction_airy_radius_um": 1.22
        * design.settings.primary_wavelength_um
        * design.settings.f_number_target,
    }
