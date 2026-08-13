from __future__ import annotations

from pathlib import Path

from kirakiralens.domain import OpticalDesign
from kirakiralens.optics.optiland_adapter import OptilandAdapter
from kirakiralens.optics.paraxial import trace_parallel_rays


def test_starter_prescription_matches_initial_targets(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "matplotlib"))
    design = OpticalDesign.starter()
    result = OptilandAdapter().analyze_first_order(design)

    assert result.valid, result.error
    assert result.engine == "Optiland 0.5.9"
    assert abs(result.effective_focal_length_mm - 50.0) < 0.01
    assert abs(result.back_focal_length_mm - 45.46) < 0.01
    assert result.image_distance_mm == design.elements[-1].gap_after_mm
    assert abs(result.recommended_image_distance_mm - 45.46) < 0.01
    rays = trace_parallel_rays(design, result.refractive_indices)
    assert len(rays) == design.settings.layout_ray_count * len(design.settings.field_fractions)
    assert all(len(ray.points) == 7 for ray in rays)
    assert {ray.field_index for ray in rays} == {0, 1, 2}
    assert result.angle_of_view_diagonal_deg is not None
    assert 46.0 < result.angle_of_view_diagonal_deg < 47.0


def test_even_asphere_is_passed_to_optiland(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "matplotlib"))
    design = OpticalDesign.starter()
    surface = design.elements[0].surfaces[0]
    surface.surface_type = "even_asphere"
    surface.conic = -0.5
    surface.asphere_coefficients = [0.0, 1e-7]
    design.stop_after_element = 0
    design.stop_surface_index = 0

    adapter = OptilandAdapter()
    system = adapter.to_optic(design)
    result = adapter.analyze_first_order(design)

    assert result.valid, result.error
    assert result.effective_focal_length_mm is not None
    assert system.surface_group.stop_index == 1


def test_configured_fields_wavelengths_and_weights_reach_optiland(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "matplotlib"))
    design = OpticalDesign.starter()
    design.settings.field_mode = "angles"
    design.settings.field_angles_deg = [0.0, 12.5, 24.0]
    design.settings.wavelengths_um = [0.48613, 0.58756, 0.65627]
    design.settings.wavelength_weights = [0.5, 2.0, 1.5]

    system = OptilandAdapter().to_optic(design)

    assert list(system.fields.y_fields) == [0.0, 12.5, 24.0]
    assert list(system.wavelengths.get_wavelengths()) == design.settings.wavelengths_um
    assert [wavelength.weight for wavelength in system.wavelengths.wavelengths] == [0.5, 2.0, 1.5]


def test_recommended_image_distance_tracks_the_lens_focus(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "matplotlib"))
    design = OpticalDesign.starter()
    design.elements[-1].gap_after_mm = 30.0

    result = OptilandAdapter().analyze_first_order(design)

    assert result.valid, result.error
    assert result.back_focal_length_mm == 30.0
    assert result.image_distance_mm == 30.0
    assert abs(result.recommended_image_distance_mm - 45.46) < 0.01
