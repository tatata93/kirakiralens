from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import inf, isinf
from typing import Any
from uuid import uuid4


def new_id() -> str:
    return uuid4().hex


@dataclass(slots=True)
class SurfaceSpec:
    radius_mm: float | None
    material_after: str = "air"
    thickness_after_mm: float = 0.0
    clear_aperture_mm: float | None = None
    coating: str = ""
    surface_type: str = "standard"
    conic: float = 0.0
    asphere_coefficients: list[float] = field(default_factory=list)
    comment: str = ""
    radius_locked: bool = False
    thickness_locked: bool = False
    material_locked: bool = False
    clear_aperture_locked: bool = False
    conic_locked: bool = False
    asphere_locked: bool = False

    @property
    def is_plane(self) -> bool:
        return self.radius_mm is None or self.radius_mm == 0 or self.radius_mm == inf


@dataclass(slots=True)
class LensElement:
    name: str
    surfaces: list[SurfaceSpec]
    outer_diameter_mm: float
    gap_after_mm: float = 2.0
    manufacturer: str = "Custom"
    part_number: str = ""
    shape: str = "custom"
    catalog_product_id: int | None = None
    is_catalog: bool = False
    orientation_reversed: bool = False
    element_locked: bool = False
    orientation_locked: bool = False
    diameter_locked: bool = False
    gap_locked: bool = False
    diameter_min_mm: float | None = None
    diameter_max_mm: float | None = None
    gap_min_mm: float = 0.0
    gap_max_mm: float | None = None
    id: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        if len(self.surfaces) < 2:
            raise ValueError("A lens element needs at least two optical surfaces")
        if self.outer_diameter_mm <= 0:
            raise ValueError("Outer diameter must be positive")
        if self.gap_after_mm < 0:
            raise ValueError("Air gap cannot be negative")

    def reverse(self) -> None:
        if self.orientation_locked:
            raise ValueError("Element orientation is locked")
        internal_media = [surface.material_after for surface in self.surfaces[:-1]]
        internal_thicknesses = [surface.thickness_after_mm for surface in self.surfaces[:-1]]
        reversed_surfaces: list[SurfaceSpec] = []
        for index, source in enumerate(reversed(self.surfaces)):
            radius = None if source.is_plane else -float(source.radius_mm)
            is_last = index == len(self.surfaces) - 1
            reversed_surfaces.append(
                SurfaceSpec(
                    radius_mm=radius,
                    material_after="air" if is_last else list(reversed(internal_media))[index],
                    thickness_after_mm=0.0 if is_last else list(reversed(internal_thicknesses))[index],
                    clear_aperture_mm=source.clear_aperture_mm,
                    coating=source.coating,
                    surface_type=source.surface_type,
                    conic=source.conic,
                    asphere_coefficients=[-coefficient for coefficient in source.asphere_coefficients],
                    comment=source.comment,
                    radius_locked=source.radius_locked,
                    thickness_locked=source.thickness_locked,
                    material_locked=source.material_locked,
                    clear_aperture_locked=source.clear_aperture_locked,
                    conic_locked=source.conic_locked,
                    asphere_locked=source.asphere_locked,
                )
            )
        self.surfaces = reversed_surfaces
        self.orientation_reversed = not self.orientation_reversed

    def custom_copy(self) -> LensElement:
        copied = lens_element_from_dict(asdict(self))
        copied.id = new_id()
        copied.is_catalog = False
        copied.catalog_product_id = self.catalog_product_id
        copied.manufacturer = "Custom"
        copied.part_number = ""
        copied.name = f"{self.name} (custom)"
        return copied


