from __future__ import annotations

from dataclasses import dataclass
from math import inf, radians, sqrt, tan
from typing import Callable

from ..domain import DesignSettings, LensElement, OpticalDesign, SurfaceSpec
from .optiland_adapter import FirstOrderAnalysis


@dataclass(frozen=True, slots=True)
class ReferenceMetric:
    key: str
    label: str
    expected: float
    tolerance: float
    unit: str


@dataclass(frozen=True, slots=True)
class ReferenceExample:
    key: str
    family: str
    publication: str
    example_name: str
    source_url: str
    description: str
    build: Callable[[], OpticalDesign]
    metrics: tuple[ReferenceMetric, ...]

    @property
    def label(self) -> str:
        return f"{self.family} / {self.publication} {self.example_name}"


@dataclass(frozen=True, slots=True)
class ReferenceValidation:
    key: str
    label: str
    expected: float
    actual: float | None
    tolerance: float
    unit: str
    passed: bool


def _surface(
    radius: float | None,
    thickness: float,
    nd: float | None = None,
    vd: float | None = None,
    *,
    aperture: float,
    surface_type: str = "standard",
    coefficients: tuple[float, ...] = (),
) -> SurfaceSpec:
    material = "air" if nd is None else f"Patent glass nD {nd:.5f} / vd {vd:.2f}"
    return SurfaceSpec(
        radius_mm=radius,
        material_after=material,
        thickness_after_mm=thickness,
        clear_aperture_mm=aperture,
        surface_type=surface_type,
        asphere_coefficients=list(coefficients),
        refractive_index_d=nd,
        abbe_number_d=vd,
    )


def _settings(
    name: str,
    focal_length: float,
    f_number: float,
    back_focus: float,
    full_field_angle: float,
    image_height: float | None,
    maximum_diameter: float,
) -> DesignSettings:
    if image_height is None:
        image_height = focal_length * tan(radians(full_field_angle / 2.0))
    sensor_width = 2.0 * image_height * 3.0 / sqrt(13.0)
    sensor_height = sensor_width * 2.0 / 3.0
    return DesignSettings(
        name=name,
        sensor_width_mm=sensor_width,
        sensor_height_mm=sensor_height,
        sensor_preset="patent_example",
        object_distance_mm=inf,
        focal_length_target_mm=focal_length,
        f_number_target=f_number,
        mount_name="Patent reference",
        back_focus_target_mm=back_focus,
        auto_focus_enabled=False,
        primary_wavelength_um=0.58756,
        wavelengths_um=[0.48613, 0.58756, 0.65627],
        wavelength_weights=[1.0, 1.0, 1.0],
        field_mode="angles",
        field_angles_deg=[0.0, full_field_angle * 0.35, full_field_angle * 0.5],
        field_weights=[1.0, 1.0, 1.0],
        max_outer_diameter_mm=maximum_diameter,
    )


def _triplet() -> OpticalDesign:
    settings = _settings("JPH07168095A embodiment 1", 100.0, 2.78, 81.015, 64.7, None, 100.0)
    design = OpticalDesign(
        name="Triplet - JPH07168095A embodiment 1",
        settings=settings,
        elements=[
            LensElement(
                name="L1 positive meniscus",
                manufacturer="Patent example",
                part_number="JPH07168095A Ex.1 L1",
                shape="positive_meniscus",
                outer_diameter_mm=70.0,
                gap_after_mm=4.82,
                surfaces=[
                    _surface(32.466, 10.85, 1.734, 51.49, aperture=68.0),
                    _surface(74.59, 0.0, aperture=68.0),
                ],
            ),
            LensElement(
                name="L2 biconcave",
                manufacturer="Patent example",
                part_number="JPH07168095A Ex.1 L2",
                shape="double_concave",
                outer_diameter_mm=60.0,
                gap_after_mm=3.58,
                surfaces=[
                    _surface(-86.321, 2.34, 1.689, 31.08, aperture=58.0),
                    _surface(34.271, 0.0, aperture=58.0),
                ],
            ),
            LensElement(
                name="L3 biconvex asphere",
                manufacturer="Patent example",
                part_number="JPH07168095A Ex.1 L3",
                shape="double_convex",
                outer_diameter_mm=70.0,
                gap_after_mm=81.015,
                surfaces=[
                    _surface(90.834, 6.81, 1.799, 42.24, aperture=68.0),
                    _surface(
                        -60.477,
                        0.0,
                        aperture=68.0,
                        surface_type="even_asphere",
                        coefficients=(-0.41866e-6, 0.71905e-9, -0.6539e-11),
                    ),
                ],
            ),
        ],
        explicit_stop_after_element=2,
        explicit_stop_offset_mm=3.18,
        reference_example_key="triplet-jph07168095a-ex1",
    )
    return design


