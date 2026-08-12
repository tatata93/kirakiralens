from __future__ import annotations

import hashlib
import json
from typing import Any

from ..domain import OpticalDesign


def design_signature(design: OpticalDesign, options: dict[str, Any] | None = None) -> str:
    """Return a stable content signature for analysis caching."""
    payload: dict[str, Any] = {"design": design.to_dict()}
    if options is not None:
        payload["options"] = options
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def analysis_signature(design: OpticalDesign, options: dict[str, Any] | None = None) -> str:
    """Hash only values that can change sequential optical performance."""
    settings = design.settings
    payload: dict[str, Any] = {
        "settings": {
            "sensor_width_mm": settings.sensor_width_mm,
            "sensor_height_mm": settings.sensor_height_mm,
            "object_distance_mm": "infinity" if settings.object_distance_mm == float("inf") else settings.object_distance_mm,
            "focal_length_target_mm": settings.focal_length_target_mm,
            "f_number_target": settings.f_number_target,
            "back_focus_target_mm": settings.back_focus_target_mm,
            "cover_glass_thickness_mm": settings.cover_glass_thickness_mm,
            "primary_wavelength_um": settings.primary_wavelength_um,
            "wavelengths_um": settings.wavelengths_um,
            "field_mode": settings.field_mode,
            "field_fractions": settings.field_fractions,
            "field_angles_deg": settings.field_angles_deg,
        },
        "stop_after_element": design.stop_after_element,
        "stop_surface_index": design.stop_surface_index,
        "elements": [
            {
                "outer_diameter_mm": element.outer_diameter_mm,
                "gap_after_mm": element.gap_after_mm,
                "surfaces": [
                    {
                        "radius_mm": surface.radius_mm,
                        "material_after": surface.material_after,
                        "thickness_after_mm": surface.thickness_after_mm,
                        "clear_aperture_mm": surface.clear_aperture_mm,
                        "surface_type": surface.surface_type,
                        "conic": surface.conic,
                        "asphere_coefficients": surface.asphere_coefficients,
                    }
                    for surface in element.surfaces
                ],
            }
            for element in design.elements
        ],
    }
    if options is not None:
        payload["options"] = options
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
