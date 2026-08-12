from __future__ import annotations

from math import atan, degrees, hypot

from ..domain import DesignSettings


SENSOR_PRESETS = (
    ("full_frame", "フルフレーム 36 x 24 mm", 36.0, 24.0),
    ("aps_c", "APS-C 23.5 x 15.6 mm", 23.5, 15.6),
    ("canon_aps_c", "Canon APS-C 22.3 x 14.9 mm", 22.3, 14.9),
    ("micro_four_thirds", "マイクロフォーサーズ 17.3 x 13.0 mm", 17.3, 13.0),
    ("one_inch", "1型 13.2 x 8.8 mm", 13.2, 8.8),
    ("medium_44x33", "中判 43.8 x 32.9 mm", 43.8, 32.9),
    ("custom", "カスタム", 36.0, 24.0),
)

WAVELENGTH_PRESETS = {
    "fdc": ("Fraunhofer F-d-C", [0.48613, 0.58756, 0.65627], [1.0, 1.0, 1.0], 0.58756),
    "fedc": ("Fraunhofer F-e-d-C", [0.48613, 0.54607, 0.58756, 0.65627], [1.0, 1.0, 1.0, 1.0], 0.58756),
    "rgb": ("撮像RGB 460-550-620 nm", [0.460, 0.550, 0.620], [1.0, 1.0, 1.0], 0.550),
}


def angle_of_view_deg(sensor_size_mm: float, focal_length_mm: float) -> float:
    if sensor_size_mm <= 0 or focal_length_mm <= 0:
        return 0.0
    return degrees(2.0 * atan(sensor_size_mm / (2.0 * focal_length_mm)))


def sensor_angle_of_view(settings: DesignSettings, focal_length_mm: float | None = None) -> dict[str, float]:
    focal_length = abs(float(focal_length_mm or settings.focal_length_target_mm))
    diagonal = hypot(settings.sensor_width_mm, settings.sensor_height_mm)
    return {
        "horizontal_deg": angle_of_view_deg(settings.sensor_width_mm, focal_length),
        "vertical_deg": angle_of_view_deg(settings.sensor_height_mm, focal_length),
        "diagonal_deg": angle_of_view_deg(diagonal, focal_length),
        "maximum_half_angle_deg": angle_of_view_deg(diagonal, focal_length) / 2.0,
    }


def resolved_field_angles(settings: DesignSettings, focal_length_mm: float | None = None) -> list[float]:
    if settings.field_mode == "angles":
        values = settings.field_angles_deg
    else:
        maximum = sensor_angle_of_view(settings, focal_length_mm)["maximum_half_angle_deg"]
        values = [maximum * fraction for fraction in settings.field_fractions]
    clean = sorted({min(max(float(value), 0.0), 89.0) for value in values})
    return clean or [0.0]


def resolved_field_weights(settings: DesignSettings) -> list[float]:
    source = settings.field_weights
    count = len(settings.field_angles_deg if settings.field_mode == "angles" else settings.field_fractions)
    values = [max(float(value), 0.0) for value in source[:count]]
    values.extend([1.0] * (count - len(values)))
    return values or [1.0]


def sensor_preset_for_size(width_mm: float, height_mm: float) -> str:
    for key, _, width, height in SENSOR_PRESETS:
        if key != "custom" and abs(width_mm - width) < 0.01 and abs(height_mm - height) < 0.01:
            return key
    return "custom"