def _tessar() -> OpticalDesign:
    settings = _settings("JP2003005030A example 1", 100.0, 2.90, 82.5467, 50.4, 47.0, 110.0)
    design = OpticalDesign(
        name="Tessar - JP2003005030A example 1",
        settings=settings,
        elements=[
            LensElement(
                name="L1 positive",
                manufacturer="Patent example",
                part_number="JP2003005030A Ex.1 L1",
                shape="positive_meniscus",
                outer_diameter_mm=82.0,
                gap_after_mm=9.99,
                surfaces=[
                    _surface(51.6147, 8.687, 1.816, 46.63, aperture=80.0),
                    _surface(301.177, 0.0, aperture=80.0),
                ],
            ),
            LensElement(
                name="L2 negative",
                manufacturer="Patent example",
                part_number="JP2003005030A Ex.1 L2",
                shape="negative_meniscus",
                outer_diameter_mm=72.0,
                gap_after_mm=5.6465,
                surfaces=[
                    _surface(-64.973, 3.2576, 1.69895, 30.13, aperture=70.0),
                    _surface(49.3254, 0.0, aperture=70.0),
                ],
            ),
            LensElement(
                name="L3 cemented doublet",
                manufacturer="Patent example",
                part_number="JP2003005030A Ex.1 L3",
                shape="cemented_doublet",
                outer_diameter_mm=82.0,
                gap_after_mm=82.5467,
                surfaces=[
                    _surface(198.5055, 10.4244, 1.883, 40.77, aperture=80.0),
                    _surface(-31.4847, 3.2576, 1.64769, 33.80, aperture=80.0),
                    _surface(-83.094, 0.0, aperture=80.0),
                ],
            ),
        ],
        explicit_stop_after_element=0,
        explicit_stop_offset_mm=3.4748,
        reference_example_key="tessar-jp2003005030a-ex1",
    )
    return design


def _double_gauss() -> OpticalDesign:
    settings = _settings("JPS54104334A example 1", 100.0, 2.0, 74.8, 46.0, None, 110.0)
    design = OpticalDesign(
        name="Double Gauss - JPS54104334A example 1",
        settings=settings,
        elements=[
            LensElement(
                "L1", [_surface(88.702, 6.78, 1.713, 53.9, aperture=78.0), _surface(3682.171, 0.0, aperture=78.0)],
                80.0, 0.19, "Patent example", "JPS54104334A Ex.1 L1", "positive_meniscus",
            ),
            LensElement(
                "L2", [_surface(37.399, 8.72, 1.713, 53.9, aperture=78.0), _surface(61.587, 0.0, aperture=78.0)],
                80.0, 2.71, "Patent example", "JPS54104334A Ex.1 L2", "positive_meniscus",
            ),
            LensElement(
                "L3", [_surface(188.525, 1.94, 1.64831, 33.8, aperture=64.0), _surface(31.585, 0.0, aperture=64.0)],
                66.0, 15.70, "Patent example", "JPS54104334A Ex.1 L3", "negative_meniscus",
            ),
            LensElement(
                "L4 cemented", [
                    _surface(-35.134, 1.94, 1.64831, 33.8, aperture=64.0),
                    _surface(-112.118, 9.63, 1.713, 53.9, aperture=76.0),
                    _surface(-39.574, 0.0, aperture=76.0),
                ], 78.0, 0.19, "Patent example", "JPS54104334A Ex.1 L4", "cemented_doublet",
            ),
            LensElement(
                "L5", [_surface(156.498, 5.62, 1.713, 53.9, aperture=78.0), _surface(-226.066, 0.0, aperture=78.0)],
                80.0, 74.8, "Patent example", "JPS54104334A Ex.1 L5", "positive_meniscus",
            ),
        ],
        explicit_stop_after_element=2,
        explicit_stop_offset_mm=7.85,
        reference_example_key="double-gauss-jps54104334a-ex1",
    )
    return design


