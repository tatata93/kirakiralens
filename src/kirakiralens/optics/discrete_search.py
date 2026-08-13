from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from itertools import zip_longest
from random import Random
from time import monotonic
from typing import Any, Callable

import numpy as np

from ..domain import LensElement, OpticalDesign, lens_element_from_dict, new_id
from .configuration import resolved_field_weights
from .longitudinal import longitudinal_aberration_metrics
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
    topology_pool = [lens_element_from_dict(item) for item in options.get("topology_pool", [])]
    topology_search = bool(options.get("allow_element_count_search"))
    if topology_search and not topology_pool:
        return {"valid": False, "error": "自由構成探索に使う市販レンズ候補がありません"}
    if not topology_search and (len(pools) != len(source_design.elements) or any(not slot for slot in pools)):
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
        if not _mutate(parent, pools, options, random, topology_pool):
            break
        evaluate(parent)

    if not beam or not np.isfinite(beam[0].score) or beam[0].score >= 1e29:
        return {"valid": False, "error": "有効な市販レンズ構成が見つかりませんでした", "evaluations": evaluations}
    valid_beam = [item for item in beam if np.isfinite(item.score) and item.score < 1e29]
    _screen_top_mtf(valid_beam, options, deadline, progress, evaluations, start)
    best = valid_beam[0]
    candidates = [
        _candidate_summary(
            rank,
            item,
            _topology_summary(item.design, options),
            _constraints_satisfied(item.metrics, options),
        )
        for rank, item in enumerate(valid_beam[: options["result_count"]], 1)
    ]
    topology = _topology_summary(best.design, options)
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


def _mutate(
    design: OpticalDesign,
    pools: list[list[LensElement]],
    options: dict[str, Any],
    random: Random,
    topology_pool: list[LensElement] | None = None,
) -> bool:
    topology_pool = topology_pool or []
    topology_search = bool(options.get("allow_element_count_search"))
    replacements: dict[int, list[LensElement]] = {}
    for index, element in enumerate(design.elements):
        if element.element_locked:
            continue
        source_pool = topology_pool if topology_search else (pools[index] if index < len(pools) else [])
        alternatives = [candidate for candidate in source_pool if _element_identity(candidate) != _element_identity(element)]
        if alternatives:
            replacements[index] = alternatives
    replaceable = list(replacements)
    reversible = [
        index
        for index, element in enumerate(design.elements)
        if not element.element_locked and not element.orientation_locked
    ]
    reorderable = [index for index, element in enumerate(design.elements) if not element.element_locked]
    insertable = [
        index
        for index in range(len(design.elements) + 1)
        if index == 0
        or (
            not design.elements[index - 1].element_locked
            and not design.elements[index - 1].gap_locked
        )
    ]
    deletable = [
        index
        for index, element in enumerate(design.elements)
        if not element.element_locked
        and not element.gap_locked
        and (
            index == 0
            or (
                not design.elements[index - 1].element_locked
                and not design.elements[index - 1].gap_locked
            )
        )
    ]
    actions: list[str] = []
    if replaceable:
        actions.extend(["replace", "replace"])
    if options.get("allow_orientation_search", False) and reversible:
        actions.append("reverse")
    if options.get("allow_order_search", False) and len(reorderable) >= 2:
        actions.append("swap")
    if (
        topology_search
        and topology_pool
        and insertable
        and len(design.elements) < options.get("maximum_element_count", 8)
    ):
        actions.extend(["insert", "insert"])
    if topology_search and len(design.elements) > options.get("minimum_element_count", 1) and deletable:
        actions.append("delete")
    if options.get("allow_stop_search", False) and _available_stop_positions(design):
        actions.append("stop")
    if not actions:
        return False

    action = random.choice(actions)
    if action == "replace":
        index = random.choice(replaceable)
        old = design.elements[index]
        candidate = deepcopy(random.choice(replacements[index]))
        candidate.id = old.id
        candidate.gap_after_mm = old.gap_after_mm
        candidate.gap_locked = old.gap_locked
        candidate.gap_min_mm = old.gap_min_mm
        candidate.gap_max_mm = old.gap_max_mm
        candidate.diameter_min_mm = old.diameter_min_mm
        candidate.diameter_max_mm = old.diameter_max_mm
        candidate.element_locked = old.element_locked
        candidate.orientation_locked = old.orientation_locked
        design.elements[index] = candidate
        if design.stop_after_element == index and design.stop_surface_index is not None:
            design.stop_surface_index = min(design.stop_surface_index, len(candidate.surfaces) - 1)
    elif action == "reverse":
        index = random.choice(reversible)
        surface_count = len(design.elements[index].surfaces)
        design.elements[index].reverse()
        if design.stop_after_element == index and design.stop_surface_index is not None:
            design.stop_surface_index = surface_count - 1 - design.stop_surface_index
    elif action == "swap":
        first, second = random.sample(reorderable, 2)
        first_gap = _gap_state(design.elements[first])
        second_gap = _gap_state(design.elements[second])
        design.elements[first], design.elements[second] = design.elements[second], design.elements[first]
        _set_gap_state(design.elements[first], first_gap)
        _set_gap_state(design.elements[second], second_gap)
    elif action == "insert":
        _insert_catalog_element(design, deepcopy(random.choice(topology_pool)), random.choice(insertable))
    elif action == "delete":
        _delete_element(design, random.choice(deletable))
    else:
        positions = _available_stop_positions(design)
        design.stop_after_element, design.stop_surface_index = random.choice(positions)
        design.explicit_stop_after_element = None
    return True


