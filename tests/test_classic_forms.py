from __future__ import annotations

from kirakiralens.domain import LensElement, OpticalDesign, SurfaceSpec
from kirakiralens.optics.classic_forms import CLASSIC_FORMS, build_classic_design, design_matches_form, form_summary


def _element(shape: str) -> LensElement:
    if shape == "achromatic_doublet":
        surfaces = [
            SurfaceSpec(50.0, "N-BK7", 3.0, 20.0),
            SurfaceSpec(-40.0, "N-SF5", 2.0, 20.0),
            SurfaceSpec(-100.0, "air", 0.0, 20.0),
        ]
    elif "concave" in shape:
        surfaces = [SurfaceSpec(-50.0, "N-SF5", 2.0, 20.0), SurfaceSpec(50.0, "air", 0.0, 20.0)]
    else:
        surfaces = [SurfaceSpec(50.0, "N-BK7", 3.0, 20.0), SurfaceSpec(-50.0, "air", 0.0, 20.0)]
    return LensElement(name=shape, shape=shape, surfaces=surfaces, outer_diameter_mm=25.0)


def test_classic_form_power_sequences_and_components() -> None:
    assert [slot.power for slot in CLASSIC_FORMS["triplet"].slots] == ["positive", "negative", "positive"]
    assert CLASSIC_FORMS["tessar"].slots[-1].shapes == ("achromatic_doublet",)
    assert [slot.power for slot in CLASSIC_FORMS["double_gauss"].slots] == [
        "positive",
        "positive",
        "negative",
        "negative",
        "positive",
        "positive",
    ]
    assert form_summary("tessar")["glass_count"] == 4


def test_classic_form_replaces_topology_and_sets_stop_and_image_distance() -> None:
    source = OpticalDesign.starter()
    form = CLASSIC_FORMS["tessar"]
    elements = [_element(slot.shapes[0]) for slot in form.slots]

    design = build_classic_design(source, "tessar", elements, target_efl_mm=50.0, image_distance_mm=45.46)

    assert design.name.startswith("Tessar")
    assert [element.shape for element in design.elements] == [
        "double_convex",
        "double_concave",
        "achromatic_doublet",
    ]
    assert design.stop_after_element == 1
    assert design.elements[-1].gap_after_mm == 45.46
    assert sum(len(element.surfaces) - 1 for element in design.elements) == 4
    assert design_matches_form(design, "tessar")
    design.elements[0], design.elements[1] = design.elements[1], design.elements[0]
    assert not design_matches_form(design, "tessar")