_EXAMPLES = (
    ReferenceExample(
        "triplet-jph07168095a-ex1",
        "トリプレット",
        "特開平7-168095",
        "実施例1",
        "https://patents.google.com/patent/JPH07168095A/ja",
        "3群3枚、後置絞り、最終面が偶数次非球面。公報の fB は絞り面から像面までとして照合します。",
        _triplet,
        (
            ReferenceMetric("effective_focal_length_mm", "実効焦点距離", 100.0, 0.2, "mm"),
            ReferenceMetric("image_f_number", "Fナンバー", 2.78, 0.03, ""),
            ReferenceMetric("paraxial_focus_after_stop_mm", "絞り面からの近軸焦点", 77.835, 0.2, "mm"),
        ),
    ),
    ReferenceExample(
        "tessar-jp2003005030a-ex1",
        "テッサー",
        "特開2003-005030",
        "実施例1",
        "https://patents.google.com/patent/JP2003005030A/ja",
        "3群4枚。第1群と第2群の間に、公報表で独立面として記載された絞りを配置します。",
        _tessar,
        (
            ReferenceMetric("effective_focal_length_mm", "実効焦点距離", 100.0, 0.2, "mm"),
            ReferenceMetric("paraxial_focus_distance_mm", "近軸バックフォーカス", 82.5467, 0.25, "mm"),
            ReferenceMetric("image_f_number", "Fナンバー", 2.90, 0.03, ""),
        ),
    ),
    ReferenceExample(
        "double-gauss-jps54104334a-ex1",
        "ダブルガウス",
        "特開昭54-104334",
        "実施例1",
        "https://patents.google.com/patent/JPS54104334A/ja",
        "5群6枚。公報本文の r2=3682.171 を採用し、絞りは中央空気間隔の中点に置きます。",
        _double_gauss,
        (
            ReferenceMetric("effective_focal_length_mm", "実効焦点距離", 100.0, 0.2, "mm"),
            ReferenceMetric("paraxial_focus_distance_mm", "近軸バックフォーカス", 74.8, 0.25, "mm"),
            ReferenceMetric("image_f_number", "Fナンバー", 2.0, 0.03, ""),
            ReferenceMetric("total_track_mm", "全長", 128.3, 0.2, "mm"),
        ),
    ),
)


def reference_examples() -> tuple[ReferenceExample, ...]:
    return _EXAMPLES


def reference_example(key: str) -> ReferenceExample:
    for example in _EXAMPLES:
        if example.key == key:
            return example
    raise KeyError(key)


def build_reference_design(key: str) -> OpticalDesign:
    return reference_example(key).build()


def validate_reference_analysis(
    design: OpticalDesign,
    analysis: FirstOrderAnalysis,
) -> list[ReferenceValidation]:
    if not design.reference_example_key:
        return []
    example = reference_example(design.reference_example_key)
    output: list[ReferenceValidation] = []
    for metric in example.metrics:
        if metric.key == "configured_image_distance_mm":
            actual = analysis.back_focal_length_mm
        elif metric.key == "paraxial_focus_after_stop_mm":
            actual = (
                None
                if analysis.paraxial_focus_distance_mm is None
                else analysis.paraxial_focus_distance_mm - design.explicit_stop_offset_mm
            )
        else:
            actual = getattr(analysis, metric.key, None)
        passed = actual is not None and abs(float(actual) - metric.expected) <= metric.tolerance
        output.append(
            ReferenceValidation(
                key=metric.key,
                label=metric.label,
                expected=metric.expected,
                actual=None if actual is None else float(actual),
                tolerance=metric.tolerance,
                unit=metric.unit,
                passed=passed,
            )
        )
    return output
