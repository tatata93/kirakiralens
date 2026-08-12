from __future__ import annotations

from dataclasses import dataclass, field
from math import atan, degrees, inf
from typing import Any

from ..domain import OpticalDesign


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
    image_f_number: float | None = None
    entrance_pupil_diameter_mm: float | None = None
    total_track_mm: float | None = None
    refractive_indices: list[float] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str = ""


class OptilandAdapter:
    """Translate the persistent domain model to the pinned Optiland API."""

    def to_optic(self, design: OpticalDesign) -> Any:
        from optiland import optic

        system = optic.Optic(design.name)
        system.add_surface(index=0, thickness=inf, comment="Object")
        surface_number = 1
        for element_index, element in enumerate(design.elements):
            for local_index, surface in enumerate(element.surfaces):
                is_last = local_index == len(element.surfaces) - 1
                thickness = element.gap_after_mm if is_last else surface.thickness_after_mm
                material = MATERIAL_ALIASES.get(surface.material_after.strip(), surface.material_after.strip())
                if not material:
                    material = "air"
                radius = inf if surface.is_plane else float(surface.radius_mm)
                system.add_surface(
                    index=surface_number,
                    thickness=float(thickness),
                    radius=radius,
                    material=material,
                    is_stop=(element_index == design.stop_after_element and is_last),
                    comment=self._surface_comment(element.manufacturer, element.part_number, local_index),
                )
                surface_number += 1
        system.add_surface(index=surface_number, comment="Image")
        system.set_aperture(aperture_type="imageFNO", value=design.settings.f_number_target)
        system.set_field_type(field_type="angle")
        half_diagonal = ((design.settings.sensor_width_mm / 2) ** 2 + (design.settings.sensor_height_mm / 2) ** 2) ** 0.5
        maximum_field = degrees(atan(half_diagonal / design.settings.focal_length_target_mm))
        for field_fraction in (0.0, 0.7, 1.0):
            system.add_field(y=maximum_field * field_fraction)
        for wavelength in design.settings.wavelengths_um:
            system.add_wavelength(
                value=wavelength,
                is_primary=abs(wavelength - design.settings.primary_wavelength_um) < 1e-9,
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
            result = FirstOrderAnalysis(
                valid=True,
                engine=f"Optiland {getattr(optiland, '__version__', 'unknown')}",
                effective_focal_length_mm=float(system.paraxial.f2()),
                back_focal_length_mm=float(final_gap + system.paraxial.F2()),
                image_f_number=float(system.paraxial.FNO()),
                entrance_pupil_diameter_mm=float(system.paraxial.EPD()),
                total_track_mm=float(system.total_track),
                refractive_indices=indices,
            )
            if result.back_focal_length_mm is not None and result.back_focal_length_mm <= 0:
                result.warnings.append("Back focal length is non-positive")
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
