from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from kirakiralens.domain import OpticalDesign
from kirakiralens.optics.automatic_design import variable_candidates
from kirakiralens.optics.optiland_adapter import FirstOrderAnalysis, OptilandAdapter
from kirakiralens.optics.reference_designs import (
    build_reference_design,
    reference_examples,
    validate_reference_analysis,
)
from kirakiralens.ui.reference_examples_window import ReferenceExamplesWindow
from kirakiralens.ui.main_window import MainWindow


def test_reference_examples_reproduce_patent_first_order_values() -> None:
    examples = reference_examples()
    assert {example.family for example in examples} == {"トリプレット", "テッサー", "ダブルガウス"}
    assert {example.publication for example in examples} == {
        "特開平7-168095",
        "特開2003-005030",
        "特開昭54-104334",
    }

    adapter = OptilandAdapter()
    for example in examples:
        design = example.build()
        analysis = adapter.analyze_first_order(design)
        assert analysis.valid, analysis.error
        results = validate_reference_analysis(design, analysis)
        assert results
        assert all(result.passed for result in results), (example.label, results)


def test_reference_prescription_round_trip_preserves_exact_glass_and_stop() -> None:
    design = build_reference_design("tessar-jp2003005030a-ex1")
    restored = OpticalDesign.from_dict(design.to_dict())

    assert restored.reference_example_key == design.reference_example_key
    assert restored.explicit_stop_after_element == 0
    assert restored.explicit_stop_offset_mm == 3.4748
    assert restored.elements[0].surfaces[0].refractive_index_d == 1.816
    assert restored.elements[0].surfaces[0].abbe_number_d == 46.63

    system = OptilandAdapter().to_optic(restored)
    expected_surfaces = sum(len(element.surfaces) for element in restored.elements) + 3
    assert len(system.surface_group.surfaces) == expected_surfaces
    assert sum(bool(surface.is_stop) for surface in system.surface_group.surfaces) == 1

    first = restored.elements[0]
    first.reverse()
    assert first.surfaces[0].refractive_index_d == 1.816
    assert first.surfaces[0].abbe_number_d == 46.63
    assert first.surfaces[-1].refractive_index_d is None


def test_automatic_variables_account_for_inserted_stop_surface() -> None:
    design = build_reference_design("triplet-jph07168095a-ex1")
    candidates = variable_candidates(
        design,
        {
            "vary_radii": True,
            "vary_thicknesses": True,
            "vary_air_gaps": True,
            "vary_image_plane": True,
        },
    )
    image_gap = next(candidate for candidate in candidates if candidate.kind == "image_gap")
    assert image_gap.surface_number == 7
    assert image_gap.minimum >= 0.0


def test_reference_window_shows_passed_calculation() -> None:
    application = QApplication.instance() or QApplication([])
    design = build_reference_design("double-gauss-jps54104334a-ex1")
    analysis = OptilandAdapter().analyze_first_order(design)
    window = ReferenceExamplesWindow(design, analysis)
    window.show()
    application.processEvents()

    assert window.prescription_table.rowCount() == 12
    assert window.validation_table.rowCount() == 4
    assert "許容差内" in window.status_label.text()
    assert all(
        window.validation_table.item(row, 4).text() == "合格"
        for row in range(window.validation_table.rowCount())
    )
    window.close()


def test_reference_window_waits_for_a_valid_analysis() -> None:
    application = QApplication.instance() or QApplication([])
    design = build_reference_design("tessar-jp2003005030a-ex1")
    analysis = FirstOrderAnalysis(valid=False, engine="Optiland", error="pending")
    window = ReferenceExamplesWindow(design, analysis)
    window.show()
    application.processEvents()

    assert "再計算" in window.status_label.text()
    window.close()


def test_main_window_loads_selected_reference_example() -> None:
    application = QApplication.instance() or QApplication([])
    root = Path(__file__).resolve().parents[1]
    window = MainWindow(root, analyze_on_start=False)
    calculation_requests: list[bool] = []
    window.schedule_analysis = lambda force=False: calculation_requests.append(force)
    window.open_reference_examples()
    dialog = window._reference_examples_window
    index = dialog.example_combo.findData("tessar-jp2003005030a-ex1")
    dialog.example_combo.setCurrentIndex(index)
    dialog.load_button.click()
    application.processEvents()

    assert window.design.reference_example_key == "tessar-jp2003005030a-ex1"
    assert window.design.explicit_stop_offset_mm == 3.4748
    assert calculation_requests == [True]
    window.close()
