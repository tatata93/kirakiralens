from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from random import Random
from time import monotonic
from typing import Any, Callable

import numpy as np

from ..domain import LensElement, OpticalDesign, lens_element_from_dict
from .configuration import resolved_field_weights
from .classic_forms import design_matches_form, form_summary
from .optiland_adapter import OptilandAdapter
from .signature import analysis_signature


@dataclass(slots=True)
class ScoredDesign:
    score: float
    design: OpticalDesign
    metrics: dict[str, float | None]


def run_discrete_search(
    source_design: OpticalDesign,
    options: dict[str, Any],
    deadline: float,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    pools = [
        [lens_element_from_dict(item) for item in slot]
        for slot in options.get("candidate_pool", [])
    ]
    if len(pools) != len(source_design.elements) or any(not slot for slot in pools):
        return {"valid": False, "error": "離散探索候補がありません"}

    random = Random(options["seed"])
    evaluation_limit = options["discrete_evaluations"]
    beam_width = max(options["discrete_beam_width"], options["result_count"])
    start = monotonic()
    seen: set[str] = set()
    beam: list[ScoredDesign] = []
    evaluations = 0
    attempts = 0
    initial_score: float | None = None

    def evaluate(design: OpticalDesign) -> None:
        nonlocal evaluations, initial_score
        signature = analysis_signature(design)
        if signature in seen or evaluations >= evaluation_limit or monotonic() >= deadline:
            return
        seen.add(signature)
        evaluations += 1
        score, focused, metrics = _score_design(design, options)
        if initial_score is None:
            initial_score = score
        beam.append(ScoredDesign(score, focused, metrics))
        beam.sort(key=lambda item: item.score)
        del beam[beam_width:]
        if progress is not None:
            progress(
                {
                    "phase": "離散探索",
                    "evaluations": evaluations,
                    "best_score": beam[0].score,
                    "elapsed_seconds": monotonic() - start,
                    "time_limit_seconds": options["time_limit_seconds"],
                }
            )

    evaluate(deepcopy(source_design))
    maximum_attempts = max(evaluation_limit * 25, 100)
    while evaluations < evaluation_limit and attempts < maximum_attempts and monotonic() < deadline:
        attempts += 1
        parent = deepcopy(random.choice(beam).design)
        if not _mutate(parent, pools, options, random):
            break
        evaluate(parent)

    if not beam or not np.isfinite(beam[0].score) or beam[0].score >= 1e29:
        return {"valid": False, "error": "有効な市販レンズ構成が見つかりませんでした", "evaluations": evaluations}
    valid_beam = [item for item in beam if np.isfinite(item.score) and item.score < 1e29]
    _screen_top_mtf(valid_beam, options, deadline, progress, evaluations, start)
    best = valid_beam[0]
    topology = form_summary(options.get("classic_form", ""))
    candidates = [
        _candidate_summary(rank, item, topology, _constraints_satisfied(item.metrics, options))
        for rank, item in enumerate(valid_beam[: options["result_count"]], 1)
    ]
    return {
        "valid": True,
        "constraints_satisfied": _constraints_satisfied(best.metrics, options),
        "design": best.design,
        "initial_score": initial_score,
        "best_score": best.score,
        "evaluations": evaluations,
        "metrics": best.metrics,
        "changes": _identity_changes(source_design, best.design),
        "candidates": candidates,
        "topology": topology,
    }


def _mutate(design: OpticalDesign, pools: list[list[LensElement]], options: dict[str, Any], random: Random) -> bool:
    replaceable = [index for index, element in enumerate(design.elements) if not element.element_locked and len(pools[index]) > 1]
    reversible = [
        index
        for index, element in enumerate(design.elements)
        if not element.element_locked and not element.orientation_locked
    ]
    reorderable = [index for index, element in enumerate(design.elements) if not element.element_locked]
    actions: list[str] = []
    if replaceable:
        actions.extend(["replace", "replace"])
    if options["allow_orientation_search"] and reversible:
        actions.append("reverse")
    if options["allow_order_search"] and len(reorderable) >= 2:
        actions.append("swap")
    if not actions:
        return False

    action = random.choice(actions)
    if action == "replace":
        index = random.choice(replaceable)
        old = design.elements[index]
        candidate = deepcopy(random.choice(pools[index]))
        candidate.gap_after_mm = old.gap_after_mm
        candidate.gap_locked = old.gap_locked
        candidate.gap_min_mm = old.gap_min_mm
        candidate.gap_max_mm = old.gap_max_mm
        candidate.diameter_min_mm = old.diameter_min_mm
        candidate.diameter_max_mm = old.diameter_max_mm
        candidate.element_locked = old.element_locked
        candidate.orientation_locked = old.orientation_locked
        design.elements[index] = candidate
    elif action == "reverse":
        index = random.choice(reversible)
        design.elements[index].reverse()
    else:
        first, second = random.sample(reorderable, 2)
        first_gap = _gap_state(design.elements[first])
        second_gap = _gap_state(design.elements[second])
        design.elements[first], design.elements[second] = design.elements[second], design.elements[first]
        _set_gap_state(design.elements[first], first_gap)
        _set_gap_state(design.elements[second], second_gap)
    return True


def _gap_state(element: LensElement) -> tuple[float, bool, float, float | None]:
    return element.gap_after_mm, element.gap_locked, element.gap_min_mm, element.gap_max_mm


def _set_gap_state(element: LensElement, state: tuple[float, bool, float, float | None]) -> None:
    element.gap_after_mm, element.gap_locked, element.gap_min_mm, element.gap_max_mm = state


def _score_design(source: OpticalDesign, options: dict[str, Any]) -> tuple[float, OpticalDesign, dict[str, float | None]]:
    from optiland.analysis import Distortion, SpotDiagram

    design = deepcopy(source)
    design.settings.focal_length_target_mm = options["target_efl_mm"]
    design.settings.f_number_target = options["target_f_number"]
    try:
        if not design_matches_form(design, options.get("classic_form", "")):
            raise ValueError("classic form constraint violated")
        if not _mechanically_valid(design):
            raise ValueError("mechanical bounds violated")
        system = OptilandAdapter().to_optic(design)
        if (
            options["vary_image_plane"]
            and not design.elements[-1].element_locked
            and not design.elements[-1].gap_locked
        ):
            system.image_solve()
            image_distance = max(0.0, float(system.surface_group.surfaces[-2].thickness))
            final_element = design.elements[-1]
            image_distance = max(final_element.gap_min_mm, image_distance)
            if final_element.gap_max_mm is not None:
                image_distance = min(final_element.gap_max_mm, image_distance)
            system.surface_group.surfaces[-2].thickness = image_distance
            system.update()
            design.elements[-1].gap_after_mm = image_distance
        else:
            image_distance = design.elements[-1].gap_after_mm
        efl = float(system.paraxial.f2())
        total_track = _total_track_mm(design)
        score = options["efl_weight"] * ((efl - options["target_efl_mm"]) / options["efl_tolerance_mm"]) ** 2
        score += options["bfl_weight"] * _bfl_violation(image_distance, options) ** 2
        score += options["track_weight"] * _track_violation(total_track, options) ** 2
        if options["efl_hard"] and abs(efl - options["target_efl_mm"]) > options["efl_tolerance_mm"]:
            score += 1e6 * ((abs(efl - options["target_efl_mm"]) / options["efl_tolerance_mm"]) ** 2)
        if options["bfl_hard"] and _bfl_violation(image_distance, options) > 0:
            score += 1e6 * max(_bfl_violation(image_distance, options), 1.0) ** 2
        if options["track_hard"] and _track_violation(total_track, options) > 0:
            score += 1e6 * max(_track_violation(total_track, options), 1.0) ** 2

        fields = [tuple(map(float, field)) for field in system.fields.get_field_coords()]
        wavelengths = [float(value) for value in system.wavelengths.get_wavelengths()]
        field_weights = _normalize(resolved_field_weights(design.settings), len(fields))
        wavelength_weights = _normalize(design.settings.wavelength_weights, len(wavelengths))
        airy_mm = max(1.22 * design.settings.primary_wavelength_um * 1e-3 * options["target_f_number"], 1e-5)
        spots = SpotDiagram(
            system,
            fields=fields,
            wavelengths=wavelengths,
            num_rings=min(options["spot_rings"], 3),
            distribution="hexapolar",
        ).rms_spot_radius()
        maximum_spot = 0.0
        for field_index, field_data in enumerate(spots):
            for wavelength_index, value in enumerate(field_data):
                rms = float(value)
                maximum_spot = max(maximum_spot, rms)
                share = field_weights[field_index] * wavelength_weights[wavelength_index]
                score += options["spot_weight"] * share * (rms / airy_mm) ** 2

        edge_distortion = None
        if options["distortion_weight"] > 0:
            distortion = Distortion(system, wavelengths=[design.settings.primary_wavelength_um], num_points=5, distortion_type="f-tan")
            edge_distortion = float(np.asarray(distortion.data, dtype=float).ravel()[-1])
            score += options["distortion_weight"] * (edge_distortion / 2.0) ** 2
        if not np.isfinite(score):
            raise ValueError("non-finite merit")
        return score, design, {
            "effective_focal_length_mm": efl,
            "image_f_number": float(system.paraxial.FNO()),
            "image_distance_mm": image_distance,
            "maximum_rms_spot_um": maximum_spot * 1000.0,
            "edge_distortion_percent": edge_distortion,
            "total_track_mm": total_track,
            "maximum_outer_diameter_mm": max(element.outer_diameter_mm for element in design.elements),
            "mtf40_min": None,
        }
    except Exception:
        return 1e30, design, {
            "effective_focal_length_mm": None,
            "image_f_number": None,
            "image_distance_mm": design.elements[-1].gap_after_mm,
            "maximum_rms_spot_um": None,
            "edge_distortion_percent": None,
            "total_track_mm": None,
            "maximum_outer_diameter_mm": None,
            "mtf40_min": None,
        }


def _mechanically_valid(design: OpticalDesign) -> bool:
    for element in design.elements:
        if element.outer_diameter_mm > design.settings.max_outer_diameter_mm:
            return False
        if element.diameter_min_mm is not None and element.outer_diameter_mm < element.diameter_min_mm:
            return False
        if element.diameter_max_mm is not None and element.outer_diameter_mm > element.diameter_max_mm:
            return False
        if element.gap_after_mm < element.gap_min_mm:
            return False
        if element.gap_max_mm is not None and element.gap_after_mm > element.gap_max_mm:
            return False
    return True


def _total_track_mm(design: OpticalDesign) -> float:
    return sum(
        element.gap_after_mm + sum(surface.thickness_after_mm for surface in element.surfaces[:-1])
        for element in design.elements
    )


def _screen_top_mtf(
    beam: list[ScoredDesign],
    options: dict[str, Any],
    deadline: float,
    progress: Callable[[dict[str, Any]], None] | None,
    evaluations: int,
    start: float,
) -> None:
    from .performance import minimum_polychromatic_mtf

    for index, item in enumerate(beam[: options["mtf_screen_count"]]):
        if monotonic() >= deadline:
            return
        try:
            system = OptilandAdapter().to_optic(item.design)
            item.metrics["mtf40_min"] = minimum_polychromatic_mtf(system, item.design, 40.0, 3)
        except Exception:
            item.metrics["mtf40_min"] = None
        if progress is not None:
            progress(
                {
                    "phase": "上位候補MTF",
                    "evaluations": evaluations,
                    "mtf_candidates_done": index + 1,
                    "best_score": beam[0].score,
                    "elapsed_seconds": monotonic() - start,
                    "time_limit_seconds": options["time_limit_seconds"],
                }
            )


def _candidate_summary(
    rank: int,
    item: ScoredDesign,
    topology: dict[str, object] | None,
    constraints_satisfied: bool,
) -> dict[str, Any]:
    return {
        "rank": rank,
        "stage": "discrete_coarse",
        "score": item.score,
        "design": item.design.to_dict(),
        "metrics": item.metrics,
        "topology": topology,
        "constraints_satisfied": constraints_satisfied,
        "parts": [
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
            for index, element in enumerate(item.design.elements)
        ],
    }


def _normalize(values: list[float], count: int) -> list[float]:
    clean = [max(float(value), 0.0) for value in values[:count]]
    clean.extend([1.0] * (count - len(clean)))
    total = sum(clean)
    return [value / total for value in clean] if total > 0 else [1.0 / count] * count


def _bfl_violation(image_distance: float, options: dict[str, Any]) -> float:
    mode = options["bfl_constraint"]
    tolerance = options["bfl_tolerance_mm"]
    if mode == "target":
        return abs(image_distance - options["target_bfl_mm"]) / tolerance
    if mode == "minimum":
        return max(0.0, options["minimum_bfl_mm"] - image_distance) / tolerance
    if mode == "range":
        return max(
            max(0.0, options["minimum_bfl_mm"] - image_distance),
            max(0.0, image_distance - options["maximum_bfl_mm"]),
        ) / tolerance
    return 0.0


def _constraints_satisfied(metrics: dict[str, float | None], options: dict[str, Any]) -> bool:
    efl = metrics.get("effective_focal_length_mm")
    image_distance = metrics.get("image_distance_mm")
    if options["efl_hard"] and (
        efl is None or abs(efl - options["target_efl_mm"]) > options["efl_tolerance_mm"]
    ):
        return False
    if options["bfl_hard"] and (
        image_distance is None or _bfl_violation(image_distance, options) > 0
    ):
        return False
    total_track = metrics.get("total_track_mm")
    if options["track_hard"] and (
        total_track is None or _track_violation(total_track, options) > 0
    ):
        return False
    return True


def _track_violation(total_track_mm: float, options: dict[str, Any]) -> float:
    maximum = options["maximum_total_track_mm"]
    if maximum is None:
        return 0.0
    return max(0.0, total_track_mm - maximum) / options["track_tolerance_mm"]


def _identity_changes(before: OpticalDesign, after: OpticalDesign) -> list[dict[str, Any]]:
    changes = []
    for index, (old, new) in enumerate(zip(before.elements, after.elements, strict=False)):
        old_name = " / ".join(item for item in (old.manufacturer, old.part_number or old.name) if item)
        new_name = " / ".join(item for item in (new.manufacturer, new.part_number or new.name) if item)
        if old_name != new_name or old.orientation_reversed != new.orientation_reversed:
            changes.append(
                {
                    "label": f"L{index + 1} 型番・向き",
                    "before": old_name + (" (反転)" if old.orientation_reversed else ""),
                    "after": new_name + (" (反転)" if new.orientation_reversed else ""),
                }
            )
    return changes