def _insert_catalog_element(design: OpticalDesign, element: LensElement, index: int) -> None:
    index = min(max(index, 0), len(design.elements))
    element.id = new_id()
    element.element_locked = False
    element.orientation_locked = False
    element.gap_locked = False
    element.gap_min_mm = 0.0
    element.gap_max_mm = None
    element.gap_after_mm = 1.0
    if index > 0:
        previous = design.elements[index - 1]
        original_gap = previous.gap_after_mm
        if index == len(design.elements):
            previous.gap_after_mm = min(max(original_gap * 0.1, 0.1), 2.0)
            element.gap_after_mm = max(original_gap, 0.1)
        else:
            internal_thickness = sum(surface.thickness_after_mm for surface in element.surfaces[:-1])
            previous.gap_after_mm = min(max(original_gap * 0.25, 0.1), 1.0)
            element.gap_after_mm = max(original_gap - previous.gap_after_mm - internal_thickness, 0.1)
    design.elements.insert(index, element)
    if index <= design.stop_after_element:
        design.stop_after_element += 1
    if design.explicit_stop_after_element is not None and index <= design.explicit_stop_after_element:
        design.explicit_stop_after_element += 1


def _delete_element(design: OpticalDesign, index: int) -> None:
    if len(design.elements) <= 1 or not 0 <= index < len(design.elements):
        return
    old_count = len(design.elements)
    removed = design.elements.pop(index)
    if index > 0:
        previous = design.elements[index - 1]
        if index == old_count - 1:
            previous.gap_after_mm = max(removed.gap_after_mm, previous.gap_min_mm)
        else:
            internal_thickness = sum(surface.thickness_after_mm for surface in removed.surfaces[:-1])
            previous.gap_after_mm += internal_thickness + removed.gap_after_mm
        if previous.gap_max_mm is not None:
            previous.gap_after_mm = min(previous.gap_after_mm, previous.gap_max_mm)
    if design.stop_after_element > index:
        design.stop_after_element -= 1
    elif design.stop_after_element == index:
        design.stop_after_element = max(0, index - 1)
        design.stop_surface_index = None
    if design.explicit_stop_after_element is not None:
        if design.explicit_stop_after_element > index:
            design.explicit_stop_after_element -= 1
        elif design.explicit_stop_after_element == index:
            design.explicit_stop_after_element = None
    design.stop_after_element = min(design.stop_after_element, len(design.elements) - 1)


def _available_stop_positions(design: OpticalDesign) -> list[tuple[int, int]]:
    stop_element = min(max(design.stop_after_element, 0), len(design.elements) - 1)
    current_surface = design.stop_surface_index
    if design.elements and current_surface is None:
        current_surface = len(design.elements[stop_element].surfaces) - 1
    return [
        (element_index, surface_index)
        for element_index, element in enumerate(design.elements)
        for surface_index in range(len(element.surfaces))
        if (element_index, surface_index) != (stop_element, current_surface)
    ]