@dataclass(slots=True)
class DesignSettings:
    name: str = "Pentax K 50 mm F4"
    sensor_width_mm: float = 36.0
    sensor_height_mm: float = 24.0
    sensor_preset: str = "full_frame"
    object_distance_mm: float = inf
    focal_length_target_mm: float = 50.0
    f_number_target: float = 4.0
    mount_name: str = "Pentax K"
    back_focus_target_mm: float = 45.46
    back_focus_tolerance_mm: float = 0.5
    back_focus_hard: bool = False
    auto_focus_enabled: bool = True
    cover_glass_thickness_mm: float = 0.0
    primary_wavelength_um: float = 0.58756
    wavelengths_um: list[float] = field(default_factory=lambda: [0.48613, 0.58756, 0.65627])
    wavelength_weights: list[float] = field(default_factory=lambda: [1.0, 1.0, 1.0])
    field_mode: str = "sensor"
    field_fractions: list[float] = field(default_factory=lambda: [0.0, 0.7, 1.0])
    field_angles_deg: list[float] = field(default_factory=lambda: [0.0, 10.0, 20.0])
    field_weights: list[float] = field(default_factory=lambda: [1.0, 1.0, 1.0])
    layout_ray_count: int = 7
    spot_ring_count: int = 10
    ray_fan_point_count: int = 101
    analysis_curve_point_count: int = 51
    max_outer_diameter_mm: float = 50.0

    def normalize(self) -> None:
        self.sensor_width_mm = max(float(self.sensor_width_mm), 0.1)
        self.sensor_height_mm = max(float(self.sensor_height_mm), 0.1)
        if self.field_mode not in {"sensor", "angles"}:
            self.field_mode = "sensor"
        active_fields = self.field_angles_deg if self.field_mode == "angles" else self.field_fractions
        field_maximum = 89.0 if self.field_mode == "angles" else 1.0
        field_pairs: dict[float, float] = {}
        for index, value in enumerate(active_fields):
            clean_value = min(max(float(value), 0.0), field_maximum)
            field_pairs[clean_value] = max(float(self.field_weights[index]), 0.0) if index < len(self.field_weights) else 1.0
        if not field_pairs:
            field_pairs = {0.0: 1.0}
        ordered_fields = sorted(field_pairs)
        if self.field_mode == "angles":
            self.field_angles_deg = ordered_fields
        else:
            self.field_fractions = ordered_fields
        self.field_weights = [field_pairs[value] for value in ordered_fields]
        pairs = sorted(
            (
                (min(max(float(wavelength), 0.2), 2.5), max(float(weight), 0.0))
                for wavelength, weight in zip(
                    self.wavelengths_um,
                    self.wavelength_weights + [1.0] * len(self.wavelengths_um),
                    strict=False,
                )
            ),
            key=lambda pair: pair[0],
        )
        if not pairs:
            pairs = [(0.58756, 1.0)]
        self.wavelengths_um = [pair[0] for pair in pairs]
        self.wavelength_weights = [pair[1] for pair in pairs]
        self.primary_wavelength_um = min(self.wavelengths_um, key=lambda value: abs(value - self.primary_wavelength_um))
        self.layout_ray_count = min(max(int(self.layout_ray_count), 1), 31)
        self.spot_ring_count = min(max(int(self.spot_ring_count), 2), 30)
        self.ray_fan_point_count = _odd_between(self.ray_fan_point_count, 11, 501)
        self.analysis_curve_point_count = min(max(int(self.analysis_curve_point_count), 11), 201)


@dataclass(slots=True)
class OpticalDesign:
    name: str
    settings: DesignSettings = field(default_factory=DesignSettings)
    elements: list[LensElement] = field(default_factory=list)
    stop_after_element: int = 0
    stop_surface_index: int | None = None
    schema_version: int = 1

    @classmethod
    def starter(cls) -> OpticalDesign:
        settings = DesignSettings()
        return cls(
            name="Pentax K 50 mm F4 starter",
            settings=settings,
            elements=[
                LensElement(
                    name="Front positive",
                    shape="double_convex",
                    outer_diameter_mm=30.0,
                    gap_after_mm=0.709,
                    surfaces=[
                        SurfaceSpec(42.0, "N-BK7", 5.0, 28.0),
                        SurfaceSpec(-70.0, "air", 0.0, 28.0),
                    ],
                ),
                LensElement(
                    name="Negative",
                    shape="double_concave",
                    outer_diameter_mm=24.0,
                    gap_after_mm=7.291,
                    surfaces=[
                        SurfaceSpec(-65.956, "N-SF5", 2.5, 22.0),
                        SurfaceSpec(65.956, "air", 0.0, 22.0),
                    ],
                ),
                LensElement(
                    name="Rear positive",
                    shape="double_convex",
                    outer_diameter_mm=28.0,
                    gap_after_mm=settings.back_focus_target_mm,
                    surfaces=[
                        SurfaceSpec(65.0, "N-BK7", 4.0, 26.0),
                        SurfaceSpec(-38.0, "air", 0.0, 26.0),
                    ],
                ),
            ],
            stop_after_element=0,
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if isinf(self.settings.object_distance_mm):
            data["settings"]["object_distance_mm"] = "infinity"
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OpticalDesign:
        settings_data = dict(data.get("settings", {}))
        if settings_data.get("object_distance_mm") == "infinity":
            settings_data["object_distance_mm"] = inf
        settings = DesignSettings(**settings_data)
        settings.normalize()
        return cls(
            name=data["name"],
            settings=settings,
            elements=[lens_element_from_dict(item) for item in data.get("elements", [])],
            stop_after_element=int(data.get("stop_after_element", 0)),
            stop_surface_index=(
                None if data.get("stop_surface_index") is None else int(data["stop_surface_index"])
            ),
            schema_version=int(data.get("schema_version", 1)),
        )


def lens_element_from_dict(data: dict[str, Any]) -> LensElement:
    values = dict(data)
    values["surfaces"] = [SurfaceSpec(**surface) for surface in values.get("surfaces", [])]
    return LensElement(**values)


def _odd_between(value: int, minimum: int, maximum: int) -> int:
    result = min(max(int(value), minimum), maximum)
    return result if result % 2 else min(result + 1, maximum)
