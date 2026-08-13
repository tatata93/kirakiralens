from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict
from random import Random

from kirakiralens.domain import OpticalDesign
from kirakiralens.optics.automatic_design import normalized_automatic_options, run_automatic_design
from kirakiralens.optics.discrete_search import (
    _delete_element,
    _insert_catalog_element,
    _mutate,
    _score_design,
    _split_element_with_catalog,
)
from kirakiralens.optics.longitudinal import longitudinal_aberration_metrics
from kirakiralens.optics.mechanics import (
    ensure_air_gap_clearances,
    mechanical_clearance_violations,
    required_air_gap_mm,
)
from kirakiralens.optics.optiland_adapter import OptilandAdapter
from kirakiralens.optics.reference_designs import build_reference_design


def test_discrete_design_accepts_numeric_f_number_and_minimum_bfl() -> None:
    design = OpticalDesign.starter()
    design.elements[-1].gap_after_mm = 41.0
    result = run_automatic_design(
        design,
        {
            "discrete_search": True,
            "candidate_pool": [[asdict(element)] for element in design.elements],
            "discrete_evaluations": 1,
            "allow_orientation_search": False,
            "allow_order_search": False,
            "vary_radii": False,
            "vary_thicknesses": False,
            "vary_air_gaps": False,
            "vary_image_plane": False,
            "target_efl_mm": 50.0,
            "target_f_number": 5.6,
            "bfl_constraint": "minimum",
            "minimum_bfl_mm": 40.0,
            "bfl_hard": True,
            "spot_rings": 2,
            "longitudinal_weight": 4.0,
            "longitudinal_tolerance_um": 2000.0,
            "longitudinal_hard": True,
            "time_limit_seconds": 10,
        },
    )

    assert result["valid"], result.get("error")
    assert result["method"] == "カタログ離散ビーム探索"
    assert result["evaluations"] == 1
    assert result["targets"]["f_number"] == 5.6
    assert result["targets"]["minimum_bfl_mm"] == 40.0
    assert abs(result["metrics"]["image_f_number"] - 5.6) < 1e-6
    assert result["metrics"]["image_distance_mm"] == 41.0
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["parts"][0]["position"] == 1
    assert 0.0 <= result["candidates"][0]["metrics"]["mtf40_min"] <= 1.0
    assert 0.0 < result["metrics"]["longitudinal_rms_um"] < 2000.0
    assert result["targets"]["longitudinal_tolerance_um"] == 2000.0
    assert "candidate_pool" not in result["options"]
    json.dumps(result, allow_nan=False)


def test_discrete_mutation_respects_element_locks() -> None:
    design = OpticalDesign.starter()
    for element in design.elements:
        element.element_locked = True
    pools = [[element] for element in design.elements]

    changed = _mutate(
        design,
        pools,
        {"allow_orientation_search": True, "allow_order_search": True},
        Random(1),
    )

    assert changed is False


def test_topology_mutations_change_element_count_and_stop_surface() -> None:
    design = OpticalDesign.starter()
    original_image_distance = design.elements[-1].gap_after_mm
    inserted = design.elements[0].custom_copy()

    _insert_catalog_element(design, inserted, len(design.elements))

    assert len(design.elements) == 4
    assert design.elements[-1].gap_after_mm == original_image_distance
    assert design.elements[-1].id != design.elements[0].id

    _delete_element(design, len(design.elements) - 1)

    assert len(design.elements) == 3
    assert design.elements[-1].gap_after_mm == original_image_distance

    for element in design.elements:
        element.element_locked = True
    before_stop = (design.stop_after_element, design.stop_surface_index)
    changed = _mutate(
        design,
        [[element] for element in design.elements],
        {
            "allow_orientation_search": False,
            "allow_order_search": False,
            "allow_stop_search": True,
        },
        Random(2),
    )

    assert changed is True
    assert (design.stop_after_element, design.stop_surface_index) != before_stop


def test_topology_options_are_normalized() -> None:
    options = normalized_automatic_options(
        {
            "allow_element_count_search": True,
            "allow_stop_search": True,
            "minimum_element_count": 5,
            "maximum_element_count": 2,
            "allow_catalog_splitting": True,
            "maximum_split_count": 99,
        }
    )

    assert options["allow_element_count_search"] is True
    assert options["allow_stop_search"] is True
    assert options["minimum_element_count"] == 5
    assert options["maximum_element_count"] == 5
    assert options["allow_catalog_splitting"] is True
    assert options["maximum_split_count"] == 6
    assert options["minimum_edge_clearance_mm"] == 0.1


