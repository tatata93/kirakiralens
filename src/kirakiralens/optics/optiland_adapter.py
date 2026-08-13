from __future__ import annotations

from dataclasses import dataclass, field
from math import inf, isfinite
from typing import Any

from ..domain import OpticalDesign
from .configuration import resolved_field_angles, sensor_angle_of_view


MATERIAL_ALIASES = {
    "Fused Silica": "fused_silica",
    "Fused Silica (Corning 7980)": "fused_silica",
    "Fused Silica (Corning 7980) ": "fused_silica",
}


@dataclass(slots=True)
class FirstOrderAnalysis:
    valid: bool
    engine: str
    effective_focal_length_mm: float | None = None
    back_focal_length_mm: float | None = None
    image_distance_mm: float | None = None
    recommended_image_distance_mm: float | None = None
    paraxial_focus_distance_mm: float | None = None
    image_f_number: float | None = None
    entrance_pupil_diameter_mm: float | None = None
    total_track_mm: float | None = None
    angle_of_view_horizontal_deg: float | None = None
    angle_of_view_vertical_deg: float | None = None
    angle_of_view_diagonal_deg: float | None = None
    maximum_half_field_angle_deg: float | None = None
    field_angles_deg: list[float] = field(default_factory=list)
    refractive_indices: list[float] = field(default_factory=list)
    layout_rays: list[dict[str, Any]] = field(default_factory=list)
    layout_ray_model: str = ""
    layout_ray_wavelength_um: float | None = None
    warnings: list[str] = field(default_factory=list)
    error: str = ""


