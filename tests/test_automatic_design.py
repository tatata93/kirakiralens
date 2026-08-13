from __future__ import annotations

import json
from dataclasses import asdict
from random import Random

from kirakiralens.domain import OpticalDesign
from kirakiralens.optics.automatic_design import normalized_automatic_options, run_automatic_design
from kirakiralens.optics.discrete_search import _delete_element, _insert_catalog_element, _mutate


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
        }
    )

    assert options["allow_element_count_search"] is True
    assert options["allow_stop_search"] is True
    assert options["minimum_element_count"] == 5
    assert options["maximum_element_count"] == 5
