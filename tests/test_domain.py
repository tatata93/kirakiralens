from __future__ import annotations

from kirakiralens.domain import LensElement, OpticalDesign, SurfaceSpec


def test_cemented_doublet_reversal_preserves_media_and_thicknesses() -> None:
    element = LensElement(
        name="doublet",
        outer_diameter_mm=20,
        surfaces=[
            SurfaceSpec(30, "N-BK7", 3, 18, "front"),
            SurfaceSpec(-25, "N-SF5", 2, 18, "cement"),
            SurfaceSpec(-60, "air", 0, 18, "rear"),
        ],
    )

    element.reverse()

    assert [surface.radius_mm for surface in element.surfaces] == [60, 25, -30]
    assert [surface.material_after for surface in element.surfaces] == ["N-SF5", "N-BK7", "air"]
    assert [surface.thickness_after_mm for surface in element.surfaces] == [2, 3, 0]
    assert [surface.coating for surface in element.surfaces] == ["rear", "cement", "front"]


def test_design_dictionary_uses_strict_json_value_for_infinity() -> None:
    design = OpticalDesign.starter()
    data = design.to_dict()

    assert data["settings"]["object_distance_mm"] == "infinity"
    restored = OpticalDesign.from_dict(data)
    assert restored.settings.object_distance_mm == float("inf")


def test_older_designs_default_to_automatic_image_focus() -> None:
    data = OpticalDesign.starter().to_dict()
    del data["settings"]["auto_focus_enabled"]

    restored = OpticalDesign.from_dict(data)

    assert restored.settings.auto_focus_enabled is True


def test_aperture_modes_round_trip_and_estimate_f_number() -> None:
    design = OpticalDesign.starter()
    design.settings.aperture_mode = "entrance_pupil_diameter"
    design.settings.set_aperture_value(10.0)

    restored = OpticalDesign.from_dict(design.to_dict())

    assert restored.settings.aperture_mode == "entrance_pupil_diameter"
    assert restored.settings.aperture_value == 10.0
    assert restored.settings.estimated_f_number() == 5.0
