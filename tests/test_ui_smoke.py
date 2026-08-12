from __future__ import annotations

import os
from time import perf_counter
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QContextMenuEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from kirakiralens.ui.main_window import MainWindow


def test_main_window_constructs_with_generated_catalog() -> None:
    application = QApplication.instance() or QApplication([])
    root = Path(__file__).resolve().parents[1]
    window = MainWindow(root, analyze_on_start=False)
    window.show()
    application.processEvents()

    assert window.repository.count_products() == 920
    assert window.design.settings.back_focus_target_mm == 45.46
    assert window.lens_view.scene().items()

    window._select("element", 0)
    assert window.inspector.surface_selector.count() == 2
    assert window.inspector.surface_index == 0
    window.inspector.surface_selector.setCurrentIndex(1)
    application.processEvents()
    assert window.selected_surface == 1

    window._select("surface", 0, 0)
    editor = window.diagram_editor
    editor.surface_radius.setValue(55)
    editor.surface_distance.setValue(6)
    editor.surface_material.setText("N-LAK22")
    editor.surface_aperture.setValue(27)
    editor.surface_coating.setText("Test AR")
    editor.surface_type.setCurrentIndex(editor.surface_type.findData("even_asphere"))
    editor.surface_conic.setValue(-0.5)
    editor.surface_coefficients.setText("0, 1e-7")
    editor.surface_comment.setText("Front asphere")
    editor._apply_surface()
    surface = window.design.elements[0].surfaces[0]
    assert surface.radius_mm == 55
    assert surface.thickness_after_mm == 6
    assert surface.material_after == "N-LAK22"
    assert surface.clear_aperture_mm == 27
    assert surface.coating == "Test AR"
    assert surface.surface_type == "even_asphere"
    assert surface.conic == -0.5
    assert surface.asphere_coefficients == [0.0, 1e-7]
    assert surface.comment == "Front asphere"
    editor.stop_surface.setChecked(True)
    editor._apply_surface()
    assert window.design.stop_after_element == 0
    assert window.design.stop_surface_index == 0

    surface_count = len(window.design.elements[0].surfaces)
    window.insert_surface(0, 1)
    assert len(window.design.elements[0].surfaces) == surface_count + 1
    window.delete_surface(0, 1)
    assert len(window.design.elements[0].surfaces) == surface_count

    geometry, _ = window.lens_view._geometry(window.design)
    for surface_index, surface_z in enumerate(geometry[0]):
        surface_position = window.lens_view.mapFromScene(QPointF(surface_z, 0))
        surface_item = window.lens_view._interactive_item_at(surface_position)
        assert surface_item.data(0) == "surface"
        assert surface_item.data(2) == surface_index
    viewport_position = window.lens_view.mapFromScene(QPointF(geometry[0][0], 0))
    context_event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse,
        viewport_position,
        window.lens_view.mapToGlobal(viewport_position),
    )
    started = perf_counter()
    window.lens_view.contextMenuEvent(context_event)
    assert perf_counter() - started < 0.5
    assert window.lens_view._context_menu is not None
    first_menu = window.lens_view._context_menu
    window.lens_view.contextMenuEvent(context_event)
    assert window.lens_view._context_menu is not first_menu
    window.lens_view._context_menu.close()

    gap_item = max(
        (item for item in window.lens_view.scene().items() if item.data(0) == "gap" and item.data(1) == 0),
        key=lambda item: item.zValue(),
    )
    gap_position = window.lens_view.mapFromScene(gap_item.sceneBoundingRect().center())
    gap_event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse,
        gap_position,
        window.lens_view.mapToGlobal(gap_position),
    )
    window.lens_view.contextMenuEvent(gap_event)
    assert window.selected_kind == "gap"
    window.lens_view._context_menu.close()

    original_gap = window.design.elements[0].gap_after_mm
    moved_position = gap_position + QPoint(25, 0)
    for event_type, position, button, buttons in (
        (QEvent.Type.MouseButtonPress, gap_position, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseMove, moved_position, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseButtonRelease, moved_position, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton),
    ):
        event = QMouseEvent(
            event_type,
            QPointF(position),
            QPointF(window.lens_view.mapToGlobal(position)),
            button,
            buttons,
            Qt.KeyboardModifier.NoModifier,
        )
        if event_type == QEvent.Type.MouseButtonPress:
            window.lens_view.mousePressEvent(event)
        elif event_type == QEvent.Type.MouseMove:
            window.lens_view.mouseMoveEvent(event)
        else:
            window.lens_view.mouseReleaseEvent(event)
    application.processEvents()
    assert window.design.elements[0].gap_after_mm > original_gap

    element_item = next(
        item for item in window.lens_view.scene().items() if item.data(0) == "element" and item.data(1) == 2
    )
    element_position = window.lens_view.mapFromScene(element_item.sceneBoundingRect().center())
    element_event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse,
        element_position,
        window.lens_view.mapToGlobal(element_position),
    )
    window.lens_view.contextMenuEvent(element_event)
    assert window.selected_kind == "element"
    window.lens_view._context_menu.close()

    window.set_gap_after_element(0, 12.5)
    assert window.design.elements[0].gap_after_mm == 12.5
    element_count = len(window.design.elements)
    window.delete_element(1)
    assert len(window.design.elements) == element_count - 1

    assert window.catalog_panel.min_diameter.maximum() == 10000
    assert window.inspector.diameter.maximum() == 10000
    assert window.surface_dock.isHidden()
    window.close()
    application.processEvents()
