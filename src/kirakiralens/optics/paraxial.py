from __future__ import annotations

from dataclasses import dataclass
from math import radians, tan

from ..domain import OpticalDesign
from .configuration import resolved_field_angles


@dataclass(slots=True)
class RayPoint:
    z_mm: float
    y_mm: float


@dataclass(slots=True)
class ParaxialRayPath:
    field_index: int
    field_angle_deg: float
    points: list[RayPoint]


def trace_parallel_rays(
    design: OpticalDesign,
    refractive_indices: list[float],
    fractions: tuple[float, ...] | None = None,
    entrance_distance_mm: float = 10.0,
) -> list[ParaxialRayPath]:
    """Trace first-order rays using indices supplied by Optiland.

    The index list follows Optiland's object/surfaces/image ordering. Rays are
    only drawn when the complete index list is available, avoiding guessed glass
    properties in the UI.
    """

    surface_count = sum(len(element.surfaces) for element in design.elements)
    if len(refractive_indices) != surface_count + 2 or not design.elements:
        return []
    entrance_radius = (design.elements[0].surfaces[0].clear_aperture_mm or design.elements[0].outer_diameter_mm) / 2
    if fractions is None:
        count = design.settings.layout_ray_count
        fractions = tuple(0.0 if count == 1 else -0.8 + 1.6 * index / (count - 1) for index in range(count))
    rays: list[ParaxialRayPath] = []
    for field_index, field_angle in enumerate(resolved_field_angles(design.settings)):
        for fraction in fractions:
            y = entrance_radius * fraction
            slope = tan(radians(field_angle))
            z = 0.0
            entrance_distance = max(float(entrance_distance_mm), 0.0)
            points = [RayPoint(-entrance_distance, y - slope * entrance_distance), RayPoint(z, y)]
            index_cursor = 1
            n_before = refractive_indices[0]
            for element in design.elements:
                for local_index, surface in enumerate(element.surfaces):
                    n_after = refractive_indices[index_cursor]
                    if not surface.is_plane:
                        slope = (n_before / n_after) * slope - ((n_after - n_before) / n_after) * y / float(surface.radius_mm)
                    else:
                        slope = (n_before / n_after) * slope
                    thickness = element.gap_after_mm if local_index == len(element.surfaces) - 1 else surface.thickness_after_mm
                    y += slope * thickness
                    z += thickness
                    points.append(RayPoint(z, y))
                    n_before = n_after
                    index_cursor += 1
            rays.append(ParaxialRayPath(field_index, field_angle, points))
    return rays
