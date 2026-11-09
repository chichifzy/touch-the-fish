"""设置对话框。

允许配置：
- 显示模式：单行 / 双行
- 跳行方式：自动 / 手动
- 自动跳行间隔（秒）
- 每次前进行数：下一行 / 下两行
- 字体大小
- 每行文字数量
- 导入文档
所有更改实时应用到浮窗（通过信号回传）。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListView,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .config import Config


class DarkComboBox(QComboBox):
    """下拉框：首次弹出时给弹窗容器（QComboBoxPrivateContainer）刷深色背景。

    该容器是 Qt 私有类，在 macOS 上无法用 QSS 类名选中，默认白色会在列表
    上下边距处露出白边。这里在 showPopup 后直接对容器设 palette + 背景 +
    清零边距来消除白边。
    """

    _CONTAINER_QSS = "background:#2d3138; border:1px solid #3d434d; border-radius:8px;"

    def showPopup(self):
        super().showPopup()
        container = self.view().parentWidget()
        if container is not None:
            container.setContentsMargins(0, 0, 0, 0)
            container.setAutoFillBackground(True)
            pal = container.palette()
            pal.setColor(QPalette.Window, QColor("#2d3138"))
            container.setPalette(pal)
            container.setStyleSheet(self._CONTAINER_QSS)


STYLE = """
QDialog { background: #23262b; }
QLabel { color: #cfd3da; font-size: 13px; }
QLabel#progress {
    color: #8a94a6;
    font-size: 12px;
    padding: 6px 0;
}
QComboBox, QSpinBox {
    background: #2d3138;
    border: 1px solid #3d434d;
    border-radius: 8px;
    padding: 5px 8px;
    color: #e6e9ee;
    min-height: 20px;
    min-width: 150px;
}
QComboBox:focus, QSpinBox:focus {
    border: 1px solid #5a86c2;
}
QComboBox::drop-down, QSpinBox::up-button, QSpinBox::down-button {
    border: none;
    background: transparent;
    width: 16px;
}
QSlider { min-width: 150px; }
QSlider::groove:horizontal {
    height: 4px;
    background: #3d434d;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #5a86c2;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #cfd3da;
    width: 14px;
    height: 14px;
    margin: -6px 0;
    border-radius: 7px;
}
QSlider::handle:horizontal:hover { background: #ffffff; }
QComboBox QAbstractItemView {
    background: #2d3138;
    border: 1px solid #3d434d;
    border-radius: 8px;
    padding: 4px;
    margin: 0px;
    outline: none;
    color: #e6e9ee;
    selection-background-color: transparent;
}
QComboBox QAbstractItemView::item {
    min-height: 26px;
    padding: 3px 10px;
    border: none;
    border-radius: 6px;
    color: #e6e9ee;
    background: transparent;
}
QComboBox QAbstractItemView::item:hover {
    background: #354056;
    color: #ffffff;
}
QComboBox QAbstractItemView::item:selected {
    background: #3d5a80;
    color: #ffffff;
}
QPushButton {
    background: #3d5a80;
    color: #ffffff;
    border: none;
    border-radius: 9px;
    padding: 8px 20px;
    font-weight: bold;
}
QPushButton:hover { background: #4a6d99; }
QPushButton:pressed { background: #34506f; }
QCheckBox { color: #cfd3da; font-size: 13px; spacing: 8px; }
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #3d434d;
    border-radius: 4px;
    background: #2d3138;
}
QCheckBox::indicator:checked {
    background: #5a86c2;
    border: 1px solid #5a86c2;
}
"""


class SettingsDialog(QDialog):
    # (need_rebuild_lines, need_reapply_mode)
    settings_changed = Signal(bool, bool)
    # 请求导入文档（由浮窗处理文件选择）
    import_requested = Signal()
    # 请求切换 Dock 栏图标显示（仅 macOS）
    dock_icon_toggled = Signal(bool)
    # “未悬浮隐藏文本”勾选项变化（携带新状态），由浮窗应用显隐并播放边框特效
    hide_text_toggled = Signal(bool)

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("设置")
        self.setFixedWidth(340)
        self.setStyleSheet(STYLE)
        self._loading = True
        self._build_ui()
        self._load_from_config()
        self._loading = False

    def _make_combo(self, items: list[str]) -> QComboBox:
        """创建统一风格的下拉框：用 QListView 作弹出视图并关闭交替行底色，
        保证样式表完全生效，避免 macOS 原生弹窗出现黑白条纹。"""
        combo = DarkComboBox()
        view = QListView()
        view.setAlternatingRowColors(False)
        view.setSpacing(1)
        view.setUniformItemSizes(True)
        combo.setView(view)
        combo.addItems(items)
        return combo

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(12)

        # 显示模式
        self.display_mode = self._make_combo(["单行显示", "双行显示", "三行显示"])
        self.display_mode.currentIndexChanged.connect(self._on_change)
        form.addRow("显示模式", self.display_mode)

        # 跳行方式
        self.advance_mode = self._make_combo(["自动跳行", "手动跳行"])
        self.advance_mode.currentIndexChanged.connect(self._on_advance_mode_changed)
        form.addRow("跳行方式", self.advance_mode)

        # 每次前进行数（单行模式禁用；双行=1/2 行；三行=1/3 行）
        self.step = self._make_combo(["每次一行", "每次多行"])
        self.step.currentIndexChanged.connect(self._on_change)
        self._step_label = QLabel("跳行步进")
        form.addRow(self._step_label, self.step)

        # 翻页动画：无动画 / 平滑滚动
        self.page_animation = self._make_combo(["无动画", "平滑滚动"])
        self.page_animation.currentIndexChanged.connect(self._on_page_animation_changed)
        form.addRow("翻页动画", self.page_animation)

        # 行间距（仅双行模式可用）：0-12px，粒度 1px
        self.line_spacing = QSlider(Qt.Horizontal)
        self.line_spacing.setRange(0, 12)
        self.line_spacing.setSingleStep(1)
        self.line_spacing.setPageStep(1)
        self.line_spacing.valueChanged.connect(self._on_line_spacing_changed)
        self._line_spacing_value = QLabel()
        self._line_spacing_label = QLabel("行间距")
        form.addRow(
            self._line_spacing_label,
            self._slider_row(self.line_spacing, self._line_spacing_value),
        )

        # 自动间隔：1-6 秒，粒度 0.5 秒（滑块以半秒为单位，范围 2-12）
        self.interval = QSlider(Qt.Horizontal)
        self.interval.setRange(2, 12)
        self.interval.setSingleStep(1)
        self.interval.setPageStep(1)
        self.interval.valueChanged.connect(self._on_interval_changed)
        self._interval_value = QLabel()
        self._interval_label = QLabel("自动跳行间隔")
        self._interval_row = self._slider_row(self.interval, self._interval_value)
        form.addRow(self._interval_label, self._interval_row)

        # 字号：10-24px，粒度 2px（滑块以 2px 为单位，范围 5-12）
        self.font_size = QSlider(Qt.Horizontal)
        self.font_size.setRange(5, 12)
        self.font_size.setSingleStep(1)
        self.font_size.setPageStep(1)
        self.font_size.valueChanged.connect(self._on_font_size_changed)
        self._font_size_value = QLabel()
        form.addRow("字体大小", self._slider_row(self.font_size, self._font_size_value))

        # 每行字数
        self.chars_per_line = QSpinBox()
        self.chars_per_line.setRange(1, 200)
        self.chars_per_line.setSuffix(" 字")
        self.chars_per_line.valueChanged.connect(self._on_chars_changed)
        form.addRow("每行文字数量", self.chars_per_line)

        # 文字描边：勾选后文字周围出现黑色描边
        self.text_outline = QCheckBox("文字描边")
        self.text_outline.toggled.connect(self._on_text_outline_changed)
        form.addRow("", self.text_outline)

        # 隐藏 Dock 栏图标：勾选后应用不在 Dock 显示图标
        self.hide_dock_icon = QCheckBox("隐藏 Dock 栏图标")
        self.hide_dock_icon.toggled.connect(self._on_hide_dock_icon_changed)
        form.addRow("", self.hide_dock_icon)

        # 鼠标未悬浮在圆点上时隐藏文本（仅手动模式显示该选项）
        self.hide_text_when_not_hovering = QCheckBox(
            "鼠标未悬浮在圆点上时隐藏文本"
        )
        self.hide_text_when_not_hovering.toggled.connect(
            self._on_hide_text_changed
        )
        self._hide_text_row_label = QLabel("")

        # 提示：可双击小圆点快速切换该选项
        self._hide_text_hint = QLabel("--双击小圆点可快速切换")
        self._hide_text_hint.setWordWrap(True)
        self._hide_text_hint.setStyleSheet("color: #8a94a6; font-size: 12px;")

        # 把勾选框与提示放进同一列的竖向容器：提示贴近勾选框并稍向右缩进
        hide_text_box = QVBoxLayout()
        hide_text_box.setContentsMargins(0, 0, 0, 0)
        hide_text_box.setSpacing(2)
        hide_text_box.addWidget(self.hide_text_when_not_hovering)
        self._hide_text_hint.setContentsMargins(20, 0, 0, 0)
        hide_text_box.addWidget(self._hide_text_hint)
        form.addRow(self._hide_text_row_label, hide_text_box)

        layout.addLayout(form)

        # 手动模式提示
        self.manual_hint = QLabel(
            "手动模式：屏幕上会出现圆形迷你窗，鼠标悬停其上时\n按键盘 ↑ / ↓ 键上下翻行。"
        )
        self.manual_hint.setWordWrap(True)
        self.manual_hint.setStyleSheet("color: #8a94a6; font-size: 12px;")
        layout.addWidget(self.manual_hint)

        # 进度显示
        self.progress_label = QLabel("")
        self.progress_label.setObjectName("progress")
        layout.addWidget(self.progress_label)

        # 导入按钮
        self.import_btn = QPushButton("导入文档…")
        self.import_btn.clicked.connect(self.import_requested.emit)
        layout.addWidget(self.import_btn)

    def _slider_row(self, slider: QSlider, value_label: QLabel) -> QWidget:
        """把滑块和数值标签横向组合成一行控件。"""
        value_label.setMinimumWidth(46)
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        h.addWidget(slider, 1)
        h.addWidget(value_label)
        return row

    # ---------- 加载 / 收集 ----------
    def _load_from_config(self):
        c = self.config
        idx = {"double": 1, "triple": 2}.get(c.display_mode, 0)
        self.display_mode.setCurrentIndex(idx)
        self.advance_mode.setCurrentIndex(1 if c.advance_mode == "manual" else 0)
        self.step.setCurrentIndex(1 if c.step >= 2 else 0)
        self.page_animation.setCurrentIndex(1 if c.page_animation == "smooth" else 0)
        # 间隔滑块以半秒为单位；字号滑块以 2px 为单位
        self.interval.setValue(round(c.auto_interval_ms / 500))
        self.font_size.setValue(round(c.font_size / 2))
        self.chars_per_line.setValue(c.chars_per_line)
        self.line_spacing.setValue(c.line_spacing)
        self.text_outline.setChecked(c.text_outline)
        self.hide_dock_icon.setChecked(c.hide_dock_icon)
        self.hide_text_when_not_hovering.setChecked(c.hide_text_when_not_hovering)
        self._refresh_slider_values()
        self._update_interval_enabled()
        self._update_step_enabled()

    def _refresh_slider_values(self):
        """刷新三个滑块右侧的数值文本。"""
        self._line_spacing_value.setText(f"{self.line_spacing.value()} px")
        self._interval_value.setText(f"{self.interval.value() / 2:g} 秒")
        self._font_size_value.setText(f"{self.font_size.value() * 2} px")

    def _update_interval_enabled(self):
        auto = self.advance_mode.currentIndex() == 0
        # 自动跳行间隔仅自动模式显示，手动模式整行隐藏
        self._interval_label.setVisible(auto)
        self._interval_row.setVisible(auto)
        self.manual_hint.setVisible(not auto)
        # “鼠标未悬浮时隐藏文本”仅在手动模式下可见
        self.hide_text_when_not_hovering.setVisible(not auto)
        self._hide_text_row_label.setVisible(not auto)
        self._hide_text_hint.setVisible(not auto)

    def _update_step_enabled(self):
        """跳行步进与行间距仅多行模式（双行/三行）可用；单行时禁用（步进强制回到一行）。"""
        mode_idx = self.display_mode.currentIndex()
        multi = mode_idx in (1, 2)
        # 多行步进的第二项文案随模式变化：双行=每次两行，三行=每次三行
        self.step.setItemText(1, "每次三行" if mode_idx == 2 else "每次两行")
        self.step.setEnabled(multi)
        self._step_label.setEnabled(multi)
        self.line_spacing.setEnabled(multi)
        self._line_spacing_label.setEnabled(multi)
        if not multi and self.step.currentIndex() != 0:
            self.step.setCurrentIndex(0)  # 单行强制每次一行

    # ---------- 变更处理 ----------
    def _on_change(self):
        """普通设置项变更：写回配置，实时应用（无需重切行/换模式）。"""
        if self._loading:
            return
        mode_idx = self.display_mode.currentIndex()
        self.config.display_mode = {1: "double", 2: "triple"}.get(mode_idx, "single")
        self._update_step_enabled()
        # 步进第二项在双行=2、三行=3；单行恒为 1
        if self.step.currentIndex() == 1:
            self.config.step = 3 if mode_idx == 2 else 2
        else:
            self.config.step = 1
        self.settings_changed.emit(False, False)

    def _on_advance_mode_changed(self):
        if self._loading:
            return
        self.config.advance_mode = (
            "manual" if self.advance_mode.currentIndex() == 1 else "auto"
        )
        self._update_interval_enabled()
        self.settings_changed.emit(False, True)  # 需要重新应用模式

    def _on_interval_changed(self):
        if self._loading:
            return
        # 滑块以半秒为单位 → 毫秒
        self.config.auto_interval_ms = int(self.interval.value() * 500)
        self._interval_value.setText(f"{self.interval.value() / 2:g} 秒")
        self.settings_changed.emit(False, True)  # 重启定时器

    def _on_font_size_changed(self):
        if self._loading:
            return
        # 滑块以 2px 为单位 → px
        self.config.font_size = self.font_size.value() * 2
        self._font_size_value.setText(f"{self.config.font_size} px")
        self.settings_changed.emit(False, False)

    def _on_chars_changed(self):
        if self._loading:
            return
        self.config.chars_per_line = self.chars_per_line.value()
        self.settings_changed.emit(True, False)  # 需要重新切分行

    def _on_line_spacing_changed(self):
        if self._loading:
            return
        self.config.line_spacing = self.line_spacing.value()
        self._line_spacing_value.setText(f"{self.line_spacing.value()} px")
        self.settings_changed.emit(False, False)  # 实时应用，无需重切行

    def _on_text_outline_changed(self):
        if self._loading:
            return
        self.config.text_outline = self.text_outline.isChecked()
        self.settings_changed.emit(False, False)  # 实时应用，无需重切行

    def _on_hide_dock_icon_changed(self):
        if self._loading:
            return
        self.config.hide_dock_icon = self.hide_dock_icon.isChecked()
        self.dock_icon_toggled.emit(self.config.hide_dock_icon)

    def _on_hide_text_changed(self):
        if self._loading:
            return
        checked = self.hide_text_when_not_hovering.isChecked()
        self.config.hide_text_when_not_hovering = checked
        # 由浮窗应用显隐并播放与双击一致的边框缩放特效
        self.hide_text_toggled.emit(checked)

    def _on_page_animation_changed(self):
        if self._loading:
            return
        self.config.page_animation = (
            "smooth" if self.page_animation.currentIndex() == 1 else "none"
        )
        self.settings_changed.emit(False, False)  # 实时应用，无需重切行

    # ---------- 进度 ----------
    def update_progress(self, index: int, total: int):
        self.progress_label.setText(f"当前进度：第 {index + 1} / {total} 行")

    def sync_hide_text_checkbox(self, checked: bool):
        """外部（如双击圆点）切换配置后，同步勾选框而不回发信号。"""
        if self.hide_text_when_not_hovering.isChecked() == checked:
            return
        was_loading = self._loading
        self._loading = True  # 抑制 toggled 回调，避免重复写配置
        self.hide_text_when_not_hovering.setChecked(checked)
        self._loading = was_loading


class SyncConfirmDialog(QDialog):
    """源文件更新确认弹窗，样式与设置页保持一致。

    用于检测到原文件变动时询问用户是否同步到最新内容。
    """

    def __init__(self, title: str, summary: str, preview: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedWidth(320)
        self.setStyleSheet(STYLE)
        self._build_ui(title, summary, preview)

    def _build_ui(self, title: str, summary: str, preview: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        heading = QLabel(title)
        heading.setStyleSheet("color: #e6e9ee; font-size: 15px; font-weight: bold;")
        layout.addWidget(heading)

        summary_label = QLabel(summary)
        summary_label.setWordWrap(True)
        layout.addWidget(summary_label)

        if preview:
            preview_label = QLabel(preview)
            preview_label.setObjectName("progress")
            preview_label.setWordWrap(True)
            layout.addWidget(preview_label)

        tip = QLabel("当前阅读进度会尽量保留。")
        tip.setStyleSheet("color: #8a94a6; font-size: 12px;")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch(1)
        self.no_btn = QPushButton("暂不更新")
        self.no_btn.setStyleSheet(
            "QPushButton { background: #2d3138; color: #cfd3da;"
            " border: 1px solid #3d434d; }"
            " QPushButton:hover { background: #353a42; }"
            " QPushButton:pressed { background: #262a30; }"
        )
        self.no_btn.clicked.connect(self.reject)
        self.yes_btn = QPushButton("更新")
        self.yes_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.no_btn)
        btn_row.addWidget(self.yes_btn)
        layout.addLayout(btn_row)
