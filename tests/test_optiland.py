from __future__ import annotations

from pathlib import Path

from kirakiralens.domain import DesignSettings, LensElement, OpticalDesign, SurfaceSpec
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
    assert result.layout_ray_model == "Optiland sequential real rays"
    assert result.layout_ray_wavelength_um == design.settings.primary_wavelength_um
    assert len(result.layout_rays) == design.settings.layout_ray_count * len(design.settings.field_fractions)
    rays = trace_parallel_rays(design, result.refractive_indices)
    assert len(rays) == design.settings.layout_ray_count * len(design.settings.field_fractions)
    assert all(len(ray.points) == 8 for ray in rays)
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


def test_f_number_entrance_pupil_and_stop_radius_apertures_reach_optiland(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "matplotlib"))
    adapter = OptilandAdapter()
    expected = {
        "image_f_number": (5.6, "imageFNO", 5.6),
        "entrance_pupil_diameter": (10.0, "EPD", 10.0),
        "stop_semi_diameter": (4.0, "float_by_stop_size", 8.0),
    }

    for mode, (value, optiland_mode, optiland_value) in expected.items():
        design = OpticalDesign.starter()
        design.settings.aperture_mode = mode
        design.settings.set_aperture_value(value)
        system = adapter.to_optic(design)
        result = adapter.analyze_first_order(design)

        assert system.aperture.ap_type == optiland_mode
        assert system.aperture.value == optiland_value
        assert result.valid, result.error
        assert result.image_f_number is not None and result.image_f_number > 0
        assert result.entrance_pupil_diameter_mm is not None and result.entrance_pupil_diameter_mm > 0

    stop_index = system.surface_group.stop_index
    assert float(system.surface_group.surfaces[stop_index].aperture.r_max) == 4.0


def test_recommended_image_distance_tracks_the_lens_focus(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "matplotlib"))
    design = OpticalDesign.starter()
    design.elements[-1].gap_after_mm = 30.0

    result = OptilandAdapter().analyze_first_order(design)

    assert result.valid, result.error
    assert result.back_focal_length_mm == 30.0
    assert result.image_distance_mm == 30.0
    assert abs(result.recommended_image_distance_mm - 45.46) < 0.01


def test_single_positive_lens_focuses_parallel_rays_on_the_image(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "matplotlib"))
    element = LensElement(
        name="Edmund 22-426 equivalent",
        manufacturer="Edmund Optics",
        part_number="22-426",
        shape="double_convex",
        outer_diameter_mm=49.0,
        gap_after_mm=2.0,
        surfaces=[
            SurfaceSpec(42.12, "Fused Silica (Corning 7980)", 21.8, 49.0),
            SurfaceSpec(-42.12, "air", 0.0, 49.0),
        ],
    )
    settings = DesignSettings(field_mode="angles", field_angles_deg=[0.0], field_weights=[1.0])
    design = OpticalDesign("single positive lens", settings, [element])

    initial = OptilandAdapter().analyze_first_order(design)
    assert initial.valid, initial.error
    assert initial.effective_focal_length_mm is not None and initial.effective_focal_length_mm > 0
    assert initial.recommended_image_distance_mm is not None
    assert initial.paraxial_focus_distance_mm == initial.recommended_image_distance_mm

    element.gap_after_mm = initial.recommended_image_distance_mm
    focused = OptilandAdapter().analyze_first_order(design)
    rays = trace_parallel_rays(design, focused.refractive_indices, fractions=(-0.8, 0.0, 0.8))

    assert focused.paraxial_focus_distance_mm is not None
    assert abs(focused.paraxial_focus_distance_mm - element.gap_after_mm) < 1e-9
    assert all(abs(ray.points[-1].y_mm) < 1e-9 for ray in rays)
    assert all(ray.points[0].z_mm < 0 for ray in rays)
    real_image_heights = [float(ray["points"][-1]["y_mm"]) for ray in focused.layout_rays]
    assert max(real_image_heights) - min(real_image_heights) > 0.2


def test_single_negative_lens_reports_virtual_focus_without_zeroing_image(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "matplotlib"))
    element = LensElement(
        name="Negative singlet",
        shape="plano_concave",
        outer_diameter_mm=25.0,
        gap_after_mm=20.0,
        surfaces=[
            SurfaceSpec(-22.92, "Fused Silica (Corning 7980)", 2.0, 24.0),
            SurfaceSpec(None, "air", 0.0, 24.0),
        ],
    )
    settings = DesignSettings(field_mode="angles", field_angles_deg=[0.0], field_weights=[1.0])
    design = OpticalDesign("single negative lens", settings, [element])

    result = OptilandAdapter().analyze_first_order(design)

    assert result.valid, result.error
    assert result.effective_focal_length_mm is not None and result.effective_focal_length_mm < 0
    assert result.paraxial_focus_distance_mm is not None and result.paraxial_focus_distance_mm < 0
    assert result.recommended_image_distance_mm is None
    assert any("実像焦点がありません" in warning for warning in result.warnings)
    assert element.gap_after_mm == 20.0