class OptilandAdapter:
    """Translate the persistent domain model to the pinned Optiland API."""

    def to_optic(self, design: OpticalDesign) -> Any:
        from optiland import optic, physical_apertures

        system = optic.Optic(design.name)
        object_distance = design.settings.object_distance_mm
        system.add_surface(index=0, thickness=inf if object_distance == inf else float(object_distance), comment="Object")
        surface_number = 1
        for element_index, element in enumerate(design.elements):
            stop_surface_index = design.stop_surface_index
            if stop_surface_index is None or not 0 <= stop_surface_index < len(element.surfaces):
                stop_surface_index = len(element.surfaces) - 1
            for local_index, surface in enumerate(element.surfaces):
                is_last = local_index == len(element.surfaces) - 1
                thickness = element.gap_after_mm if is_last else surface.thickness_after_mm
                material = MATERIAL_ALIASES.get(surface.material_after.strip(), surface.material_after.strip())
                if not material:
                    material = "air"
                radius = inf if surface.is_plane else float(surface.radius_mm)
                surface_type = surface.surface_type if surface.surface_type in {"standard", "even_asphere"} else "standard"
                geometry_parameters: dict[str, Any] = {"radius": radius, "conic": float(surface.conic)}
                if surface_type == "even_asphere":
                    geometry_parameters["coefficients"] = list(surface.asphere_coefficients)
                clear_diameter = min(
                    element.outer_diameter_mm,
                    surface.clear_aperture_mm or element.outer_diameter_mm,
                )
                system.add_surface(
                    index=surface_number,
                    thickness=float(thickness),
                    surface_type=surface_type,
                    material=material,
                    is_stop=(element_index == design.stop_after_element and local_index == stop_surface_index),
                    comment=surface.comment or self._surface_comment(element.manufacturer, element.part_number, local_index),
                    aperture=physical_apertures.RadialAperture(r_max=float(clear_diameter) / 2.0),
                    **geometry_parameters,
                )
                surface_number += 1
        system.add_surface(index=surface_number, comment="Image")
        system.set_aperture(aperture_type="imageFNO", value=design.settings.f_number_target)
        system.set_field_type(field_type="angle")
        for field_angle in resolved_field_angles(design.settings):
            system.add_field(y=field_angle)
        weights = design.settings.wavelength_weights + [1.0] * len(design.settings.wavelengths_um)
        for wavelength, weight in zip(design.settings.wavelengths_um, weights, strict=False):
            system.add_wavelength(
                value=wavelength,
                is_primary=abs(wavelength - design.settings.primary_wavelength_um) < 1e-9,
                weight=weight,
            )
        system.update()
        return system

    def analyze_first_order(self, design: OpticalDesign) -> FirstOrderAnalysis:
        if not design.elements:
            return FirstOrderAnalysis(valid=False, engine="Optiland 0.5.9", error="No lens elements")
        try:
            import optiland

            system = self.to_optic(design)
            final_gap = design.elements[-1].gap_after_mm
            indices = [float(value) for value in system.n()]
            focus_distance = float(final_gap + system.paraxial.F2())
            if not isfinite(focus_distance):
                focus_distance = None
            recommended_image_distance = (
                focus_distance if focus_distance is not None and focus_distance > 0.0 else None
            )
            # Optiland 0.5.9 returns abs(f2). The sign of -f1 distinguishes
            # converging and diverging systems in its coordinate convention.
            effective_focal_length = -float(system.paraxial.f1())
            angles = sensor_angle_of_view(design.settings, effective_focal_length)
            traced_fields = resolved_field_angles(design.settings)
            layout_warning = ""
            try:
                layout_rays = self._trace_layout_rays(system, design, traced_fields)
            except Exception as exc:
                layout_rays = []
                layout_warning = f"実光線図を作成できませんでした: {type(exc).__name__}: {exc}"
            result = FirstOrderAnalysis(
                valid=True,
                engine=f"Optiland {getattr(optiland, '__version__', 'unknown')}",
                effective_focal_length_mm=effective_focal_length,
                back_focal_length_mm=float(final_gap),
                image_distance_mm=float(final_gap),
                recommended_image_distance_mm=recommended_image_distance,
                paraxial_focus_distance_mm=focus_distance,
                image_f_number=float(system.paraxial.FNO()),
                entrance_pupil_diameter_mm=float(system.paraxial.EPD()),
                total_track_mm=float(system.total_track),
                angle_of_view_horizontal_deg=angles["horizontal_deg"],
                angle_of_view_vertical_deg=angles["vertical_deg"],
                angle_of_view_diagonal_deg=angles["diagonal_deg"],
                maximum_half_field_angle_deg=max(traced_fields),
                field_angles_deg=traced_fields,
                refractive_indices=indices,
                layout_rays=layout_rays,
                layout_ray_model="Optiland sequential real rays" if layout_rays else "",
                layout_ray_wavelength_um=float(design.settings.primary_wavelength_um),
            )
            if result.back_focal_length_mm is not None and result.back_focal_length_mm <= 0:
                result.warnings.append("Back focal length is non-positive")
            if result.paraxial_focus_distance_mm is not None and result.paraxial_focus_distance_mm <= 0:
                result.warnings.append("無限遠物体の実像焦点がありません（発散系）")
            if layout_warning:
                result.warnings.append(layout_warning)
            return result
        except Exception as exc:  # Optiland raises several domain-specific exception types.
            return FirstOrderAnalysis(
                valid=False,
                engine="Optiland 0.5.9",
                error=f"{type(exc).__name__}: {exc}",
            )

    @staticmethod
    def _surface_comment(manufacturer: str, part_number: str, local_index: int) -> str:
        identity = " ".join(item for item in (manufacturer, part_number) if item).strip()
        return f"{identity or 'Custom'} S{local_index + 1}"

    @staticmethod
    def _trace_layout_rays(system: Any, design: OpticalDesign, field_angles: list[float]) -> list[dict[str, Any]]:
        import optiland.backend as be

        ray_count = max(int(design.settings.layout_ray_count), 1)
        if ray_count == 1:
            pupil = be.array([0.0])
        else:
            pupil = be.linspace(-0.95, 0.95, ray_count)
        pupil_values = [float(value) for value in be.to_numpy(pupil)]
        wavelength = float(design.settings.primary_wavelength_um)
        entrance_span = max(10.0, min(30.0, design.elements[0].outer_diameter_mm / 2.0))
        output: list[dict[str, Any]] = []

        for field_index, (field_x, field_y) in enumerate(system.fields.get_field_coords()):
            system.trace_generic(
                Hx=float(field_x),
                Hy=float(field_y),
                Px=be.zeros_like(pupil),
                Py=pupil,
                wavelength=wavelength,
            )
            y_values = be.to_numpy(system.surface_group.y)
            z_values = be.to_numpy(system.surface_group.z)
            intensities = be.to_numpy(system.surface_group.intensity)
            surface_count, traced_count = y_values.shape
            for ray_index in range(traced_count):
                points: list[dict[str, float]] = []
                vignetted = False
                for surface_index in range(surface_count):
                    y = float(y_values[surface_index, ray_index])
                    z = float(z_values[surface_index, ray_index])
                    intensity = float(intensities[surface_index, ray_index])
                    if not isfinite(y) or not isfinite(z) or intensity <= 0.0:
                        vignetted = True
                        break
                    points.append({"z_mm": z, "y_mm": y})
                if len(points) < 2:
                    continue
                if points[0]["z_mm"] < -entrance_span:
                    first, second = points[0], points[1]
                    dz = second["z_mm"] - first["z_mm"]
                    if abs(dz) > 1e-12:
                        start_z = -entrance_span
                        start_y = first["y_mm"] + (second["y_mm"] - first["y_mm"]) * (
                            start_z - first["z_mm"]
                        ) / dz
                        points[0] = {"z_mm": start_z, "y_mm": start_y}
                output.append(
                    {
                        "field_index": field_index,
                        "field_angle_deg": float(field_angles[field_index]),
                        "pupil_fraction": pupil_values[ray_index],
                        "wavelength_um": wavelength,
                        "vignetted": vignetted,
                        "points": points,
                    }
                )
        return output
