from __future__ import annotations

from math import isfinite
from typing import Any, Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QMessageBox,
    QToolButton,
    QWidget,
)


TickFormatter = Callable[[float], str]


class PlotScaleDialog(QDialog):
    def __init__(self, plot: "PlotWidget") -> None:
        super().__init__(plot)
        self.plot = plot
        self.setWindowTitle(f"軸範囲 - {plot.title}")
        self.setModal(True)
        layout = QFormLayout(self)
        x_range, y_range = plot.current_ranges()
        self.x_auto, self.x_minimum, self.x_maximum, x_row = self._axis_row(
            plot.user_x_range is None,
            x_range,
        )
        self.y_auto, self.y_minimum, self.y_maximum, y_row = self._axis_row(
            plot.user_y_range is None,
            y_range,
        )
        layout.addRow("X軸", x_row)
        layout.addRow("Y軸", y_row)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Reset
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("適用")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("閉じる")
        buttons.button(QDialogButtonBox.StandardButton.Reset).setText("自動に戻す")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Reset).clicked.connect(self._reset)
        layout.addRow(buttons)

    @staticmethod
    def _axis_row(
        automatic: bool,
        axis_range: tuple[float, float],
    ) -> tuple[QCheckBox, QDoubleSpinBox, QDoubleSpinBox, QWidget]:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        automatic_check = QCheckBox("自動")
        automatic_check.setChecked(automatic)
        minimum = PlotScaleDialog._spin(axis_range[0])
        maximum = PlotScaleDialog._spin(axis_range[1])
        row_layout.addWidget(automatic_check)
        row_layout.addWidget(minimum)
        row_layout.addWidget(maximum)
        automatic_check.toggled.connect(minimum.setDisabled)
        automatic_check.toggled.connect(maximum.setDisabled)
        minimum.setDisabled(automatic)
        maximum.setDisabled(automatic)
        return automatic_check, minimum, maximum, row

    @staticmethod
    def _spin(value: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(-1_000_000_000.0, 1_000_000_000.0)
        spin.setDecimals(6)
        spin.setValue(float(value))
        spin.setKeyboardTracking(False)
        spin.setAccelerated(True)
        spin.setMinimumWidth(120)
        return spin

    def _reset(self) -> None:
        self.x_auto.setChecked(True)
        self.y_auto.setChecked(True)
        self.plot.set_user_ranges(None, None)
        super().accept()

    def accept(self) -> None:
        x_range = None if self.x_auto.isChecked() else (self.x_minimum.value(), self.x_maximum.value())
        y_range = None if self.y_auto.isChecked() else (self.y_minimum.value(), self.y_maximum.value())
        if x_range is not None and x_range[1] <= x_range[0]:
            QMessageBox.warning(self, "X軸範囲", "最大値は最小値より大きくしてください。")
            return
        if y_range is not None and y_range[1] <= y_range[0]:
            QMessageBox.warning(self, "Y軸範囲", "最大値は最小値より大きくしてください。")
            return
        self.plot.set_user_ranges(x_range, y_range)
        super().accept()


class PlotWidget(QWidget):
    def __init__(self, parent=None, scatter: bool = False, equal_axes: bool = False):
        super().__init__(parent)
        self.scatter = scatter
        self.equal_axes = equal_axes
        self.title = "解析未実行"
        self.x_label = ""
        self.y_label = ""
        self.series: list[dict[str, Any]] = []
        self.x_range: tuple[float, float] | None = None
        self.y_range: tuple[float, float] | None = None
        self.user_x_range: tuple[float, float] | None = None
        self.user_y_range: tuple[float, float] | None = None
        self.y_tick_formatter: TickFormatter | None = None
        self.reference_radius: float | None = None
        self.scale_button = QToolButton(self)
        self.scale_button.setText("軸範囲")
        self.scale_button.setToolTip("このグラフのX軸・Y軸の表示範囲を変更")
        self.scale_button.setAutoRaise(True)
        self.scale_button.clicked.connect(self.open_scale_dialog)
        self.setMinimumSize(300, 230)

    def set_plot(
        self,
        title: str,
        x_label: str,
        y_label: str,
        series: list[dict[str, Any]],
        x_range: tuple[float, float] | None = None,
        y_range: tuple[float, float] | None = None,
        reference_radius: float | None = None,
        y_tick_formatter: TickFormatter | None = None,
    ) -> None:
        self.title = title
        self.x_label = x_label
        self.y_label = y_label
        self.series = series
        self.x_range = x_range
        self.y_range = y_range
        self.reference_radius = reference_radius
        self.y_tick_formatter = y_tick_formatter
        self.update()

    def set_user_ranges(
        self,
        x_range: tuple[float, float] | None,
        y_range: tuple[float, float] | None,
    ) -> None:
        self.user_x_range = x_range
        self.user_y_range = y_range
        self.update()

    def current_ranges(self) -> tuple[tuple[float, float], tuple[float, float]]:
        prepared = self._prepared_series()
        if not prepared:
            return self.user_x_range or self.x_range or (-1.0, 1.0), self.user_y_range or self.y_range or (-1.0, 1.0)
        x_min, x_max, y_min, y_max = self._ranges(prepared)
        return (x_min, x_max), (y_min, y_max)

    def open_scale_dialog(self) -> None:
        PlotScaleDialog(self).exec()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        hint = self.scale_button.sizeHint()
        self.scale_button.setGeometry(max(self.width() - hint.width() - 6, 0), 3, hint.width(), hint.height())
        self.scale_button.raise_()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        painter.setPen(QColor("#26322f"))
        painter.drawText(QRectF(8, 6, self.width() - 88, 20), Qt.AlignmentFlag.AlignHCenter, self.title)

        prepared = self._prepared_series()
        if not prepared:
            painter.setPen(QColor("#77817d"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "解析結果がありません")
            return

        legend_items = [item for item in prepared if item.get("legend", True)]
        legend_width = 126 if legend_items else 18
        left, top, bottom = (110.0 if self.y_tick_formatter else 56.0), 31.0, 43.0
        available_width = max(self.width() - left - legend_width - 12.0, 40.0)
        available_height = max(self.height() - top - bottom, 40.0)
        if self.equal_axes:
            side = min(available_width, available_height)
            plot_rect = QRectF(left + (available_width - side) / 2, top, side, side)
        else:
            plot_rect = QRectF(left, top, available_width, available_height)

        x_min, x_max, y_min, y_max = self._ranges(prepared)
        self._draw_grid(painter, plot_rect, x_min, x_max, y_min, y_max)
        painter.save()
        painter.setClipRect(plot_rect.adjusted(-1, -1, 1, 1))
        for item in prepared:
            color = QColor(item.get("color", "#2b776d"))
            pen = QPen(color, 1.6)
            if item.get("dashed"):
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            points = [self._map_point(x, y, plot_rect, x_min, x_max, y_min, y_max) for x, y in item["points"]]
            if self.scatter:
                painter.setBrush(color)
                painter.setPen(Qt.PenStyle.NoPen)
                for point in points:
                    painter.drawEllipse(point, 1.8, 1.8)
            else:
                path = QPainterPath(points[0])
                for point in points[1:]:
                    path.lineTo(point)
                painter.drawPath(path)
        if self.reference_radius and self.reference_radius > 0:
            center = self._map_point(0.0, 0.0, plot_rect, x_min, x_max, y_min, y_max)
            radius_x = self.reference_radius / (x_max - x_min) * plot_rect.width()
            radius_y = self.reference_radius / (y_max - y_min) * plot_rect.height()
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#59625f"), 1.0, Qt.PenStyle.DashLine))
            painter.drawEllipse(center, radius_x, radius_y)
        painter.restore()
        self._draw_legend(painter, plot_rect.right() + 10, top, legend_items)
        painter.setPen(QColor("#3c4642"))
        painter.drawText(QRectF(plot_rect.left(), self.height() - 25, plot_rect.width(), 18), Qt.AlignmentFlag.AlignCenter, self.x_label)
        painter.save()
        painter.translate(15, plot_rect.center().y())
        painter.rotate(-90)
        painter.drawText(QRectF(-plot_rect.height() / 2, -9, plot_rect.height(), 18), Qt.AlignmentFlag.AlignCenter, self.y_label)
        painter.restore()

    def _prepared_series(self) -> list[dict[str, Any]]:
        output = []
        for item in self.series:
            points = [
                (float(x), float(y))
                for x, y in zip(item.get("x", []), item.get("y", []), strict=False)
                if x is not None and y is not None and isfinite(float(x)) and isfinite(float(y))
            ]
            if points:
                output.append({**item, "points": points})
        return output

    def _ranges(self, prepared):
        all_x = [x for item in prepared for x, _ in item["points"]]
        all_y = [y for item in prepared for _, y in item["points"]]
        active_x_range = self.user_x_range or self.x_range
        active_y_range = self.user_y_range or self.y_range
        x_min, x_max = active_x_range or (min(all_x), max(all_x))
        y_min, y_max = active_y_range or (min(all_y), max(all_y))
        if self.equal_axes and active_x_range is None and active_y_range is None:
            limit = max([abs(value) for value in all_x + all_y] + [self.reference_radius or 0.0, 1e-6]) * 1.08
            return -limit, limit, -limit, limit
        x_min, x_max = self._padded_range(x_min, x_max, active_x_range is None)
        y_min, y_max = self._padded_range(y_min, y_max, active_y_range is None)
        return x_min, x_max, y_min, y_max

    @staticmethod
    def _padded_range(minimum: float, maximum: float, pad: bool) -> tuple[float, float]:
        if maximum <= minimum:
            delta = max(abs(minimum) * 0.1, 1.0)
            return minimum - delta, maximum + delta
        if not pad:
            return minimum, maximum
        delta = (maximum - minimum) * 0.08
        return minimum - delta, maximum + delta

    def _draw_grid(self, painter, rect, x_min, x_max, y_min, y_max):
        metrics = QFontMetrics(painter.font())
        x_tick_count = min(6, max(3, int(rect.width() / 80.0) + 1))
        for index in range(x_tick_count):
            ratio = index / (x_tick_count - 1)
            x = rect.left() + ratio * rect.width()
            painter.setPen(QPen(QColor("#e4e9e7"), 1))
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            painter.setPen(QColor("#59625f"))
            x_text = self._tick(x_min + ratio * (x_max - x_min))
            painter.drawText(QRectF(x - 38, rect.bottom() + 4, 76, 16), Qt.AlignmentFlag.AlignHCenter, x_text)
        y_tick_left = 25.0 if self.y_tick_formatter else 2.0
        for index in range(6):
            ratio = index / 5
            y = rect.bottom() - ratio * rect.height()
            painter.setPen(QPen(QColor("#e4e9e7"), 1))
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            painter.setPen(QColor("#59625f"))
            y_value = y_min + ratio * (y_max - y_min)
            y_text = self.y_tick_formatter(y_value) if self.y_tick_formatter else self._tick(y_value)
            painter.drawText(
                QRectF(
                    y_tick_left,
                    y - metrics.height() / 2,
                    rect.left() - y_tick_left - 7,
                    metrics.height(),
                ),
                Qt.AlignmentFlag.AlignRight,
                y_text,
            )
        painter.setPen(QPen(QColor("#87918d"), 1))
        painter.drawRect(rect)
        if x_min <= 0 <= x_max:
            x_zero = rect.left() + (-x_min) / (x_max - x_min) * rect.width()
            painter.setPen(QPen(QColor("#aab3b0"), 1))
            painter.drawLine(QPointF(x_zero, rect.top()), QPointF(x_zero, rect.bottom()))
        if y_min <= 0 <= y_max:
            y_zero = rect.bottom() - (-y_min) / (y_max - y_min) * rect.height()
            painter.setPen(QPen(QColor("#aab3b0"), 1))
            painter.drawLine(QPointF(rect.left(), y_zero), QPointF(rect.right(), y_zero))

    @staticmethod
    def _map_point(x, y, rect, x_min, x_max, y_min, y_max):
        return QPointF(
            rect.left() + (x - x_min) / (x_max - x_min) * rect.width(),
            rect.bottom() - (y - y_min) / (y_max - y_min) * rect.height(),
        )

    @staticmethod
    def _tick(value: float) -> str:
        absolute = abs(value)
        if absolute >= 100:
            return f"{value:.0f}"
        if absolute >= 10:
            return f"{value:.1f}"
        if absolute >= 1:
            return f"{value:.2f}"
        return f"{value:.3g}"

    @staticmethod
    def _draw_legend(painter, x: float, y: float, prepared) -> None:
        for index, item in enumerate(prepared):
            line_y = y + index * 17 + 8
            color = QColor(item.get("color", "#2b776d"))
            pen = QPen(color, 1.8)
            if item.get("dashed"):
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(QPointF(x, line_y), QPointF(x + 18, line_y))
            painter.setPen(QColor("#3c4642"))
            painter.drawText(QRectF(x + 23, line_y - 8, 98, 16), Qt.AlignmentFlag.AlignLeft, str(item.get("label", "")))
