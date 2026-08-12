from __future__ import annotations

from dataclasses import dataclass

from ..domain import OpticalDesign


@dataclass(slots=True)
class RayPoint:
    z_mm: float
    y_mm: float


def trace_parallel_rays(
    design: OpticalDesign,
    refractive_indices: list[float],
    fractions: tuple[float, ...] = (-0.8, -0.4, 0.0, 0.4, 0.8),
) -> list[list[RayPoint]]:
    """Trace first-order rays using indices supplied by Optiland.

    The index list follows Optiland's object/surfaces/image ordering. Rays are
    only drawn when the complete index list is available, avoiding guessed glass
    properties in the UI.
    """

    surface_count = sum(len(element.surfaces) for element in design.elements)
    if len(refractive_indices) != surface_count + 2 or not design.elements:
        return []
    entrance_radius = (design.elements[0].surfaces[0].clear_aperture_mm or design.elements[0].outer_diameter_mm) / 2
    rays: list[list[RayPoint]] = []
    for fraction in fractions:
        y = entrance_radius * fraction
        slope = 0.0
        z = 0.0
        points = [RayPoint(z, y)]
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
        rays.append(points)
    return rays
