from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal, Slot
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
)

from ..catalog.database import CatalogRepository
from ..catalog.edmund import default_paths, import_edmund_catalog
from ..domain import LensElement, OpticalDesign, SurfaceSpec
from ..optics.optiland_adapter import FirstOrderAnalysis, OptilandAdapter
from ..persistence import load_project, save_project
from .lens_view import LensLayoutView
from .panels import CatalogPanel, InspectorPanel, SurfaceTable, spin_box


class AnalysisSignals(QObject):
    finished = Signal(int, object)


class AnalysisWorker(QRunnable):
    def __init__(self, generation: int, design: OpticalDesign):
        super().__init__()
        self.generation = generation
        self.design = OpticalDesign.from_dict(design.to_dict())
        self.signals = AnalysisSignals()

    @Slot()
    def run(self) -> None:
        result = OptilandAdapter().analyze_first_order(self.design)
        self.signals.finished.emit(self.generation, result)


class MainWindow(QMainWindow):
    def __init__(self, repository_root: Path | None = None, analyze_on_start: bool = True):
        super().__init__()
        self.repository_root = repository_root or Path(__file__).resolve().parents[3]
        self.database_path = self.repository_root / "data" / "generated" / "edmund_catalog.sqlite3"
        self.repository = CatalogRepository(self.database_path)
        self.design = OpticalDesign.starter()
        self.current_path: Path | None = None
        self.current_analysis = FirstOrderAnalysis(valid=False, engine="Optiland 0.5.9", error="解析待ち")
        self.selected_element = 0
        self.selected_surface = 0
        self._selected_catalog_product: int | None = None
        self._analysis_generation = 0
        self._thread_pool = QThreadPool.globalInstance()

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
        self.analyze_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload), "再解析", self)
        self.analyze_action.setShortcut(QKeySequence("F5"))
        self.reset_view_action = QAction("全体表示", self)
        self.import_action = QAction("Edmund Excelを再取込", self)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Design", self)
        toolbar.setObjectName("designToolbar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        for action in (self.new_action, self.open_action, self.save_action, self.analyze_action):
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
        self.bfl_target.setValue(self.design.settings.back_focus_target_mm)
        self.bfl_target.setMaximumWidth(110)
        toolbar.addWidget(self.bfl_target)
        toolbar.addWidget(QLabel("最大径"))
        self.max_diameter = spin_box(1.0, 10000.0, 1)
        self.max_diameter.setValue(self.design.settings.max_outer_diameter_mm)
        self.max_diameter.setMaximumWidth(110)
        toolbar.addWidget(self.max_diameter)
        self.addToolBar(toolbar)

    def _build_workspace(self) -> None:
        self.lens_view = LensLayoutView(self)
        self.setCentralWidget(self.lens_view)

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
        table_dock = QDockWidget("面データ", self)
        table_dock.setObjectName("surfaceDock")
        table_dock.setWidget(self.surface_table)
        table_dock.setMinimumHeight(210)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, table_dock)
        self.resizeDocks([catalog_dock, inspector_dock], [490, 330], Qt.Orientation.Horizontal)
        self.resizeDocks([table_dock], [230], Qt.Orientation.Vertical)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("ファイル")
        file_menu.addActions([self.new_action, self.open_action, self.save_action, self.save_as_action])
        design_menu = self.menuBar().addMenu("設計")
        design_menu.addActions([self.analyze_action, self.reset_view_action])
        catalog_menu = self.menuBar().addMenu("カタログ")
        catalog_menu.addAction(self.import_action)

    def _connect_signals(self) -> None:
        self.new_action.triggered.connect(self.new_design)
        self.open_action.triggered.connect(self.open_design)
        self.save_action.triggered.connect(self.save_design)
        self.save_as_action.triggered.connect(lambda: self.save_design(save_as=True))
        self.analyze_action.triggered.connect(self.schedule_analysis)
        self.reset_view_action.triggered.connect(self.lens_view.reset_view)
        self.import_action.triggered.connect(self.reimport_catalog)
        self.catalog_panel.productActivated.connect(self.insert_catalog_product)
        self.catalog_panel.selectionChanged.connect(self._catalog_selected)
        self.lens_view.selectionRequested.connect(self._layout_selected)
        self.lens_view.insertionRequested.connect(self._insertion_requested)
        self.lens_view.gapChangeRequested.connect(self.set_gap_after_element)
        self.lens_view.elementActionRequested.connect(self._element_action_requested)
        self.inspector.designChanged.connect(self._design_changed)
        self.inspector.reverseRequested.connect(self.reverse_element)
        self.inspector.customizeRequested.connect(self.customize_element)
        self.inspector.deleteRequested.connect(self.delete_element)
        self.inspector.surfaceSelectionRequested.connect(lambda element, surface: self._select("surface", element, surface))
        self.surface_table.designChanged.connect(self._design_changed)
        self.surface_table.surfaceSelected.connect(lambda element, surface: self._select("surface", element, surface))
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
        else:
            self.inspector.clear_selection()
        self.inspector.set_analysis(self.current_analysis, self.design)
        self._sync_target_controls()

    def _sync_target_controls(self) -> None:
        controls = (self.focal_target, self.f_number, self.bfl_target, self.max_diameter)
        for control in controls:
            control.blockSignals(True)
        self.focal_target.setValue(self.design.settings.focal_length_target_mm)
        self.f_number.setValue(self.design.settings.f_number_target)
        self.bfl_target.setValue(self.design.settings.back_focus_target_mm)
        self.max_diameter.setValue(self.design.settings.max_outer_diameter_mm)
        for control in controls:
            control.blockSignals(False)

    def _targets_changed(self) -> None:
        self.design.settings.focal_length_target_mm = self.focal_target.value()
        self.design.settings.f_number_target = self.f_number.value()
        requested_bfl = self.bfl_target.value()
        self.design.settings.back_focus_target_mm = requested_bfl
        self.design.settings.max_outer_diameter_mm = self.max_diameter.value()
        if self.design.elements:
            self.design.elements[-1].gap_after_mm = requested_bfl
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
        try:
            self.design.elements[element_index].reverse()
        except ValueError as exc:
            QMessageBox.warning(self, "反転", str(exc))
            return
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
        if self.design.elements:
            self.design.stop_after_element = min(self.design.stop_after_element, len(self.design.elements) - 1)
            self.selected_element = min(element_index, len(self.design.elements) - 1)
            self.selected_surface = 0
            self.lens_view.set_selected("surface", self.selected_element, self.selected_surface)
        else:
            self.selected_element = -1
            self.selected_surface = -1
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
        self.selected_element = element_index
        self._design_changed()

    def _element_action_requested(self, action: str, element_index: int) -> None:
        if action == "delete":
            self.delete_element(element_index)
        elif action == "reverse":
            self.reverse_element(element_index)
        elif action == "customize":
            self.customize_element(element_index)

    def _layout_selected(self, kind: str, element_index: int, surface_index: int) -> None:
        self._select(kind, element_index, surface_index)

    def _select(self, kind: str, element_index: int, surface_index: int = -1) -> None:
        if not 0 <= element_index < len(self.design.elements):
            return
        previous_element = self.selected_element
        self.selected_element = element_index
        if kind == "surface":
            self.selected_surface = surface_index
        elif previous_element != element_index or not 0 <= self.selected_surface < len(self.design.elements[element_index].surfaces):
            self.selected_surface = 0
        self.inspector.set_selection(self.design, self.selected_element, self.selected_surface)
        self.lens_view.set_selected(kind, self.selected_element, self.selected_surface)

    def _design_changed(self) -> None:
        self.current_analysis = FirstOrderAnalysis(valid=False, engine="Optiland 0.5.9", error="解析中")
        self._refresh_all()
        self.schedule_analysis()

    def schedule_analysis(self) -> None:
        self._analysis_generation += 1
        generation = self._analysis_generation
        self.statusBar().showMessage("Optilandで解析中…")
        worker = AnalysisWorker(generation, self.design)
        worker.signals.finished.connect(self._analysis_finished)
        self._thread_pool.start(worker)

    @Slot(int, object)
    def _analysis_finished(self, generation: int, result: FirstOrderAnalysis) -> None:
        if generation != self._analysis_generation:
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

    def new_design(self) -> None:
        self.design = OpticalDesign.starter()
        self.current_path = None
        self.selected_element = 0
        self.selected_surface = 0
        self._design_changed()
        self._update_title()

    def open_design(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "設計を開く", str(self.repository_root), "KiraKiraLens (*.kklens)")
        if not path:
            return
        try:
            self.design = load_project(path)
        except Exception as exc:
            QMessageBox.critical(self, "読込エラー", str(exc))
            return
        self.current_path = Path(path)
        self.selected_element = 0
        self.selected_surface = 0
        self._design_changed()
        self._update_title()

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
