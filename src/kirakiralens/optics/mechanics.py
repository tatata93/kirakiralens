from __future__ import annotations

from math import isfinite, sqrt
from typing import Mapping

from ..domain import LensElement, OpticalDesign, SurfaceSpec


OverrideKey = tuple[str, int, int]


def surface_sag_mm(surface: SurfaceSpec, height_mm: float, radius_mm: float | None = None) -> float | None:
    """Return axial sag, or None when the surface is undefined at this height."""
    if surface.is_plane and radius_mm is None:
        return 0.0
    radius = float(surface.radius_mm if radius_mm is None else radius_mm)
    if not isfinite(radius) or abs(radius) < 1e-12:
        return 0.0
    radial_square = float(height_mm) ** 2
    root_argument = 1.0 - (1.0 + float(surface.conic)) * radial_square / (radius * radius)
    if root_argument < -1e-10:
        return None
    root = sqrt(max(root_argument, 0.0))
    denominator = radius * (1.0 + root)
    if abs(denominator) < 1e-12:
        return None
    sag = radial_square / denominator
    if surface.surface_type == "even_asphere":
        for index, coefficient in enumerate(surface.asphere_coefficients):
            sag += float(coefficient) * radial_square ** (index + 1)
    return sag if isfinite(sag) else None


def required_air_gap_mm(
    left: LensElement,
    right: LensElement,
    minimum_clearance_mm: float = 0.1,
    *,
    left_radius_mm: float | None = None,
    right_radius_mm: float | None = None,
    samples: int = 41,
) -> float:
    """Minimum vertex gap that prevents adjacent lens surfaces intersecting."""
    rear = left.surfaces[-1]
    front = right.surfaces[0]
    # Component-to-component contact is mechanical, so check the full shared
    # body diameter rather than only the smaller optical clear aperture.
    half_diameter = min(
        _usable_surface_half_diameter(left, rear),
        _usable_surface_half_diameter(right, front),
    )
    required = max(float(minimum_clearance_mm), 0.0)
    for index in range(max(samples, 3)):
        height = half_diameter * index / (max(samples, 3) - 1)
        rear_sag = surface_sag_mm(rear, height, left_radius_mm)
        front_sag = surface_sag_mm(front, height, right_radius_mm)
        if rear_sag is None or front_sag is None:
            return float("inf")
        required = max(required, rear_sag - front_sag + minimum_clearance_mm)
    return required


def mechanical_clearance_violations(
    design: OpticalDesign,
    minimum_clearance_mm: float = 0.1,
    overrides: Mapping[OverrideKey, float] | None = None,
) -> list[str]:
    """Report internal surface crossings and adjacent component collisions."""
    overrides = overrides or {}
    violations: list[str] = []
    for element_index, element in enumerate(design.elements):
        # The bundled patent examples do not publish mechanical semi-diameters;
        # their display apertures are estimates and cannot support edge checks.
        if element.manufacturer == "Patent example":
            continue
        for surface_index in range(len(element.surfaces) - 1):
            front = element.surfaces[surface_index]
            back = element.surfaces[surface_index + 1]
            thickness = overrides.get(
                ("thickness", element_index, surface_index),
                front.thickness_after_mm,
            )
            front_radius = overrides.get(("radius", element_index, surface_index))
            back_radius = overrides.get(("radius", element_index, surface_index + 1))
            half_diameter = min(
                _surface_half_diameter(element, front),
                _surface_half_diameter(element, back),
            )
            minimum_edge_thickness = float("inf")
            for sample in range(41):
                height = half_diameter * sample / 40.0
                front_sag = surface_sag_mm(front, height, front_radius)
                back_sag = surface_sag_mm(back, height, back_radius)
                if front_sag is None or back_sag is None:
                    minimum_edge_thickness = float("-inf")
                    break
                minimum_edge_thickness = min(
                    minimum_edge_thickness,
                    float(thickness) + back_sag - front_sag,
                )
            if minimum_edge_thickness < -1e-6:
                violations.append(f"L{element_index + 1} S{surface_index + 1}-S{surface_index + 2} surface crossing")

    for element_index, (left, right) in enumerate(zip(design.elements, design.elements[1:])):
        gap = overrides.get(("air_gap", element_index, len(left.surfaces) - 1), left.gap_after_mm)
        left_radius = overrides.get(("radius", element_index, len(left.surfaces) - 1))
        right_radius = overrides.get(("radius", element_index + 1, 0))
        required = required_air_gap_mm(
            left,
            right,
            minimum_clearance_mm,
            left_radius_mm=left_radius,
            right_radius_mm=right_radius,
        )
        if not isfinite(required) or float(gap) + 1e-6 < required:
            violations.append(f"L{element_index + 1}-L{element_index + 2} collision")
    return violations


def ensure_air_gap_clearances(design: OpticalDesign, minimum_clearance_mm: float = 0.1) -> bool:
    """Increase unlocked inter-element gaps to clear neighboring curved surfaces."""
    valid = True
    for index, (left, right) in enumerate(zip(design.elements, design.elements[1:])):
        required = required_air_gap_mm(left, right, minimum_clearance_mm)
        if not isfinite(required):
            valid = False
            continue
        required = max(required, left.gap_min_mm)
        if left.gap_after_mm + 1e-6 >= required:
            continue
        if left.gap_locked or left.element_locked:
            valid = False
            continue
        if left.gap_max_mm is not None and required > left.gap_max_mm + 1e-6:
            valid = False
            continue
        left.gap_after_mm = required
    return valid and not mechanical_clearance_violations(design, minimum_clearance_mm)


def _surface_half_diameter(element: LensElement, surface: SurfaceSpec) -> float:
    return min(
        float(element.outer_diameter_mm),
        float(surface.clear_aperture_mm or element.outer_diameter_mm),
    ) / 2.0


def _usable_surface_half_diameter(element: LensElement, surface: SurfaceSpec) -> float:
    half_diameter = element.outer_diameter_mm / 2.0
    if surface.is_plane or 1.0 + surface.conic <= 0.0:
        return half_diameter
    return min(
        half_diameter,
        abs(float(surface.radius_mm)) / sqrt(1.0 + float(surface.conic)) * 0.97,
    )
