from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QStyle,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..catalog.database import CatalogRepository
from ..catalog.edmund import default_paths, import_edmund_catalog
from ..domain import LensElement, OpticalDesign, SurfaceSpec, new_id
from ..optics.optiland_adapter import FirstOrderAnalysis
from ..optics.signature import analysis_signature, design_signature
from ..persistence import load_project, save_project
from .analysis_controller import AnalysisController
from .diagram_editor import DiagramEditor
from .lens_view import LensLayoutView
from .panels import CatalogPanel, InspectorPanel, SurfaceTable, spin_box


class MainWindow(QMainWindow):
    def __init__(self, repository_root: Path | None = None, analyze_on_start: bool = False):
        super().__init__()
        self.repository_root = repository_root or Path(__file__).resolve().parents[3]
        self.database_path = self.repository_root / "data" / "generated" / "edmund_catalog.sqlite3"
        self.repository = CatalogRepository(self.database_path)
        self.design = OpticalDesign.starter()
        self.current_path: Path | None = None
        self.current_analysis = FirstOrderAnalysis(valid=False, engine="Optiland 0.5.9", error="解析待ち")
        self.selected_element = 0
        self.selected_surface = 0
        self.selected_kind = "surface"
        self._selected_catalog_product: int | None = None
        self._performance_window = None
        self._system_settings_window = None
        self._automatic_design_window = None
        self._undo_stack: list[dict] = []
        self._redo_stack: list[dict] = []
        self._restoring_history = False
        self._last_committed_design = deepcopy(self.design.to_dict())
        self._analysis_generation = 0
        self._design_signature = design_signature(self.design)
        self._analysis_signature = analysis_signature(self.design)
        self._analysis_controller = AnalysisController(self.repository_root / ".tmp" / "matplotlib", self)
        self._analysis_debounce = QTimer(self)
        self._analysis_debounce.setSingleShot(True)
        self._analysis_debounce.setInterval(650)
        self._analysis_debounce.timeout.connect(self.schedule_analysis)

        self.setWindowTitle("KiraKiraLens")
        self.resize(1500, 900)
        self.setMinimumSize(1100, 700)
        self.setDockNestingEnabled(True)
        self._build_actions()
        self._build_toolbar()
        self._build_workspace()
        self._build_menu()
        self._connect_signals()
        self._refresh_all()
        self.statusBar().showMessage(f"Edmund Optics catalog: {self.repository.count_products()} products")
        if analyze_on_start:
            QTimer.singleShot(100, self.schedule_analysis)

    def _build_actions(self) -> None:
        style = self.style()
        self.new_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_FileIcon), "新規", self)
        self.new_action.setShortcut(QKeySequence.StandardKey.New)
        self.open_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton), "開く", self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.save_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton), "保存", self)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_as_action = QAction("名前を付けて保存", self)
        self.undo_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_ArrowBack), "元に戻す", self)
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.redo_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_ArrowForward), "やり直す", self)
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        self.analyze_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload), "再解析", self)
        self.analyze_action.setShortcut(QKeySequence("F5"))
        self.performance_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_ComputerIcon), "性能評価", self)
        self.system_settings_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView), "像面・光線条件", self)
        self.automatic_design_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay), "自動設計", self)
        self.reset_view_action = QAction("全体表示", self)
        self.import_action = QAction("Edmund Excelを再取込", self)
        self._update_history_actions()

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Design", self)
        toolbar.setObjectName("designToolbar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        for action in (
            self.new_action,
            self.open_action,
            self.save_action,
            self.undo_action,
            self.redo_action,
            self.analyze_action,
            self.performance_action,
            self.system_settings_action,
            self.automatic_design_action,
        ):
            toolbar.addAction(action)
        toolbar.addSeparator()

        toolbar.addWidget(QLabel("プリセット"))
        self.preset = QComboBox()
        self.preset.addItem("Pentax K / Full Frame / 50 mm / F4")
        self.preset.setMinimumWidth(230)
        toolbar.addWidget(self.preset)
        toolbar.addSeparator()

        toolbar.addWidget(QLabel("焦点距離"))
        self.focal_target = spin_box(1.0, 2000.0, 1)
        self.focal_target.setValue(self.design.settings.focal_length_target_mm)
        self.focal_target.setMaximumWidth(110)
        toolbar.addWidget(self.focal_target)
        toolbar.addWidget(QLabel("F値"))
        self.f_number = spin_box(0.5, 64.0, 1, "")
        self.f_number.setPrefix("F/")
        self.f_number.setValue(self.design.settings.f_number_target)
        self.f_number.setMaximumWidth(90)
        toolbar.addWidget(self.f_number)
        toolbar.addWidget(QLabel("BFL"))
        self.bfl_target = spin_box(0.1, 1000.0, 2)
        self.bfl_target.setValue(
            self.design.elements[-1].gap_after_mm if self.design.elements else self.design.settings.back_focus_target_mm
        )
        self.bfl_target.setMaximumWidth(110)
        toolbar.addWidget(self.bfl_target)
        toolbar.addWidget(QLabel("最大径"))
        self.max_diameter = spin_box(1.0, 10000.0, 1)
        self.max_diameter.setValue(self.design.settings.max_outer_diameter_mm)
        self.max_diameter.setMaximumWidth(110)
        toolbar.addWidget(self.max_diameter)
        self.addToolBar(toolbar)

    def _build_workspace(self) -> None:
        central = QWidget(self)
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        self.diagram_editor = DiagramEditor(central)
        self.lens_view = LensLayoutView(self)
        central_layout.addWidget(self.diagram_editor)
        central_layout.addWidget(self.lens_view, 1)
        self.setCentralWidget(central)

        self.catalog_panel = CatalogPanel(self.repository, self)
        self.catalog_panel.set_design_targets(
            self.design.settings.focal_length_target_mm,
            self.design.settings.f_number_target,
            self.design.settings.max_outer_diameter_mm,
        )
        catalog_dock = QDockWidget("レンズカタログ", self)
        catalog_dock.setObjectName("catalogDock")
        catalog_dock.setWidget(self.catalog_panel)
        catalog_dock.setMinimumWidth(440)
        catalog_dock.setMaximumWidth(540)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, catalog_dock)

        self.inspector = InspectorPanel(self)
        inspector_scroll = QScrollArea(self)
        inspector_scroll.setWidgetResizable(True)
        inspector_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inspector_scroll.setWidget(self.inspector)
        inspector_dock = QDockWidget("選択項目", self)
        inspector_dock.setObjectName("inspectorDock")
        inspector_dock.setWidget(inspector_scroll)
        inspector_dock.setMinimumWidth(310)
        inspector_dock.setMaximumWidth(380)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, inspector_dock)

        self.surface_table = SurfaceTable(self)
        self.surface_dock = QDockWidget("面データ", self)
        self.surface_dock.setObjectName("surfaceDock")
        self.surface_dock.setWidget(self.surface_table)
        self.surface_dock.setMinimumHeight(210)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.surface_dock)
        self.resizeDocks([catalog_dock, inspector_dock], [490, 330], Qt.Orientation.Horizontal)
        self.resizeDocks([self.surface_dock], [230], Qt.Orientation.Vertical)
        self.surface_dock.hide()

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("ファイル")
        file_menu.addActions([self.new_action, self.open_action, self.save_action, self.save_as_action])
        edit_menu = self.menuBar().addMenu("編集")
        edit_menu.addActions([self.undo_action, self.redo_action])
        design_menu = self.menuBar().addMenu("設計")
        design_menu.addActions(
            [
                self.analyze_action,
                self.performance_action,
                self.system_settings_action,
                self.automatic_design_action,
                self.reset_view_action,
            ]
        )
        design_menu.addAction(self.surface_dock.toggleViewAction())
        catalog_menu = self.menuBar().addMenu("カタログ")
        catalog_menu.addAction(self.import_action)

    def _connect_signals(self) -> None:
        self._analysis_controller.finished.connect(self._analysis_finished)
        self._analysis_controller.statusChanged.connect(self.statusBar().showMessage)
        self.new_action.triggered.connect(self.new_design)
        self.open_action.triggered.connect(self.open_design)
        self.save_action.triggered.connect(self.save_design)
        self.save_as_action.triggered.connect(lambda: self.save_design(save_as=True))
        self.undo_action.triggered.connect(self.undo)
        self.redo_action.triggered.connect(self.redo)
        self.analyze_action.triggered.connect(lambda: self.schedule_analysis(force=True))
        self.performance_action.triggered.connect(self.open_performance_window)
        self.system_settings_action.triggered.connect(self.open_system_settings)
        self.automatic_design_action.triggered.connect(self.open_automatic_design)
        self.reset_view_action.triggered.connect(self.lens_view.reset_view)
        self.import_action.triggered.connect(self.reimport_catalog)
        self.catalog_panel.productActivated.connect(self.insert_catalog_product)
        self.catalog_panel.selectionChanged.connect(self._catalog_selected)
        self.lens_view.selectionRequested.connect(self._layout_selected)
        self.lens_view.insertionRequested.connect(self._insertion_requested)
        self.lens_view.gapChangeRequested.connect(self.set_gap_after_element)
        self.lens_view.elementActionRequested.connect(self._element_action_requested)
        self.lens_view.surfaceActionRequested.connect(self._diagram_action_requested)
        self.lens_view.imageEditRequested.connect(self.open_system_settings)
        self.diagram_editor.designChanged.connect(self._design_changed)
        self.diagram_editor.selectionRequested.connect(self._select)
        self.diagram_editor.actionRequested.connect(self._diagram_action_requested)
        self.diagram_editor.insertionRequested.connect(self._insertion_requested)
        self.inspector.designChanged.connect(self._design_changed)
        self.inspector.reverseRequested.connect(self.reverse_element)
        self.inspector.customizeRequested.connect(self.customize_element)
        self.inspector.deleteRequested.connect(self.delete_element)
        self.inspector.surfaceSelectionRequested.connect(lambda element, surface: self._select("surface", element, surface))
        self.surface_table.designChanged.connect(self._design_changed)
        self.surface_table.surfaceSelected.connect(lambda element, surface: self._select("surface", element, surface))
        self.surface_table.imageSelected.connect(self.open_system_settings)
        for widget in (self.focal_target, self.f_number, self.bfl_target, self.max_diameter):
            widget.editingFinished.connect(self._targets_changed)

    def _refresh_all(self) -> None:
        self.lens_view.set_design(self.design, self.current_analysis)
        self.surface_table.set_design(self.design)
        if self.design.elements:
            self.selected_element = min(max(self.selected_element, 0), len(self.design.elements) - 1)
            element = self.design.elements[self.selected_element]
            self.selected_surface = min(max(self.selected_surface, -1), len(element.surfaces) - 1)
            self.inspector.set_selection(self.design, self.selected_element, self.selected_surface)
            self.diagram_editor.set_selection(
                self.design,
                self.selected_kind,
                self.selected_element,
                self.selected_surface,
            )
        else:
            self.inspector.clear_selection()
            self.diagram_editor.clear_selection(self.design)
        self.inspector.set_analysis(self.current_analysis, self.design)
        self._sync_target_controls()

    def _sync_target_controls(self) -> None:
        controls = (self.focal_target, self.f_number, self.bfl_target, self.max_diameter)
        for control in controls:
            control.blockSignals(True)
        self.focal_target.setValue(self.design.settings.focal_length_target_mm)
        self.f_number.setValue(self.design.settings.f_number_target)
        self.bfl_target.setValue(
            self.design.elements[-1].gap_after_mm if self.design.elements else self.design.settings.back_focus_target_mm
        )
        self.max_diameter.setValue(self.design.settings.max_outer_diameter_mm)
        for control in controls:
            control.blockSignals(False)

    def _targets_changed(self) -> None:
        self.design.settings.focal_length_target_mm = self.focal_target.value()
        self.design.settings.f_number_target = self.f_number.value()
        requested_bfl = self.bfl_target.value()
        self.design.settings.max_outer_diameter_mm = self.max_diameter.value()
        if self.design.elements:
            bfl_changed = abs(self.design.elements[-1].gap_after_mm - requested_bfl) > 1e-9
            explicit_bfl_edit = self.sender() is self.bfl_target or (
                self.sender() is None and abs(self.design.elements[-1].gap_after_mm - requested_bfl) >= 0.005
            )
            if explicit_bfl_edit:
                self.design.settings.back_focus_target_mm = requested_bfl
                self.design.elements[-1].gap_after_mm = requested_bfl
                if bfl_changed:
                    self.design.settings.auto_focus_enabled = False
        else:
            self.design.settings.back_focus_target_mm = requested_bfl
        self.catalog_panel.set_design_targets(
            self.focal_target.value(),
            self.f_number.value(),
            self.max_diameter.value(),
        )
        self._design_changed()

    def _catalog_selected(self, product_id: int) -> None:
        self._selected_catalog_product = product_id

    def insert_catalog_product(self, product_id: int, insertion_index: int | None = None) -> None:
        try:
            element = self.repository.element_from_product(product_id)
        except (KeyError, TypeError, ValueError) as exc:
            QMessageBox.warning(self, "カタログ", str(exc))
            return
        if element.outer_diameter_mm > self.design.settings.max_outer_diameter_mm:
            QMessageBox.warning(self, "径制約", "この部品は設計の最大径を超えています。")
            return
        index = insertion_index if insertion_index is not None else self.selected_element + 1
        index = min(max(index, 0), len(self.design.elements))
        self._insert_element(element, index)
        self.selected_element = index
        self.selected_surface = 0
        self.selected_kind = "surface"
        self.statusBar().showMessage(f"{element.manufacturer} {element.part_number} を追加しました", 4000)
        self._design_changed()

    def _insertion_requested(self, kind: str, insertion_index: int) -> None:
        if kind == "catalog":
            product_id = self.catalog_panel.selected_product_id() or self._selected_catalog_product
            if product_id is None:
                self.statusBar().showMessage("左のカタログで挿入するレンズを選択してください", 5000)
                return
            self.insert_catalog_product(product_id, insertion_index)
            return
        element = LensElement(
            name="Custom singlet",
            shape="double_convex",
            outer_diameter_mm=25.0,
            gap_after_mm=2.0,
            surfaces=[
                SurfaceSpec(50.0, "N-BK7", 4.0, 23.0),
                SurfaceSpec(-50.0, "air", 0.0, 23.0),
            ],
        )
        self._insert_element(element, insertion_index)
        self.selected_element = insertion_index
        self.selected_surface = 0
        self.selected_kind = "surface"
        self._design_changed()

    def _insert_element(self, element: LensElement, index: int) -> None:
        index = min(max(index, 0), len(self.design.elements))
        if index > 0:
            previous = self.design.elements[index - 1]
            if index == len(self.design.elements):
                previous.gap_after_mm = min(previous.gap_after_mm, 2.0)
                element.gap_after_mm = self.design.settings.back_focus_target_mm
            else:
                original_gap = previous.gap_after_mm
                internal_thickness = sum(surface.thickness_after_mm for surface in element.surfaces[:-1])
                previous.gap_after_mm = min(1.0, max(original_gap * 0.25, 0.1))
                element.gap_after_mm = max(0.1, original_gap - previous.gap_after_mm - internal_thickness)
        self.design.elements.insert(index, element)
        if index <= self.design.stop_after_element:
            self.design.stop_after_element += 1

    def reverse_element(self, element_index: int) -> None:
        if not 0 <= element_index < len(self.design.elements):
            return
        surface_count = len(self.design.elements[element_index].surfaces)
        try:
            self.design.elements[element_index].reverse()
        except ValueError as exc:
            QMessageBox.warning(self, "反転", str(exc))
            return
        if self.design.stop_after_element == element_index and self.design.stop_surface_index is not None:
            self.design.stop_surface_index = surface_count - 1 - self.design.stop_surface_index
        self._design_changed()

    def customize_element(self, element_index: int) -> None:
        if not 0 <= element_index < len(self.design.elements):
            return
        self.design.elements[element_index] = self.design.elements[element_index].custom_copy()
        self._design_changed()

    def delete_element(self, element_index: int) -> None:
        if not 0 <= element_index < len(self.design.elements):
            return
        old_count = len(self.design.elements)
        removed = self.design.elements.pop(element_index)
        if self.design.elements and element_index > 0:
            previous = self.design.elements[element_index - 1]
            if element_index == old_count - 1:
                previous.gap_after_mm = self.design.settings.back_focus_target_mm
            else:
                internal_thickness = sum(surface.thickness_after_mm for surface in removed.surfaces[:-1])
                previous.gap_after_mm += internal_thickness + removed.gap_after_mm
        if self.design.stop_after_element > element_index:
            self.design.stop_after_element -= 1
        elif self.design.stop_after_element == element_index:
            self.design.stop_after_element = max(0, element_index - 1)
            self.design.stop_surface_index = None
        if self.design.elements:
            self.design.stop_after_element = min(self.design.stop_after_element, len(self.design.elements) - 1)
            self.selected_element = min(element_index, len(self.design.elements) - 1)
            self.selected_surface = 0
            self.selected_kind = "surface"
            self.lens_view.set_selected("surface", self.selected_element, self.selected_surface)
        else:
            self.selected_element = -1
            self.selected_surface = -1
            self.selected_kind = ""
        self.statusBar().showMessage(f"{removed.part_number or removed.name} を削除しました", 4000)
        self._design_changed()

    def set_gap_after_element(self, element_index: int, gap_mm: float) -> None:
        if not 0 <= element_index < len(self.design.elements):
            return
        element = self.design.elements[element_index]
        if element.gap_locked:
            self.statusBar().showMessage("この間隔は固定されています", 3000)
            return
        element.gap_after_mm = max(element.gap_min_mm, gap_mm)
        if element.gap_max_mm is not None:
            element.gap_after_mm = min(element.gap_after_mm, element.gap_max_mm)
        if element_index == len(self.design.elements) - 1:
            self.design.settings.back_focus_target_mm = element.gap_after_mm
            self.design.settings.auto_focus_enabled = False
        self.selected_element = element_index
        self.selected_kind = "gap"
        self._design_changed()

    def _element_action_requested(self, action: str, element_index: int) -> None:
        if action == "delete":
            self.delete_element(element_index)
        elif action == "reverse":
            self.reverse_element(element_index)
        elif action == "customize":
            self.customize_element(element_index)

    def _diagram_action_requested(self, action: str, element_index: int, surface_index: int) -> None:
        if action in {"delete", "reverse", "customize"}:
            self._element_action_requested(action, element_index)
        elif action == "element_duplicate":
            self.duplicate_element(element_index)
        elif action == "surface_insert_before":
            self.insert_surface(element_index, surface_index)
        elif action == "surface_insert_after":
            self.insert_surface(element_index, surface_index + 1)
        elif action == "surface_duplicate":
            self.insert_surface(element_index, surface_index + 1, duplicate_index=surface_index)
        elif action == "surface_delete":
            self.delete_surface(element_index, surface_index)
        elif action == "surface_toggle_plane":
            self.toggle_surface_plane(element_index, surface_index)
        elif action == "surface_toggle_radius_lock":
            self.toggle_surface_radius_lock(element_index, surface_index)
        elif action == "gap_zero":
            self.set_gap_after_element(element_index, 0)
        elif action == "gap_toggle_lock":
            if 0 <= element_index < len(self.design.elements):
                element = self.design.elements[element_index]
                element.gap_locked = not element.gap_locked
                self._design_changed()
        elif action == "set_stop":
            if 0 <= element_index < len(self.design.elements):
                self.design.stop_after_element = element_index
                surface_count = len(self.design.elements[element_index].surfaces)
                self.design.stop_surface_index = (
                    surface_index if 0 <= surface_index < surface_count else surface_count - 1
                )
                self._design_changed()

    def duplicate_element(self, element_index: int) -> None:
        if not 0 <= element_index < len(self.design.elements):
            return
        duplicate = deepcopy(self.design.elements[element_index])
        duplicate.id = new_id()
        self._insert_element(duplicate, element_index + 1)
        self.selected_element = element_index + 1
        self.selected_surface = 0
        self.selected_kind = "surface"
        self._design_changed()

    def insert_surface(self, element_index: int, insertion_index: int, duplicate_index: int | None = None) -> None:
        if not 0 <= element_index < len(self.design.elements):
            return
        element = self.design.elements[element_index]
        if element.is_catalog:
            self.statusBar().showMessage("面構成を変える前にカタログ品をカスタム化してください", 5000)
            return
        insertion_index = min(max(insertion_index, 0), len(element.surfaces))
        reference_index = duplicate_index if duplicate_index is not None else min(insertion_index, len(element.surfaces) - 1)
        reference = element.surfaces[reference_index]
        new_surface = deepcopy(reference) if duplicate_index is not None else SurfaceSpec(
            radius_mm=None,
            material_after="air",
            thickness_after_mm=1.0,
            clear_aperture_mm=reference.clear_aperture_mm,
        )
        if insertion_index == 0:
            new_surface.material_after = element.surfaces[0].material_after
            new_surface.thickness_after_mm = 1.0
        elif insertion_index < len(element.surfaces):
            previous = element.surfaces[insertion_index - 1]
            original_distance = previous.thickness_after_mm
            previous.thickness_after_mm = original_distance / 2
            new_surface.material_after = previous.material_after
            new_surface.thickness_after_mm = original_distance - previous.thickness_after_mm
        else:
            previous = element.surfaces[-1]
            original_gap = element.gap_after_mm
            previous.thickness_after_mm = original_gap / 2
            new_surface.material_after = "air"
            new_surface.thickness_after_mm = 0
            element.gap_after_mm = original_gap - previous.thickness_after_mm
        element.surfaces.insert(insertion_index, new_surface)
        if (
            self.design.stop_after_element == element_index
            and self.design.stop_surface_index is not None
            and insertion_index <= self.design.stop_surface_index
        ):
            self.design.stop_surface_index += 1
        self.selected_element = element_index
        self.selected_surface = insertion_index
        self.selected_kind = "surface"
        self._design_changed()

    def delete_surface(self, element_index: int, surface_index: int) -> None:
        if not 0 <= element_index < len(self.design.elements):
            return
        element = self.design.elements[element_index]
        if element.is_catalog:
            self.statusBar().showMessage("面を削除する前にカタログ品をカスタム化してください", 5000)
            return
        if len(element.surfaces) <= 2:
            self.statusBar().showMessage("レンズ要素には最低2面が必要です", 4000)
            return
        if not 0 <= surface_index < len(element.surfaces):
            return
        is_last = surface_index == len(element.surfaces) - 1
        removed = element.surfaces[surface_index]
        if surface_index > 0:
            previous = element.surfaces[surface_index - 1]
            if is_last:
                element.gap_after_mm += previous.thickness_after_mm
                previous.thickness_after_mm = 0
                previous.material_after = "air"
            else:
                previous.thickness_after_mm += removed.thickness_after_mm
                previous.material_after = removed.material_after
        element.surfaces.pop(surface_index)
        if self.design.stop_after_element == element_index and self.design.stop_surface_index is not None:
            if surface_index < self.design.stop_surface_index:
                self.design.stop_surface_index -= 1
            elif surface_index == self.design.stop_surface_index:
                self.design.stop_surface_index = min(surface_index, len(element.surfaces) - 1)
        self.selected_element = element_index
        self.selected_surface = min(surface_index, len(element.surfaces) - 1)
        self.selected_kind = "surface"
        self._design_changed()

    def toggle_surface_plane(self, element_index: int, surface_index: int) -> None:
        if not 0 <= element_index < len(self.design.elements):
            return
        element = self.design.elements[element_index]
        if element.is_catalog or not 0 <= surface_index < len(element.surfaces):
            self.statusBar().showMessage("カタログ面を変更する前にカスタム化してください", 5000)
            return
        surface = element.surfaces[surface_index]
        surface.radius_mm = 50.0 if surface.is_plane else None
        self.selected_kind = "surface"
        self.selected_element = element_index
        self.selected_surface = surface_index
        self._design_changed()

    def toggle_surface_radius_lock(self, element_index: int, surface_index: int) -> None:
        if not 0 <= element_index < len(self.design.elements):
            return
        element = self.design.elements[element_index]
        if element.is_catalog or not 0 <= surface_index < len(element.surfaces):
            self.statusBar().showMessage("カタログ面を変更する前にカスタム化してください", 5000)
            return
        surface = element.surfaces[surface_index]
        surface.radius_locked = not surface.radius_locked
        self.selected_kind = "surface"
        self.selected_element = element_index
        self.selected_surface = surface_index
        self._design_changed()

    def _layout_selected(self, kind: str, element_index: int, surface_index: int) -> None:
        self._select(kind, element_index, surface_index)

    def _select(self, kind: str, element_index: int, surface_index: int = -1) -> None:
        if not 0 <= element_index < len(self.design.elements):
            return
        previous_element = self.selected_element
        self.selected_kind = kind
        self.selected_element = element_index
        if kind == "surface":
            self.selected_surface = surface_index
        elif previous_element != element_index or not 0 <= self.selected_surface < len(self.design.elements[element_index].surfaces):
            self.selected_surface = 0
        self.inspector.set_selection(self.design, self.selected_element, self.selected_surface)
        self.diagram_editor.set_selection(self.design, kind, self.selected_element, self.selected_surface)
        self.lens_view.set_selected(kind, self.selected_element, self.selected_surface)

    def _design_changed(self) -> None:
        signature = design_signature(self.design)
        if signature == self._design_signature:
            return
        if not self._restoring_history:
            self._undo_stack.append(deepcopy(self._last_committed_design))
            self._undo_stack = self._undo_stack[-100:]
            self._redo_stack.clear()
        self._last_committed_design = deepcopy(self.design.to_dict())
        self._update_history_actions()
        self._design_signature = signature
        optical_signature = analysis_signature(self.design)
        optical_change = optical_signature != self._analysis_signature
        self._analysis_signature = optical_signature
        if optical_change:
            self.current_analysis = FirstOrderAnalysis(valid=False, engine="Optiland 0.5.9", error="解析待ち")
            self._analysis_generation += 1
        self._refresh_all()
        if self._performance_window is not None:
            self._performance_window.set_design(self.design)
        if self._system_settings_window is not None and self.sender() is not self._system_settings_window:
            self._system_settings_window.set_design(self.design)
        if self._automatic_design_window is not None:
            self._automatic_design_window.set_design(self.design)
        if optical_change:
            self._analysis_debounce.start()

    def schedule_analysis(self, force: bool = False) -> None:
        self._analysis_debounce.stop()
        generation = self._analysis_generation
        self._analysis_controller.submit(generation, self.design, force=force)

    @Slot(int, object)
    def _analysis_finished(self, generation: int, result: FirstOrderAnalysis) -> None:
        if generation != self._analysis_generation:
            return
        if self._apply_automatic_image_focus(result):
            return
        self.current_analysis = result
        self.inspector.set_analysis(result, self.design)
        self.lens_view.set_design(self.design, result)
        if result.valid:
            self.statusBar().showMessage(
                f"{result.engine}: EFL {result.effective_focal_length_mm:.3f} mm / BFL {result.back_focal_length_mm:.3f} mm",
                8000,
            )
        else:
            self.statusBar().showMessage(f"解析失敗: {result.error}", 10000)

    def _apply_automatic_image_focus(self, result: FirstOrderAnalysis) -> bool:
        if (
            not result.valid
            or not self.design.elements
            or not self.design.settings.auto_focus_enabled
            or self.design.elements[-1].gap_locked
            or result.recommended_image_distance_mm is None
        ):
            return False
        current = self.design.elements[-1].gap_after_mm
        recommended = max(0.0, float(result.recommended_image_distance_mm))
        last_element = self.design.elements[-1]
        recommended = max(last_element.gap_min_mm, recommended)
        if last_element.gap_max_mm is not None:
            recommended = min(recommended, last_element.gap_max_mm)
        if abs(current - recommended) < 1e-4:
            return False
        last_element.gap_after_mm = recommended
        self._last_committed_design = deepcopy(self.design.to_dict())
        self._design_signature = design_signature(self.design)
        self._analysis_signature = analysis_signature(self.design)
        self._analysis_generation += 1
        self.current_analysis = FirstOrderAnalysis(valid=False, engine=result.engine, error="像面追従後の解析待ち")
        self._refresh_all()
        if self._performance_window is not None:
            self._performance_window.set_design(self.design)
        if self._system_settings_window is not None:
            self._system_settings_window.set_design(self.design)
        self.statusBar().showMessage(f"像面を最良焦点 {recommended:.3f} mmへ移動しました", 4000)
        self._analysis_debounce.start()
        return True

    def new_design(self) -> None:
        self._replace_design(OpticalDesign.starter())
        self.current_path = None
        self._update_title()

    def open_design(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "設計を開く", str(self.repository_root), "KiraKiraLens (*.kklens)")
        if not path:
            return
        try:
            design = load_project(path)
        except Exception as exc:
            QMessageBox.critical(self, "読込エラー", str(exc))
            return
        self.current_path = Path(path)
        self._replace_design(design)
        self._update_title()

    def _replace_design(self, design: OpticalDesign) -> None:
        self.design = design
        self.selected_element = 0 if design.elements else -1
        self.selected_surface = 0 if design.elements else -1
        self.selected_kind = "surface" if design.elements else ""
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._last_committed_design = deepcopy(design.to_dict())
        self._design_signature = design_signature(design)
        self._analysis_signature = analysis_signature(design)
        self._analysis_generation += 1
        self.current_analysis = FirstOrderAnalysis(valid=False, engine="Optiland 0.5.9", error="解析待ち")
        self._refresh_all()
        if self._performance_window is not None:
            self._performance_window.set_design(design)
        if self._system_settings_window is not None:
            self._system_settings_window.set_design(design)
        if self._automatic_design_window is not None:
            self._automatic_design_window.set_design(design)
        self._update_history_actions()
        self._analysis_debounce.start()

    def undo(self) -> None:
        if not self._undo_stack:
            return
        self._redo_stack.append(deepcopy(self.design.to_dict()))
        self._restore_history(self._undo_stack.pop())

    def redo(self) -> None:
        if not self._redo_stack:
            return
        self._undo_stack.append(deepcopy(self.design.to_dict()))
        self._restore_history(self._redo_stack.pop())

    def _restore_history(self, snapshot: dict) -> None:
        self._restoring_history = True
        try:
            self.design = OpticalDesign.from_dict(deepcopy(snapshot))
            self._last_committed_design = deepcopy(snapshot)
            self._design_signature = design_signature(self.design)
            self._analysis_signature = analysis_signature(self.design)
            self._analysis_generation += 1
            self.current_analysis = FirstOrderAnalysis(valid=False, engine="Optiland 0.5.9", error="解析待ち")
            self._refresh_all()
            if self._performance_window is not None:
                self._performance_window.set_design(self.design)
            if self._system_settings_window is not None:
                self._system_settings_window.set_design(self.design)
            self._analysis_debounce.start()
        finally:
            self._restoring_history = False
            self._update_history_actions()

    def _update_history_actions(self) -> None:
        if hasattr(self, "undo_action"):
            self.undo_action.setEnabled(bool(self._undo_stack))
            self.redo_action.setEnabled(bool(self._redo_stack))

    def save_design(self, save_as: bool = False) -> None:
        destination = self.current_path
        if destination is None or save_as:
            path, _ = QFileDialog.getSaveFileName(self, "設計を保存", str(self.repository_root / f"{self.design.name}.kklens"), "KiraKiraLens (*.kklens)")
            if not path:
                return
            destination = Path(path)
        try:
            self.current_path = save_project(self.design, destination)
        except Exception as exc:
            QMessageBox.critical(self, "保存エラー", str(exc))
            return
        self.statusBar().showMessage(f"保存しました: {self.current_path}", 5000)
        self._update_title()

    def _update_title(self) -> None:
        suffix = f" — {self.current_path.name}" if self.current_path else ""
        self.setWindowTitle(f"KiraKiraLens{suffix}")

    def reimport_catalog(self) -> None:
        source, database, csv_output, report = default_paths()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = import_edmund_catalog(source, database, csv_output, report)
        except Exception as exc:
            QMessageBox.critical(self, "取込エラー", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.catalog_panel.refresh()
        self.statusBar().showMessage(f"{result.accepted}品を設計可能として取り込みました", 8000)

    def open_performance_window(self) -> None:
        if self._performance_window is None:
            from .performance_window import PerformanceWindow

            self._performance_window = PerformanceWindow(self.design, self.repository_root, self)
        else:
            self._performance_window.set_design(self.design)
        self._performance_window.show()
        self._performance_window.raise_()
        self._performance_window.activateWindow()

    def open_system_settings(self) -> None:
        if self._system_settings_window is None:
            from .system_settings_window import SystemSettingsWindow

            self._system_settings_window = SystemSettingsWindow(self.design, self)
            self._system_settings_window.designChanged.connect(self._design_changed)
        else:
            self._system_settings_window.set_design(self.design)
        self._system_settings_window.show_image_tab()
        self._system_settings_window.show()
        self._system_settings_window.raise_()
        self._system_settings_window.activateWindow()

    def open_automatic_design(self) -> None:
        if self._automatic_design_window is None:
            from .automatic_design_window import AutomaticDesignWindow

            self._automatic_design_window = AutomaticDesignWindow(self.design, self.repository_root, self)
            self._automatic_design_window.applyRequested.connect(self._apply_automatic_design)
        else:
            self._automatic_design_window.set_design(self.design)
        self._automatic_design_window.show()
        self._automatic_design_window.raise_()
        self._automatic_design_window.activateWindow()

    def _apply_automatic_design(self, optimized_design: OpticalDesign) -> None:
        previous = deepcopy(self.design.to_dict())
        self.design = optimized_design
        self._last_committed_design = previous
        self._design_signature = design_signature(OpticalDesign.from_dict(previous))
        self._design_changed()
        self.statusBar().showMessage("自動設計の最良案を適用しました", 6000)

    def closeEvent(self, event) -> None:
        self._analysis_debounce.stop()
        self._analysis_controller.shutdown()
        if self._performance_window is not None:
            self._performance_window.shutdown()
        if self._system_settings_window is not None:
            self._system_settings_window.close()
        if self._automatic_design_window is not None:
            self._automatic_design_window.shutdown()
        super().closeEvent(event)
