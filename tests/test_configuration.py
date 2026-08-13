from __future__ import annotations

from kirakiralens.domain import DesignSettings, OpticalDesign
from kirakiralens.optics.automatic_design import variable_candidates
from kirakiralens.optics.configuration import resolved_field_angles, sensor_angle_of_view


def test_sensor_fields_follow_sensor_diagonal_and_target_focal_length() -> None:
    settings = DesignSettings(sensor_width_mm=36.0, sensor_height_mm=24.0, focal_length_target_mm=50.0)
    angles = sensor_angle_of_view(settings)

    assert 39.5 < angles["horizontal_deg"] < 39.7
    assert 26.9 < angles["vertical_deg"] < 27.1
    assert 46.7 < angles["diagonal_deg"] < 47.0
    assert resolved_field_angles(settings) == [0.0, angles["maximum_half_angle_deg"] * 0.7, angles["maximum_half_angle_deg"]]


def test_field_values_and_weights_are_sorted_together() -> None:
    settings = DesignSettings(field_mode="angles", field_angles_deg=[20, 0, 10], field_weights=[3, 1, 2])
    settings.normalize()

    assert settings.field_angles_deg == [0.0, 10.0, 20.0]
    assert settings.field_weights == [1.0, 2.0, 3.0]


def test_automatic_design_preserves_catalog_and_locked_variables() -> None:
    design = OpticalDesign.starter()
    design.elements[0].is_catalog = True
    design.elements[1].surfaces[0].radius_locked = True
    design.elements[1].gap_locked = True

    candidates = variable_candidates(design)
    labels = {candidate.label for candidate in candidates}

    assert not any(label.startswith("L1 S") and "曲率半径" in label for label in labels)
    assert "L2 S1 曲率半径" not in labels
    assert "L2 後方空気間隔" not in labels
    assert "像面位置" in labels

    fixed_image_labels = {candidate.label for candidate in variable_candidates(design, {"vary_image_plane": False})}
    assert "像面位置" not in fixed_image_labels


def test_numeric_minimum_bfl_expands_the_automatic_image_bound() -> None:
    design = OpticalDesign.starter()
    candidates = variable_candidates(
        design,
        {
            "bfl_constraint": "minimum",
            "minimum_bfl_mm": 250.0,
            "bfl_tolerance_mm": 0.5,
        },
    )
    image_candidate = next(candidate for candidate in candidates if candidate.kind == "image_gap")

    assert image_candidate.maximum >= 250.5