def test_curved_neighboring_lenses_are_separated_at_their_edges() -> None:
    design = OpticalDesign.starter()
    left = deepcopy(design.elements[1])
    right = deepcopy(design.elements[1])
    left.outer_diameter_mm = 20.0
    right.outer_diameter_mm = 20.0
    left.surfaces[0].radius_mm = None
    left.surfaces[0].clear_aperture_mm = 20.0
    left.surfaces[0].thickness_after_mm = 3.0
    left.surfaces[1].radius_mm = 20.0
    left.surfaces[1].clear_aperture_mm = 20.0
    right.surfaces[0].radius_mm = -20.0
    right.surfaces[0].clear_aperture_mm = 20.0
    right.surfaces[0].thickness_after_mm = 3.0
    right.surfaces[1].radius_mm = None
    right.surfaces[1].clear_aperture_mm = 20.0
    left.gap_after_mm = 0.1
    right.gap_after_mm = 20.0
    design.elements = [left, right]

    required = required_air_gap_mm(left, right, 0.1)

    assert required > 5.0
    assert mechanical_clearance_violations(design, 0.1) == ["L1-L2 collision"]
    assert ensure_air_gap_clearances(design, 0.1)
    assert abs(design.elements[0].gap_after_mm - required) < 1e-9
    assert mechanical_clearance_violations(design, 0.1) == []


def test_catalog_split_preserves_final_gap_and_moves_stop_with_group() -> None:
    design = OpticalDesign.starter()
    source = design.elements[0]
    source.gap_after_mm = 4.5
    source.gap_locked = True
    first = deepcopy(source)
    second = deepcopy(source)
    for product_id, element in enumerate((first, second), 101):
        element.is_catalog = True
        element.catalog_product_id = product_id
        element.manufacturer = "Test catalog"
        element.part_number = f"P{product_id}"

    _split_element_with_catalog(design, 0, [first, second])

    assert len(design.elements) == 4
    assert design.elements[0].gap_after_mm == 1.0
    assert design.elements[0].gap_locked is False
    assert design.elements[1].gap_after_mm == 4.5
    assert design.elements[1].gap_locked is True
    assert design.stop_after_element == 1
    assert design.stop_surface_index is None


def test_discrete_split_respects_maximum_lens_count_and_split_count() -> None:
    design = OpticalDesign.starter()
    positive = deepcopy(design.elements[0])
    negative = deepcopy(design.elements[1])
    for product_id, element in enumerate((positive, negative), 201):
        element.is_catalog = True
        element.catalog_product_id = product_id
    pools = [[deepcopy(element)] for element in design.elements]
    options = {
        "allow_orientation_search": False,
        "allow_order_search": False,
        "allow_catalog_splitting": True,
        "maximum_split_count": 2,
        "maximum_element_count": 4,
    }

    changed = _mutate(design, pools, options, Random(4), [positive, negative])

    assert changed is True
    assert len(design.elements) == 4

    blocked = OpticalDesign.starter()
    changed = _mutate(
        blocked,
        [[deepcopy(element)] for element in blocked.elements],
        {**options, "maximum_element_count": 3},
        Random(4),
        [positive, negative],
    )
    assert changed is False
    assert len(blocked.elements) == 3


def test_patent_rear_stop_keeps_image_distance_measured_from_last_lens() -> None:
    design = build_reference_design("triplet-jph07168095a-ex1")
    assert ensure_air_gap_clearances(design, 0.1)
    options = normalized_automatic_options(
        {
            "target_efl_mm": 100.0,
            "target_f_number": 2.78,
            "target_bfl_mm": 81.015,
            "vary_image_plane": True,
            "spot_rings": 2,
            "longitudinal_weight": 0.0,
            "distortion_weight": 0.0,
        }
    )

    score, focused, metrics = _score_design(design, options)

    assert score < 1e29
    assert metrics["image_distance_mm"] > focused.explicit_stop_offset_mm
    assert focused.elements[-1].gap_after_mm == metrics["image_distance_mm"]


def test_longitudinal_metric_traces_axis_rays_at_all_wavelengths() -> None:
    design = OpticalDesign.starter()
    system = OptilandAdapter().to_optic(design)

    metrics = longitudinal_aberration_metrics(
        system,
        design.settings.wavelengths_um,
        design.settings.wavelength_weights,
        design.settings.primary_wavelength_um,
    )

    assert metrics["rms_um"] > 0
    assert metrics["maximum_abs_um"] >= metrics["primary_lsa_um"] > 0
    assert metrics["axial_color_um"] > 0


def test_continuous_design_uses_longitudinal_aberration_objective() -> None:
    design = OpticalDesign.starter()
    for element in design.elements:
        element.element_locked = True
    design.elements[0].element_locked = False
    design.elements[0].is_catalog = False
    design.elements[0].surfaces[0].radius_locked = False

    result = run_automatic_design(
        design,
        {
            "vary_radii": True,
            "vary_air_gaps": False,
            "vary_image_plane": False,
            "max_evaluations": 12,
            "time_limit_seconds": 20,
            "efl_weight": 1.0,
            "bfl_weight": 0.0,
            "spot_weight": 0.0,
            "longitudinal_weight": 8.0,
            "longitudinal_tolerance_um": 100.0,
            "distortion_weight": 0.0,
            "track_weight": 0.0,
        },
    )

    assert result["valid"], result.get("error")
    assert result["evaluations"] == 12
    assert result["best_score"] < result["initial_score"]
    assert result["metrics"]["longitudinal_rms_um"] > 0
