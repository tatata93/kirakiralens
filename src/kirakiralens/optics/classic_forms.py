from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from ..domain import LensElement, OpticalDesign


@dataclass(frozen=True, slots=True)
class ClassicFormSlot:
    key: str
    label: str
    power: str
    shapes: tuple[str, ...]
    target_efl_scale: float
    gap_after_scale: float


@dataclass(frozen=True, slots=True)
class ClassicForm:
    key: str
    label: str
    description: str
    slots: tuple[ClassicFormSlot, ...]
    stop_after_slot: int
    reference_url: str


POSITIVE_SINGLET = ("double_convex", "plano_convex")
NEGATIVE_SINGLET = ("double_concave", "plano_concave")


CLASSIC_FORMS: dict[str, ClassicForm] = {
    "triplet": ClassicForm(
        key="triplet",
        label="Cooke Triplet",
        description="正・負・正の3枚構成。中央負レンズの像側面を絞り面にします。",
        slots=(
            ClassicFormSlot("front_positive", "前群 正単レンズ", "positive", POSITIVE_SINGLET, 1.2, 0.02),
            ClassicFormSlot("middle_negative", "中央 負単レンズ", "negative", NEGATIVE_SINGLET, 1.0, 0.12),
            ClassicFormSlot("rear_positive", "後群 正単レンズ", "positive", POSITIVE_SINGLET, 1.0, 0.0),
        ),
        stop_after_slot=1,
        reference_url="https://patents.google.com/patent/US540132A/en",
    ),
    "tessar": ClassicForm(
        key="tessar",
        label="Tessar",
        description="前側の正・負単レンズと、後側の正接合ダブレットによる4枚3群構成です。",
        slots=(
            ClassicFormSlot("front_positive", "前群 正単レンズ", "positive", POSITIVE_SINGLET, 1.2, 0.03),
            ClassicFormSlot("middle_negative", "中央 負単レンズ", "negative", NEGATIVE_SINGLET, 0.9, 0.08),
            ClassicFormSlot("rear_doublet", "後群 正接合ダブレット", "positive", ("achromatic_doublet",), 1.2, 0.0),
        ),
        stop_after_slot=1,
        reference_url="https://patents.google.com/patent/US721240A/en",
    ),
    "double_gauss": ClassicForm(
        key="double_gauss",
        label="Double Gauss",
        description="絞りを中心に正・正・負／負・正・正を並べる6枚近似構成です。",
        slots=(
            ClassicFormSlot("front_positive_1", "前群 正1", "positive", POSITIVE_SINGLET, 2.0, 0.02),
            ClassicFormSlot("front_positive_2", "前群 正2", "positive", POSITIVE_SINGLET, 1.5, 0.02),
            ClassicFormSlot("front_negative", "前群 負", "negative", NEGATIVE_SINGLET, 1.0, 0.10),
            ClassicFormSlot("rear_negative", "後群 負", "negative", NEGATIVE_SINGLET, 1.0, 0.02),
            ClassicFormSlot("rear_positive_1", "後群 正1", "positive", POSITIVE_SINGLET, 1.5, 0.02),
            ClassicFormSlot("rear_positive_2", "後群 正2", "positive", POSITIVE_SINGLET, 2.0, 0.0),
        ),
        stop_after_slot=2,
        reference_url="https://patents.google.com/patent/US20050185301A1/en",
    ),
}


def classic_form(key: str) -> ClassicForm:
    try:
        return CLASSIC_FORMS[key]
    except KeyError as exc:
        raise ValueError(f"未対応の古典型です: {key}") from exc


def build_classic_design(
    source: OpticalDesign,
    form_key: str,
    elements: list[LensElement],
    target_efl_mm: float,
    image_distance_mm: float,
) -> OpticalDesign:
    form = classic_form(form_key)
    if len(elements) != len(form.slots):
        raise ValueError(f"{form.label}には{len(form.slots)}個の部品が必要です")
    built = deepcopy(source)
    built.name = f"{form.label} catalog candidate"
    built.elements = []
    for slot, source_element in zip(form.slots, elements, strict=True):
        if source_element.shape not in slot.shapes:
            raise ValueError(f"{slot.label}に{source_element.shape}は使用できません")
        element = deepcopy(source_element)
        element.gap_after_mm = max(0.1, target_efl_mm * slot.gap_after_scale)
        element.gap_min_mm = 0.0
        element.gap_max_mm = None
        element.gap_locked = False
        element.element_locked = False
        element.orientation_locked = False
        built.elements.append(element)
    built.elements[-1].gap_after_mm = max(0.0, image_distance_mm)
    built.stop_after_element = form.stop_after_slot
    built.stop_surface_index = None
    built.settings.focal_length_target_mm = target_efl_mm
    built.settings.back_focus_target_mm = image_distance_mm
    return built


def form_summary(form_key: str) -> dict[str, object] | None:
    if not form_key:
        return None
    form = classic_form(form_key)
    return {
        "key": form.key,
        "label": form.label,
        "description": form.description,
        "component_count": len(form.slots),
        "glass_count": sum(2 if slot.shapes == ("achromatic_doublet",) else 1 for slot in form.slots),
        "stop_after_slot": form.stop_after_slot,
        "reference_url": form.reference_url,
    }


def design_matches_form(design: OpticalDesign, form_key: str) -> bool:
    if not form_key:
        return True
    form = classic_form(form_key)
    return (
        len(design.elements) == len(form.slots)
        and all(element.shape in slot.shapes for element, slot in zip(design.elements, form.slots, strict=True))
        and design.stop_after_element == form.stop_after_slot
    )
