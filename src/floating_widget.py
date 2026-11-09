"""主悬浮文本窗口。

逐行悬浮显示导入的文档内容（类似歌词）：
- 单行 / 双行显示
- 自动跳行（定时）或手动跳行（配合迷你导航窗用上/下键）
- 右键菜单打开设置、导入文档、前后翻行
- macOS 下提升到状态栏级并跨全屏应用显示
"""

from __future__ import annotations

import os
import sys

try:
    import objc
except ImportError:
    objc = None

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QRect,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QInputDialog,
    QMenu,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from . import document
from .config import LibraryEntry, cache_document, load_config, save_config
from .library_widget import LibraryPopup, MenuButton
from .mini_widget import MiniWidget
from .outlined_label import OutlinedLabel


MENU_STYLE = """
QMenu {
    background: #2b2b2b;
    border: 1px solid #3d3d3d;
    border-radius: 10px;
    padding: 6px;
}
QMenu::item {
    background: transparent;
    color: #e6e6e6;
    font-size: 13px;
    padding: 7px 22px;
    border-radius: 8px;
}
QMenu::item:selected {
    background: #3d5a80;
    color: #ffffff;
}
QMenu::item:checked {
    color: #7ec8ff;
}
QMenu::separator {
    height: 1px;
    background: #3d3d3d;
    margin: 5px 8px;
}
"""

DEFAULT_HINT = "右键此处打开设置 · 导入 txt / docx / md 文档开始阅读"


class BorderFlashOverlay(QWidget):
    """双击切换“未悬浮隐藏文本”时的边框特效浮层。

    独立的透明置顶、鼠标穿透小窗，仅绘制一圈圆角边框，
    通过几何缩放 + 窗口透明度动画营造“收拢聚焦 / 扩散消散”的效果。
    """

    BORDER_COLOR = QColor("#5a86c2")
    PEN_WIDTH = 3
    RADIUS = 14
    # fit 外再留出的内边距，保证边框落在文本窗之外一点
    FIT_MARGIN = 6
    # “放大”状态相对 fit 每边外扩的像素
    EXPAND = 90

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.Tool
            | Qt.WindowStaysOnTopHint
            | Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._group: QParallelAnimationGroup | None = None
        self._color = QColor(self.BORDER_COLOR)

    def set_border_color(self, color: QColor):
        """设置边框颜色（透明度由窗口动画控制，这里用不透明色）。"""
        self._color = QColor(color.red(), color.green(), color.blue())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(self._color, self.PEN_WIDTH)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        half = self.PEN_WIDTH / 2
        rect = self.rect().adjusted(half, half, -half, -half)
        painter.drawRoundedRect(rect, self.RADIUS, self.RADIUS)

    def _fit_rect(self, anchor: QRect) -> QRect:
        m = self.FIT_MARGIN + self.PEN_WIDTH
        return anchor.adjusted(-m, -m, m, m)

    def _expanded_rect(self, fit: QRect) -> QRect:
        e = self.EXPAND
        return fit.adjusted(-e, -e, e, e)

    def flash(self, anchor: QRect, focusing: bool, duration: int = 500):
        """播放一次边框动画。

        anchor：文本窗的全局几何矩形。
        focusing=True：收拢聚焦（大→刚好框住，透明→不透明）。
        focusing=False：扩散消散（刚好框住→变大，不透明→透明）。
        """
        if self._group is not None:
            self._group.stop()

        fit = self._fit_rect(anchor)
        big = self._expanded_rect(fit)

        if focusing:
            # 收拢聚焦：大→刚好框住（透明→不透明），到位后再渐渐淡出消失
            fade_tail = 300
            total = duration + fade_tail
            shrink_ratio = duration / total

            self.setGeometry(big)
            self.setWindowOpacity(0.0)
            self.show()
            self.raise_()

            geo_anim = QPropertyAnimation(self, b"geometry", self)
            geo_anim.setDuration(total)
            geo_anim.setStartValue(big)
            # 收拢阶段结束后保持在 fit 不动
            geo_anim.setKeyValueAt(shrink_ratio, fit)
            geo_anim.setEndValue(fit)
            geo_anim.setEasingCurve(QEasingCurve.OutCubic)

            op_anim = QPropertyAnimation(self, b"windowOpacity", self)
            op_anim.setDuration(total)
            op_anim.setStartValue(0.0)
            op_anim.setKeyValueAt(shrink_ratio, 1.0)  # 收拢到位时完全不透明
            op_anim.setEndValue(0.0)  # 之后渐渐淡出
            op_anim.setEasingCurve(QEasingCurve.InOutQuad)
        else:
            # 扩散消散：刚好框住→变大，不透明→透明
            self.setGeometry(fit)
            self.setWindowOpacity(1.0)
            self.show()
            self.raise_()

            geo_anim = QPropertyAnimation(self, b"geometry", self)
            geo_anim.setDuration(duration)
            geo_anim.setStartValue(fit)
            geo_anim.setEndValue(big)
            geo_anim.setEasingCurve(QEasingCurve.OutCubic)

            op_anim = QPropertyAnimation(self, b"windowOpacity", self)
            op_anim.setDuration(duration)
            op_anim.setStartValue(1.0)
            op_anim.setEndValue(0.0)
            op_anim.setEasingCurve(QEasingCurve.InOutQuad)

        group = QParallelAnimationGroup(self)
        group.addAnimation(geo_anim)
        group.addAnimation(op_anim)
        group.finished.connect(self.hide)
        group.start()
        self._group = group


class FloatingWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.config = load_config()

        # 文档状态
        self.paragraphs: list[str] = [DEFAULT_HINT]
        self.lines: list[str] = document.split_lines(
            self.paragraphs, self.config.chars_per_line
        )
        self.index = 0

        self._drag_pos = None
        self.mini: MiniWidget | None = None
        # 文本浮窗淡入淡出动画（手动模式“未悬浮隐藏”时使用）
        self._fade_anim: QPropertyAnimation | None = None
        # 双击切换时的边框特效浮层（懒加载）
        self._border_flash: BorderFlashOverlay | None = None
        # 翻页动画状态：进行中时忽略新的翻页请求，避免动画叠加错乱
        self._anim_group: QParallelAnimationGroup | None = None
        self._anim_labels: list[OutlinedLabel] = []

        # 阅读列表当前条目（None 表示尚未打开任何文档）
        self.current_entry: LibraryEntry | None = None
        # 阅读列表弹层（打开期间存在）
        self._library_popup: LibraryPopup | None = None

        self._build_ui()
        self._init_window()

        # 自动跳行定时器
        self.auto_timer = QTimer(self)
        self.auto_timer.timeout.connect(lambda: self.advance(1))

        # 左上角"…"按钮：悬停浮窗时显示，点击后隐藏并弹出阅读列表
        self.menu_btn = MenuButton(self)
        self.menu_btn.clicked.connect(self.show_library)
        # 按钮延迟隐藏：鼠标从浮窗移向按钮需跨过间隙，立即隐藏会点不到
        self._btn_hide_timer = QTimer(self)
        self._btn_hide_timer.setSingleShot(True)
        self._btn_hide_timer.setInterval(300)
        self._btn_hide_timer.timeout.connect(self._maybe_hide_menu_btn)

        # 始终从缓存副本恢复阅读；缓存缺失时回退到原文件
        restore_entry = self._restore_entry()
        if restore_entry is not None:
            self._open_entry(restore_entry, check_update=True)

        self._apply_mode()
        self._render()

    def _restore_entry(self) -> LibraryEntry | None:
        """确定启动时恢复的书目：只认阅读列表里的条目。

        旧配置（无 library）仅在未迁移时执行一次性迁移；
        此后 last_file 若不在列表中（如被用户移除），不再自动加回。
        """
        # 1) last_file 在列表中：正常恢复
        for entry in self.config.library:
            if entry.file == self.config.last_file:
                return entry

        # 2) 一次性迁移旧版本配置（library 为空且从未迁移过）
        if not self.config.library and not self.config.library_migrated:
            self.config.library_migrated = True
            if self.config.last_file:
                cache = self.config.last_cache
                if not (cache and os.path.exists(cache)):
                    cache = None
                if cache or os.path.exists(self.config.last_file):
                    entry = LibraryEntry(
                        file=self.config.last_file,
                        cache=cache,
                        index=self.config.last_index,
                    )
                    self.config.library.insert(0, entry)
                    return entry

        # 3) 列表里还有其他书：恢复最近导入的一本（last_file 指向的书已被移除）
        if self.config.library:
            entry = self.config.library[0]
            self.config.last_file = entry.file
            self.config.last_index = entry.index
            return entry

        # 4) 空列表：无书可恢复
        return None

    # ---------- 窗口 ----------
    def _init_window(self):
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        # 最小宽度保证无文档时仍可右击操作；实际大小由内容自适应
        self.setMinimumWidth(120)
        self.resize(640, 120)
        if self.config.pos_x is not None and self.config.pos_y is not None:
            self.move(self.config.pos_x, self.config.pos_y)
        else:
            screen = self.screen().availableGeometry()
            self.move(screen.center().x() - 320, screen.top() + 80)

    def showEvent(self, event):
        super().showEvent(event)
        self._set_window_level_top()
        self._apply_dock_icon_policy()

    def _set_window_level_top(self):
        """macOS：提升到状态栏级并跨所有 Space（含原生全屏应用）显示。"""
        if sys.platform != "darwin" or objc is None:
            return
        try:
            import AppKit
        except ImportError:
            return
        view = objc.objc_object(c_void_p=int(self.winId()))
        window = view.window()
        if window is None:
            return
        window.setLevel_(AppKit.NSStatusWindowLevel)
        # Qt.Tool 在 macOS 上是 NSPanel，默认失焦自动隐藏，需关闭
        window.setHidesOnDeactivate_(False)
        window.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorStationary
            | AppKit.NSWindowCollectionBehaviorIgnoresCycle
            | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
        )

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 10, 18, 10)
        layout.setSpacing(6)

        # 主行（第一行）
        self.line1 = OutlinedLabel()
        # 副行（双行模式时显示第二行）
        self.line2 = OutlinedLabel()
        # 第三行（三行模式时显示）
        self.line3 = OutlinedLabel()

        # 上下弹性空间让文字整体垂直居中，避免固定窗高把两行撑开，
        # 使两行间距只由 layout spacing（行间距设置）决定。
        layout.addStretch(1)
        layout.addWidget(self.line1)
        layout.addWidget(self.line2)
        layout.addWidget(self.line3)
        layout.addStretch(1)

        self.setStyleSheet(
            """
            FloatingWidget {
                background: rgba(20, 20, 20, 160);
                border-radius: 14px;
            }
            """
        )
        self._apply_text_style()

    def _apply_text_style(self):
        size = max(8, int(self.config.font_size))
        font = QFont()
        # 指定中文优先字体族，兼顾 macOS / Windows
        font.setFamilies(
            ["-apple-system", "PingFang SC", "Microsoft YaHei", "sans-serif"]
        )
        font.setPixelSize(size)
        font.setWeight(QFont.DemiBold)
        # 多行显示时各行颜色保持一致（统一用调暗色）；
        # 开启描边时文字本体用不透明白色，避免半透明叠在黑底上显脏。
        outline = bool(self.config.text_outline)
        if outline:
            color = QColor(255, 255, 255)
        else:
            color = QColor(255, 255, 255, int(0.7 * 255))
        # 偏移式描边宽度取小值（1~2px），中文笔画清晰不糊
        outline_width = 1.0 if size <= 22 else 2.0
        for label in (self.line1, self.line2, self.line3):
            label.configure(font, color, outline, outline_width)

    # ---------- 渲染 ----------
    def _render(self):
        # 若动画仍在进行中（如动画期间改了设置），先终止动画再重绘。
        # 先断开信号再 stop，避免 stop 触发的 finished 递归调回 _render。
        if self._anim_group is not None:
            group = self._anim_group
            self._anim_group = None
            try:
                group.finished.disconnect(self._on_anim_finished)
            except (RuntimeError, TypeError):
                pass
            group.stop()
            for lbl in self._anim_labels:
                lbl.deleteLater()
            self._anim_labels = []
        n = len(self.lines)
        first = self.lines[self.index] if 0 <= self.index < n else ""
        self.line1.setText(first or "\u00A0")
        self.line1.show()  # 平滑动画期间会被隐藏，渲染时确保恢复

        mode = self.config.display_mode
        if mode in ("double", "triple"):
            second = self.lines[self.index + 1] if self.index + 1 < n else ""
            self.line2.setText(second or "\u00A0")
            self.line2.show()
            # 多行模式应用可调行间距
            self.layout().setSpacing(max(0, int(self.config.line_spacing)))
        else:
            self.line2.hide()

        if mode == "triple":
            third = self.lines[self.index + 2] if self.index + 2 < n else ""
            self.line3.setText(third or "\u00A0")
            self.line3.show()
        else:
            self.line3.hide()

        # 让窗口收缩到贴合文字内容（含内边距），避免固定大窗口留大片空白。
        # 直接按 layout 的 sizeHint 显式 resize（adjustSize 在 macOS frameless
        # 窗口上会被最小高度约束挡住，无法真正收缩）。
        self.layout().activate()
        hint = self.layout().sizeHint()
        self.resize(max(self.minimumWidth(), hint.width()), hint.height())

        # 同步设置窗进度显示（如已打开）
        dlg = getattr(self, "_settings_dialog", None)
        if dlg is not None:
            dlg.update_progress(self.index, n)

    # ---------- 跳行 ----------
    def advance(self, direction: int):
        """按 step 前进/后退。direction: 1 前进，-1 后退。"""
        if not self.lines:
            return
        # 动画进行中忽略新请求，防止连按导致动画叠加错乱
        if self._anim_group is not None:
            return
        # 步进行数按模式约束：单行恒为 1；双行可 1/2；三行可 1/3
        mode = self.config.display_mode
        if mode == "double" and self.config.step == 2:
            step = 2
        elif mode == "triple" and self.config.step == 3:
            step = 3
        else:
            step = 1
        delta = step * direction
        old_index = self.index
        new_index = max(0, min(self.index + delta, len(self.lines) - 1))
        if new_index == old_index:
            return  # 已到顶/底，不动

        self.index = new_index
        if self.current_entry is not None:
            self.current_entry.index = self.index
        self.config.last_index = self.index  # 记录进度（退出时统一写盘）

        if self.config.page_animation == "smooth":
            self._render_animated(direction, step)
        else:
            self._render()

    # ---------- 平滑翻页动画 ----------
    def _line_texts(self, index: int) -> list[str]:
        """按当前显示模式取 index 起始的可见行文本（不足补不换行空格）。"""
        n = len(self.lines)
        mode = self.config.display_mode
        count = {"double": 2, "triple": 3}.get(mode, 1)
        texts = []
        for i in range(count):
            t = self.lines[index + i] if 0 <= index + i < n else ""
            texts.append(t or " ")
        return texts

    def _render_animated(self, direction: int, step: int):
        """平滑翻页：把相关行拼成一条连续文字带整体平移，模拟滚动。

        关键点：多行模式下相邻两屏存在共享行（如三行 A/B/C → B/C/D 中的
        B、C），若分别对「旧屏」「新屏」各画一份会重叠成重影/闪烁。因此这里
        构造一条覆盖 [start, end] 全部行的竖直文字带（每行一个临时 label，
        位置连续、不重复），初始对齐旧屏，动画结束时对齐新屏；超出窗口的行
        由父窗口裁剪，形成滚动露出的效果。
        direction: 1 向下翻（文字带向上滚），-1 向上翻（向下滚）。
        step: 滚动的行距数。
        """
        real_labels = [self.line1, self.line2, self.line3]
        vc = {"double": 2, "triple": 3}.get(self.config.display_mode, 1)

        # 先确保真实行的几何已按当前内容布局好，用作锚点与行距来源
        self.layout().activate()
        y0 = self.line1.geometry().top()   # 第一行顶部（self 坐标）
        x0 = self.line1.geometry().left()
        line_h = self.line1.geometry().height() or self.line1.sizeHint().height()
        if vc >= 2:
            unit = self.line2.geometry().top() - self.line1.geometry().top()
        else:
            unit = line_h + max(0, self.layout().spacing())
        if unit <= 0:
            unit = line_h

        old_index = self.index - step * direction
        new_index = self.index

        # 文字带覆盖的行区间 [start, end]（含端点）
        start = min(old_index, new_index)
        end = max(old_index, new_index) + vc - 1

        font = self.line1._font
        color = self.line1._color
        outline = self.line1._outline
        outline_width = self.line1._outline_width

        # 承载文字带的容器（子控件会被 self 裁剪，实现滚动露出）
        strip = QWidget(self)
        strip.setAttribute(Qt.WA_TranslucentBackground)
        n = len(self.lines)
        max_w = 1
        line_widths: dict[int, int] = {}
        for k in range(start, end + 1):
            text = self.lines[k] if 0 <= k < n else ""
            lbl = OutlinedLabel(strip)
            lbl.configure(font, color, outline, outline_width)
            lbl.setText(text or "\u00A0")
            w = lbl.sizeHint().width()
            line_widths[k] = w
            max_w = max(max_w, w)
            lbl.setGeometry(0, (k - start) * unit, w, line_h)
            lbl.show()
        strip.resize(max_w, (end - start) * unit + line_h)

        # 旧屏 / 新屏对应的文字带顶部位置（使对应行落在 y0）
        strip_top_old = y0 - (old_index - start) * unit
        strip_top_new = y0 - (new_index - start) * unit
        strip.move(x0, strip_top_old)
        strip.show()

        # 动画期间隐藏真实行，仅显示滚动带
        for i in range(vc):
            real_labels[i].hide()

        group = QParallelAnimationGroup(self)
        pos_anim = QPropertyAnimation(strip, b"pos", group)
        pos_anim.setDuration(220)
        pos_anim.setStartValue(QPoint(x0, strip_top_old))
        pos_anim.setEndValue(QPoint(x0, strip_top_new))
        pos_anim.setEasingCurve(QEasingCurve.OutCubic)
        group.addAnimation(pos_anim)

        # 同步平滑改变窗口宽度，避免动画结束后新行比旧行长时「突然变宽」。
        # 目标宽度按旧屏/新屏各自可见行的最大宽度加内边距计算。
        margins = self.layout().contentsMargins()
        pad_w = margins.left() + margins.right()

        def screen_width(idx: int) -> int:
            widths = [line_widths.get(idx + i, 0) for i in range(vc)]
            content = max(widths) if widths else 0
            return max(self.minimumWidth(), content + pad_w)

        w_old = screen_width(old_index)
        w_new = screen_width(new_index)
        if w_old != w_new:
            cur = self.geometry()
            size_anim = QPropertyAnimation(self, b"geometry", group)
            size_anim.setDuration(220)
            size_anim.setStartValue(QRect(cur.x(), cur.y(), w_old, cur.height()))
            size_anim.setEndValue(QRect(cur.x(), cur.y(), w_new, cur.height()))
            size_anim.setEasingCurve(QEasingCurve.OutCubic)
            group.addAnimation(size_anim)

        self._anim_labels = [strip]  # 结束时统一 deleteLater
        self._anim_group = group
        group.finished.connect(self._on_anim_finished)
        group.start()

        # 同步设置窗进度（动画期间即可更新）
        dlg = getattr(self, "_settings_dialog", None)
        if dlg is not None:
            dlg.update_progress(self.index, len(self.lines))

    def _on_anim_finished(self):
        """动画结束：清理临时标签，恢复正常渲染。"""
        for lbl in self._anim_labels:
            lbl.deleteLater()
        self._anim_labels = []
        self._anim_group = None
        self._render()

    # ---------- 模式应用 ----------
    def _apply_mode(self):
        """按当前配置启停自动定时器 / 显隐迷你导航窗。"""
        self._apply_text_style()
        if self.config.advance_mode == "auto":
            self._destroy_mini()
            interval = max(300, int(self.config.auto_interval_ms))
            self.auto_timer.start(interval)
            # 退出手动模式：确保文本恢复完全可见
            self.setWindowOpacity(1.0)
        else:
            self.auto_timer.stop()
            self._create_mini()
            # 手动模式：根据“未悬浮隐藏文本”设置应用初始透明度
            if self.config.hide_text_when_not_hovering:
                hovering = self.mini is not None and self.mini.is_hovering()
                self.setWindowOpacity(1.0 if hovering else 0.0)
            else:
                self.setWindowOpacity(1.0)

    def _create_mini(self):
        if self.mini is not None:
            return
        self.mini = MiniWidget(self.config)
        self.mini.nav_up.connect(lambda: self.advance(-1))
        self.mini.nav_down.connect(lambda: self.advance(1))
        self.mini.quit_requested.connect(self._quit)
        self.mini.hover_changed.connect(self._on_mini_hover_changed)
        self.mini.toggle_hide_text_requested.connect(self._toggle_hide_text)
        self.mini.show()

    def _destroy_mini(self):
        if self.mini is not None:
            self.mini.close()
            self.mini = None

    def _on_mini_hover_changed(self, hovering: bool):
        """手动模式下，鼠标进出圆点时淡入/淡出文本浮窗。"""
        if self.config.advance_mode != "manual":
            return
        if not self.config.hide_text_when_not_hovering:
            return
        self._update_text_visibility()

    def _update_text_visibility(self):
        """按“未悬浮隐藏”规则刷新文本窗显隐：
        鼠标悬浮在小圆点上或文本窗上时显示，否则隐藏。"""
        if self.config.advance_mode != "manual":
            return
        if not self.config.hide_text_when_not_hovering:
            return
        on_mini = self.mini is not None and self.mini.is_hovering()
        show = on_mini or self.underMouse()
        self._fade_text(1.0 if show else 0.0)

    def _toggle_hide_text(self):
        """双击圆点：切换“未悬浮隐藏文本”配置并同步设置窗与显隐状态。"""
        enabled = not self.config.hide_text_when_not_hovering
        self.config.hide_text_when_not_hovering = enabled
        save_config(self.config)
        # 同步设置窗中的勾选框（打开时）
        dialog = getattr(self, "_settings_dialog", None)
        if dialog is not None:
            dialog.sync_hide_text_checkbox(enabled)
        self._apply_hide_text_state(enabled)

    def _on_hide_text_toggled(self, enabled: bool):
        """设置窗勾选/取消“未悬浮隐藏文本”时：应用显隐并播放同款边框特效。"""
        self.config.hide_text_when_not_hovering = enabled
        save_config(self.config)
        self._apply_hide_text_state(enabled)

    def _apply_hide_text_state(self, enabled: bool):
        """应用“未悬浮隐藏文本”状态：刷新显隐并播放边框缩放特效。"""
        # 立即应用显隐：开启则按当前悬停状态淡入/淡出，关闭则恢复可见
        if enabled:
            hovering = self.mini is not None and self.mini.is_hovering()
            self._fade_text(1.0 if hovering else 0.0)
        else:
            self._fade_text(1.0)
        # 边框特效：始终显示(关闭隐藏)=收拢聚焦；未悬浮隐藏(开启)=扩散消散
        self._play_border_flash(focusing=not enabled)

    def _play_border_flash(self, focusing: bool):
        """在文本窗四周播放一次边框特效（0.5s）。"""
        if self._border_flash is None:
            self._border_flash = BorderFlashOverlay()
        # 边框颜色与文本浮窗文字颜色保持一致（当前文字恒为白色）
        self._border_flash.set_border_color(QColor(255, 255, 255))
        self._border_flash.flash(self.frameGeometry(), focusing, duration=500)

    def _fade_text(self, target: float):
        """把文本浮窗透明度平滑过渡到 target（0=隐藏，1=显示）。"""
        if self._fade_anim is not None:
            self._fade_anim.stop()
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(260)
        anim.setStartValue(self.windowOpacity())
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.InOutQuad)
        anim.start()
        self._fade_anim = anim

    # ---------- 文档 ----------
    def _load_file(self, path: str, remember: bool = True, start_index: int = 0):
        """解析文档并渲染。返回是否成功。

        remember=True 时为新导入：写缓存、入阅读列表并保存进度。
        """
        if remember:
            # 先保存当前书的进度（此时 self.index 还是旧书的进度）
            self._save_current_progress()
        try:
            paragraphs = document.parse_document(path)
        except Exception as exc:  # 解析失败弹窗提示，不崩溃
            QMessageBox.critical(self, "导入失败", f"无法解析文档：\n{exc}")
            return False
        self.paragraphs = paragraphs
        self.lines = document.split_lines(self.paragraphs, self.config.chars_per_line)
        # 起始行号夹在有效范围内（恢复进度时可能因每行字数变化而越界）
        self.index = max(0, min(start_index, len(self.lines) - 1))

        if remember:
            self._register_entry(path)

        self._render()
        return True

    def _rebuild_lines(self):
        """每行字数变更后重新切分，尽量保持当前阅读位置。"""
        self.lines = document.split_lines(self.paragraphs, self.config.chars_per_line)
        self.index = max(0, min(self.index, len(self.lines) - 1))
        self._render()

    def _register_entry(self, path: str):
        """把导入的文件登记进阅读列表（已存在则复用其进度），并设为当前书。"""
        abspath = os.path.abspath(path)
        # 已在列表中：直接切换（保留原进度）
        for entry in self.config.library:
            if entry.file == abspath:
                self.current_entry = entry
                self.config.last_file = abspath
                self.config.last_index = entry.index
                save_config(self.config)
                return
        # 新书：写缓存副本，加入列表
        try:
            cache = cache_document(path)
        except OSError:
            cache = None  # 缓存失败不影响本次阅读，仅无法在原文件缺失时恢复
        import time

        entry = LibraryEntry(
            file=abspath, cache=cache, index=self.index, added_at=time.time()
        )
        self.config.library.insert(0, entry)
        self.current_entry = entry
        self.config.last_file = abspath
        self.config.last_index = self.index
        save_config(self.config)

    def _save_current_progress(self):
        """把当前书进度写入列表条目与全局字段。"""
        if self.current_entry is not None:
            self.current_entry.index = self.index
        self.config.last_index = self.index
        save_config(self.config)

    def _open_entry(self, entry: LibraryEntry, check_update: bool = False):
        """打开阅读列表条目：优先读缓存副本，回退原文件；可选做更新检测。"""
        read_path = None
        if entry.cache and os.path.exists(entry.cache):
            read_path = entry.cache
        elif os.path.exists(entry.file):
            read_path = entry.file
        if read_path is None:
            QMessageBox.warning(
                self,
                "无法打开",
                f"找不到该文档及其缓存副本：\n{entry.file}",
            )
            return
        self.current_entry = entry
        self.config.last_file = entry.file
        self.config.last_index = entry.index
        ok = self._load_file(read_path, remember=False, start_index=entry.index)
        if ok and check_update:
            # 恢复后再检测原文件是否有更新，有则询问用户是否同步
            self._maybe_sync_source()

    # ---------- 阅读列表 ----------
    def show_library(self):
        """点击"…"：隐藏按钮并弹出阅读列表（紧贴浮窗左侧、顶部平齐）。"""
        if self._library_popup is not None:
            self._library_popup.close()
            return
        if not self.config.library:
            return
        # 列表文字样式与浮窗一致（同字体/颜色/描边），字号略小
        font = QFont(self.line1._font)  # 拷贝，避免改动浮窗自身字体
        font.setPixelSize(max(10, int(self.config.font_size) - 4))
        color = self.line1._color
        outline = self.line1._outline
        outline_width = self.line1._outline_width
        popup = LibraryPopup(
            self.config.library,
            font,
            color,
            outline,
            outline_width,
            current_file=self.current_entry.file if self.current_entry else None,
            anchor=self,
        )
        popup.file_selected.connect(self._switch_to_file)
        popup.remove_requested.connect(self._remove_entry)
        popup.popup_closed.connect(lambda: self._on_library_closed(popup))
        self.menu_btn.hide()  # "…"本身消失，由列表顶上
        popup.show()
        self._library_popup = popup

    def _on_library_closed(self, popup):
        """弹层关闭后清理引用，并按需恢复"…"按钮。"""
        if self._library_popup is popup:
            self._library_popup = None
            if self.underMouse():
                # 鼠标确实在浮窗内：延迟片刻再恢复按钮，
                # 避免关闭瞬间与列表压住的区域交叠导致误呼出
                self._btn_hide_timer.stop()
                self.menu_btn.show()
                self.menu_btn.position()

    def _switch_to_file(self, file: str):
        """从阅读列表切换到目标文件，切换前保存进度，切换后做更新检测。"""
        for entry in self.config.library:
            if entry.file == file:
                if self.current_entry is entry:
                    return
                self._save_current_progress()
                self._open_entry(entry, check_update=True)
                return

    def _remove_entry(self, file: str):
        """从阅读列表移除书目（列表内对勾二次确认已通过）：删缓存副本，当前书被删则切换。"""
        entry = next(
            (e for e in self.config.library if e.file == file), None
        )
        if entry is None:
            return

        self.config.library.remove(entry)
        # 删除缓存副本（仅删除本项目缓存目录内的文件，防误删）
        from .config import CACHE_DIR

        if entry.cache and entry.cache.startswith(CACHE_DIR) and os.path.exists(entry.cache):
            try:
                os.remove(entry.cache)
            except OSError:
                pass

        removing_current = self.current_entry is entry
        if removing_current:
            self.current_entry = None
            # 切到列表中最近导入的剩余书目；列表空则清空显示
            if self.config.library:
                self._open_entry(self.config.library[0])
            else:
                self._clear_document()
        elif self.config.last_file == file:
            # 删的不是当前书，但全局指针指向它：修正到当前书
            if self.current_entry is not None:
                self.config.last_file = self.current_entry.file
                self.config.last_index = self.current_entry.index
        save_config(self.config)
        # 重开列表以刷新条目（若列表仍开着）
        if self._library_popup is not None and self._library_popup.isVisible():
            self._library_popup.close()

    def _clear_document(self):
        """清空当前文档显示（阅读列表为空时）。"""
        self.paragraphs = [DEFAULT_HINT]
        self.lines = document.split_lines(self.paragraphs, self.config.chars_per_line)
        self.index = 0
        self.config.last_file = None
        self.config.last_cache = None
        self.config.last_index = 0
        self._render()

    def _maybe_sync_source(self):
        """启动恢复/切换书目后检测原文件是否有更新，有则询问用户是否同步到副本。

        调用前 self.paragraphs 应为缓存副本的内容。
        """
        if self.current_entry is None:
            return
        entry = self.current_entry
        src = entry.file
        if not os.path.exists(src):
            return  # 原文件已删除或移动，继续使用副本
        if not entry.cache:
            # 当前读的就是原文件（无副本），补建一份副本即可，无需对比
            try:
                entry.cache = cache_document(src)
                save_config(self.config)
            except OSError:
                pass
            return
        try:
            new_paragraphs = document.parse_document(src)
        except Exception:
            return  # 原文件无法解析，忽略本次同步
        diff = document.diff_documents(self.paragraphs, new_paragraphs)
        if not diff["changed"]:
            return

        from .settings_dialog import SyncConfirmDialog

        preview = "\n".join(self._format_preview_line(p) for p in diff["preview"])
        summary = f"检测到原文件有更新：+{diff['added']} 行，-{diff['removed']} 行。"
        dialog = SyncConfirmDialog("原文件已更新", summary, preview, self)
        # 与设置窗一致：提升层级，默认弹在文本浮窗下方（下方空间不足则上方）
        dialog.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        dialog.show()
        self._position_below_anchor(dialog)
        self._raise_settings_window(dialog)
        if dialog.exec() != SyncConfirmDialog.Accepted:
            return

        # 用户同意同步：刷新副本与内存内容，尽量保留当前阅读位置
        self.paragraphs = new_paragraphs
        try:
            entry.cache = cache_document(src)
        except OSError:
            pass
        self.lines = document.split_lines(self.paragraphs, self.config.chars_per_line)
        self.index = max(0, min(self.index, len(self.lines) - 1))
        entry.index = self.index
        self.config.last_index = self.index
        save_config(self.config)
        self._render()

    @staticmethod
    def _format_preview_line(line: str, max_len: int = 40) -> str:
        """把 diff 预览行（+/- 前缀）截断到合适长度，避免弹窗过宽。"""
        sign, text = line[:1], line[1:]
        text = text.strip()
        if len(text) > max_len:
            text = text[:max_len] + "…"
        return f"{sign} {text}" if text else sign

    def import_document(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入文档", "", "文档 (*.txt *.md *.docx)"
        )
        if path:
            self._load_file(path)

    # ---------- 右键菜单 ----------
    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet(MENU_STYLE)

        act_settings = QAction("打开设置…", self)
        act_settings.triggered.connect(self.open_settings)
        menu.addAction(act_settings)
        menu.addSeparator()

        act_import = QAction("导入文档…", self)
        act_import.triggered.connect(self.import_document)
        menu.addAction(act_import)
        menu.addSeparator()

        act_goto = QAction("快速跳转…", self)
        act_goto.triggered.connect(self.goto_line)
        menu.addAction(act_goto)
        menu.addSeparator()

        act_quit = QAction("退出", self)
        act_quit.triggered.connect(self._quit)
        menu.addAction(act_quit)

        menu.exec(event.globalPos())

    def goto_line(self):
        """弹出输入框，跳转到指定行号（1 ~ 最大行数）。"""
        if not self.lines:
            return
        if self._anim_group is not None:
            return
        total = len(self.lines)

        dialog = QInputDialog(self)
        dialog.setInputMode(QInputDialog.IntInput)
        dialog.setWindowTitle("快速跳转")
        dialog.setLabelText(f"请输入行号（1 ~ {total}）：")
        dialog.setIntRange(1, total)
        dialog.setIntStep(1)
        dialog.setIntValue(self.index + 1)
        # 与设置窗一致：弹在文本浮窗右侧并提升层级，避免与浮窗重合点不到
        dialog.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        dialog.show()
        self._position_settings_window(dialog)
        self._raise_settings_window(dialog)

        if dialog.exec() != QInputDialog.Accepted:
            return
        new_index = dialog.intValue() - 1
        if new_index == self.index:
            return
        self.index = new_index
        if self.current_entry is not None:
            self.current_entry.index = self.index
        self.config.last_index = self.index
        self._render()

    def open_settings(self):
        from .settings_dialog import SettingsDialog

        dialog = SettingsDialog(self.config, self)
        self._settings_dialog = dialog
        # 设置项实时应用
        dialog.settings_changed.connect(self._on_settings_changed)
        dialog.import_requested.connect(self.import_document)
        dialog.dock_icon_toggled.connect(self._on_dock_icon_toggled)
        dialog.hide_text_toggled.connect(self._on_hide_text_toggled)
        dialog.update_progress(self.index, len(self.lines))
        # 让设置窗浮在置顶悬浮窗之上，同时保留悬浮窗可见以便实时预览
        dialog.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        dialog.show()
        self._position_settings_window(dialog)
        self._raise_settings_window(dialog)
        try:
            dialog.exec()
        finally:
            self._settings_dialog = None

    def _position_settings_window(self, dialog):
        """把设置窗默认放在悬浮窗右侧，顶部与悬浮窗顶部齐平。"""
        geo = self.frameGeometry()
        x = geo.right() + 8  # 悬浮窗右缘 + 少许间隙
        y = geo.top()
        # 若右侧放不下则改放左侧，避免超出屏幕
        screen = self.screen().availableGeometry()
        if x + dialog.width() > screen.right():
            x = geo.left() - dialog.width() - 8
        # 若底部溢出屏幕，则上移使设置窗底边不超过屏幕底边
        if y + dialog.height() > screen.bottom():
            y = screen.bottom() - dialog.height()
        if y < screen.top():
            y = screen.top()
        dialog.move(x, y)

    def _position_below_anchor(self, dialog):
        """把弹窗默认放在悬浮窗下方、左缘对齐；下方空间不足则放上方。"""
        geo = self.frameGeometry()
        screen = self.screen().availableGeometry()
        x = geo.left()
        # 优先放下方（留 8px 间隙）
        y = geo.bottom() + 8
        if y + dialog.height() > screen.bottom():
            # 下方放不下 → 放上方
            y = geo.top() - dialog.height() - 8
            if y < screen.top():
                # 上下都放不下 → 钳制在屏幕内
                y = max(screen.top(), screen.bottom() - dialog.height())
        # 横向防溢出
        if x + dialog.width() > screen.right():
            x = screen.right() - dialog.width()
        if x < screen.left():
            x = screen.left()
        dialog.move(x, y)

    def _raise_settings_window(self, dialog):
        """macOS：把设置窗层级提到悬浮窗（状态栏层）之上，保证可操作。"""
        if sys.platform != "darwin" or objc is None:
            return
        try:
            import AppKit
        except ImportError:
            return
        view = objc.objc_object(c_void_p=int(dialog.winId()))
        window = view.window()
        if window is None:
            return
        # 比悬浮窗使用的 NSStatusWindowLevel 更高，确保设置窗在最前
        window.setLevel_(AppKit.NSStatusWindowLevel + 1)

    def _on_settings_changed(self, need_rebuild: bool, need_mode: bool):
        save_config(self.config)
        if need_rebuild:
            self._rebuild_lines()
        if need_mode:
            self._apply_mode()
        self._apply_text_style()
        self._render()

    def _on_dock_icon_toggled(self, hidden: bool):
        save_config(self.config)
        self._apply_dock_icon_policy()

    def _apply_dock_icon_policy(self):
        """macOS：按配置切换 Dock 栏图标显隐。

        通过 NSApplication 激活策略实现：
        - Accessory：不在 Dock 显示图标（窗口仍正常显示）
        - Regular：正常在 Dock 显示图标
        切换后重新应用窗口层级，避免激活策略变化导致置顶/跨 Space 失效。
        """
        if sys.platform != "darwin" or objc is None:
            return
        try:
            import AppKit
        except ImportError:
            return
        policy = (
            AppKit.NSApplicationActivationPolicyAccessory
            if self.config.hide_dock_icon
            else AppKit.NSApplicationActivationPolicyRegular
        )
        AppKit.NSApp.setActivationPolicy_(policy)
        self._set_window_level_top()

    # ---------- 悬停"…"按钮与阅读列表 ----------
    def enterEvent(self, event):
        """鼠标移入浮窗：显示左侧"…"按钮（阅读列表打开时不呼出）。"""
        # “未悬浮隐藏”模式下，悬浮到文本窗上也显示文本
        self._update_text_visibility()
        if self._library_popup is not None and self._library_popup.isVisible():
            super().enterEvent(event)
            return  # 列表已打开：保持"…"隐藏，避免弹列表瞬间又被呼出
        self._btn_hide_timer.stop()
        self.menu_btn.show()
        self.menu_btn.position()
        super().enterEvent(event)

    def leaveEvent(self, event):
        """鼠标移出浮窗：延迟隐藏"…"按钮，给鼠标穿过间隙的时间。"""
        self._btn_hide_timer.start()
        # 略延迟再判定文本窗显隐，避免移向小圆点时的瞬间闪烁
        QTimer.singleShot(60, self._update_text_visibility)
        super().leaveEvent(event)

    def _maybe_hide_menu_btn(self):
        """延迟到点后检查：鼠标仍不在浮窗/按钮/列表上才真正隐藏。"""
        from PySide6.QtGui import QCursor

        pos = QCursor.pos()
        if self.underMouse():
            return
        if self.menu_btn.isVisible() and self.menu_btn.geometry().contains(pos):
            return
        if self._library_popup is not None and self._library_popup.isVisible():
            return
        self.menu_btn.hide()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            # 附属窗口（"…"按钮 / 阅读列表）跟随浮窗移动
            if self.menu_btn.isVisible():
                self.menu_btn.position()
            if self._library_popup is not None and self._library_popup.isVisible():
                self._library_popup.position_beside_anchor()
            event.accept()

    def mouseReleaseEvent(self, event):
        if self._drag_pos is not None:
            pos = self.pos()
            self.config.pos_x = pos.x()
            self.config.pos_y = pos.y()
            save_config(self.config)
        self._drag_pos = None

    # ---------- 键盘（浮窗聚焦时也支持上/下键） ----------
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Up:
            self.advance(-1)
        elif event.key() == Qt.Key_Down:
            self.advance(1)
        else:
            super().keyPressEvent(event)

    def _quit(self):
        from PySide6.QtWidgets import QApplication

        self.save_progress()
        self._destroy_mini()
        QApplication.instance().quit()

    def save_progress(self):
        """保存当前阅读进度到配置（供退出/Cmd+Q 时调用）。"""
        if self.current_entry is not None:
            self.current_entry.index = self.index
        self.config.last_index = self.index
        save_config(self.config)