def _element_identity(element: LensElement) -> tuple[object, ...]:
    if element.catalog_product_id is not None:
        return ("catalog", element.catalog_product_id, element.orientation_reversed)
    return (
        "custom",
        element.manufacturer,
        element.part_number,
        element.name,
        tuple(surface.radius_mm for surface in element.surfaces),
        element.orientation_reversed,
    )


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
        if options.get("allow_element_count_search") and not (
            options["minimum_element_count"] <= len(design.elements) <= options["maximum_element_count"]
        ):
            raise ValueError("element count constraint violated")
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

        longitudinal: dict[str, float] = {}
        if options["longitudinal_weight"] > 0 or options["longitudinal_hard"]:
            longitudinal = longitudinal_aberration_metrics(
                system,
                wavelengths,
                design.settings.wavelength_weights,
                design.settings.primary_wavelength_um,
            )
            score += options["longitudinal_weight"] * (
                longitudinal["rms_um"] / options["longitudinal_tolerance_um"]
            ) ** 2
            if options["longitudinal_hard"] and longitudinal["rms_um"] > options["longitudinal_tolerance_um"]:
                score += 1e6 * max(
                    longitudinal["rms_um"] / options["longitudinal_tolerance_um"],
                    1.0,
                ) ** 2

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
            "longitudinal_rms_um": longitudinal.get("rms_um"),
            "maximum_longitudinal_aberration_um": longitudinal.get("maximum_abs_um"),
            "primary_longitudinal_spherical_um": longitudinal.get("primary_lsa_um"),
            "axial_color_um": longitudinal.get("axial_color_um"),
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
            "longitudinal_rms_um": None,
            "maximum_longitudinal_aberration_um": None,
            "primary_longitudinal_spherical_um": None,
            "axial_color_um": None,
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


def _topology_summary(design: OpticalDesign, options: dict[str, Any]) -> dict[str, object] | None:
    classic = form_summary(options.get("classic_form", ""))
    if classic is not None:
        return classic
    stop_element = min(max(design.stop_after_element, 0), len(design.elements) - 1)
    stop_surface = design.stop_surface_index
    if stop_surface is None:
        stop_surface = len(design.elements[stop_element].surfaces) - 1
    label = f"自由構成 {len(design.elements)}部品 / 絞り L{stop_element + 1} S{stop_surface + 1}"
    return {
        "key": "free_topology" if options.get("allow_element_count_search") else "free",
        "label": label,
        "component_count": len(design.elements),
        "glass_count": sum(len(element.surfaces) - 1 for element in design.elements),
        "stop_element": stop_element,
        "stop_surface": stop_surface,
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
    longitudinal_rms = metrics.get("longitudinal_rms_um")
    if options["longitudinal_hard"] and (
        longitudinal_rms is None or longitudinal_rms > options["longitudinal_tolerance_um"]
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
    if len(before.elements) != len(after.elements):
        changes.append({"label": "部品数", "before": len(before.elements), "after": len(after.elements)})
    for index, (old, new) in enumerate(zip_longest(before.elements, after.elements)):
        if old is None or new is None:
            changes.append(
                {
                    "label": f"L{index + 1} 型番・向き",
                    "before": "-" if old is None else _element_label(old),
                    "after": "-" if new is None else _element_label(new),
                }
            )
            continue
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
    before_stop = _stop_label(before)
    after_stop = _stop_label(after)
    if before_stop != after_stop:
        changes.append({"label": "絞り位置", "before": before_stop, "after": after_stop})
    return changes


def _element_label(element: LensElement) -> str:
    name = " / ".join(item for item in (element.manufacturer, element.part_number or element.name) if item)
    return name + (" (反転)" if element.orientation_reversed else "")


def _stop_label(design: OpticalDesign) -> str:
    if not design.elements:
        return "-"
    element_index = min(max(design.stop_after_element, 0), len(design.elements) - 1)
    surface_index = design.stop_surface_index
    if surface_index is None:
        surface_index = len(design.elements[element_index].surfaces) - 1
    return f"L{element_index + 1} S{surface_index + 1}"
