"""阅读列表组件：悬停显示的"…"按钮 + 文件列表弹层。

- MenuButton：鼠标移入主浮窗时出现在浮窗左上角（浮窗自身坐标内），
  点击后弹出阅读列表。
- LibraryPopup：紧贴主浮窗左侧、顶部与浮窗平齐的独立置顶窗口，
  列出所有导入过的文件，点击切换；文字样式与主浮窗保持一致
  （同字体/颜色/描边，字号略小）。
"""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF
from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget

try:
    import objc
except ImportError:
    objc = None


def _set_tool_window_level(widget: QWidget):
    """macOS：置顶工具窗通用设置（与主浮窗同层级）。"""
    if sys.platform != "darwin" or objc is None:
        return
    try:
        import AppKit
    except ImportError:
        return
    view = objc.objc_object(c_void_p=int(widget.winId()))
    window = view.window()
    if window is None:
        return
    window.setLevel_(AppKit.NSStatusWindowLevel)
    window.setHidesOnDeactivate_(False)
    window.setCollectionBehavior_(
        AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
        | AppKit.NSWindowCollectionBehaviorStationary
        | AppKit.NSWindowCollectionBehaviorIgnoresCycle
        | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
    )


class MenuButton(QWidget):
    """浮窗左侧的"…"按钮（独立置顶小窗，不遮住浮窗内文字）。"""

    clicked = Signal()

    BUTTON_SIZE = 22
    GAP = -10  # 与浮窗左缘的间距

    def __init__(self, anchor: QWidget):
        super().__init__(None)
        self.anchor = anchor
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(self.BUTTON_SIZE, self.BUTTON_SIZE)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("阅读列表")
        self.hide()

    def position(self):
        """贴在浮窗左侧外部（留 GAP 间距），顶部与浮窗平齐。"""
        geo = self.anchor.frameGeometry()
        self.move(geo.left() - self.width() - self.GAP, geo.top())

    def showEvent(self, event):
        super().showEvent(event)
        self.position()
        _set_tool_window_level(self)

    def leaveEvent(self, event):
        # 鼠标离开按钮：若不在浮窗上则隐藏（可能正移向浮窗）
        from PySide6.QtGui import QCursor

        if not self.anchor.frameGeometry().contains(QCursor.pos()):
            self.hide()
        super().leaveEvent(event)

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QPen

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        # 半透明圆角背景，与浮窗风格一致
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(20, 20, 20, 180))
        painter.drawRoundedRect(self.rect(), 6, 6)
        # 三个点（水平居中）
        pen = QPen(QColor(255, 255, 255, 200))
        pen.setCapStyle(Qt.RoundCap)
        pen.setWidthF(2.4)
        painter.setPen(pen)
        cy = self.height() / 2
        r = self.width() / 2
        for dx in (-4, 0, 4):
            painter.drawPoint(r + dx, cy)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
        else:
            super().mousePressEvent(event)


class LibraryItemLabel(QWidget):
    """列表项：一行文件名（OutlinedLabel 风格，自绘描边文字）。"""

    clicked = Signal()
    delete_clicked = Signal()

    # 文件名右侧垃圾桶热区宽度（自绘小图标）
    TRASH_W = 22

    def __init__(self, text: str, font: QFont, color: QColor, outline: bool,
                 outline_width: float, full_name: str | None = None, parent=None):
        super().__init__(parent)
        self._full_text = text  # 完整文件名（截断前）
        self._text = text
        self._font = font
        self._color = color
        self._outline = outline
        self._outline_width = outline_width
        self._hovered = False
        # 二次确认状态：点击垃圾桶后变红色对勾，再点才真正删除
        self._confirming = False
        self._confirm_timer = QTimer(self)
        self._confirm_timer.setSingleShot(True)
        self._confirm_timer.setInterval(3000)
        self._confirm_timer.timeout.connect(self._cancel_confirm)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(full_name or text)  # 悬停显示完整文件名

    def _cancel_confirm(self):
        """退出删除确认状态（超时或点击别处），恢复垃圾桶图标。"""
        if self._confirming:
            self._confirming = False
            self.update()

    def elide_text(self, max_width: int):
        """按最大像素宽度截断文件名（尾部省略号），用于适配左侧空间。"""
        from PySide6.QtGui import QFontMetrics

        fm = QFontMetrics(self._font)
        elided = fm.elidedText(self._full_text, Qt.ElideRight, max_width)
        if elided != self._text:
            self._text = elided
            self.updateGeometry()
            self.update()

    def sizeHint(self):
        from PySide6.QtCore import QSize

        fm = QFontMetricsF(self._font)
        text = self._text or " "
        w = fm.horizontalAdvance(text)
        h = fm.height()
        pad = (int(round(self._outline_width)) + 1) if self._outline else 1
        return QSize(int(w) + pad * 2 + 20 + self.TRASH_W, int(h) + pad * 2 + 4)

    def minimumSizeHint(self):
        return self.sizeHint()

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._cancel_confirm()  # 鼠标移开即取消删除确认
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            in_trash = event.position().x() >= self.width() - self.TRASH_W
            if in_trash:
                if self._confirming:
                    # 第二次点击（红色对勾）：确认删除
                    self._confirm_timer.stop()
                    self._confirming = False
                    self.delete_clicked.emit()
                else:
                    # 第一次点击：进入确认状态，图标变红色对勾
                    self._confirming = True
                    self._confirm_timer.start()
                    self.update()
            else:
                self._cancel_confirm()
                self.clicked.emit()
            event.accept()
        else:
            super().mousePressEvent(event)

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        # 悬停高亮背景
        if self._hovered:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(61, 90, 128, 160))
            painter.drawRoundedRect(self.rect().adjusted(0, 2, 0, -2), 8, 8)

        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.setFont(self._font)
        fm = QFontMetricsF(self._font)
        pad = (int(round(self._outline_width)) + 1) if self._outline else 1
        baseline = (self.height() + fm.ascent() - fm.descent()) / 2.0
        x = float(pad + 10)

        if self._outline:
            d = max(1, int(round(self._outline_width)))
            painter.setPen(QColor(0, 0, 0))
            offsets = [
                (-d, 0), (d, 0), (0, -d), (0, d),
                (-d, -d), (d, -d), (-d, d), (d, d),
            ]
            for dx, dy in offsets:
                painter.drawText(int(x) + dx, int(baseline) + dy, self._text)
            painter.setPen(self._color)
            painter.drawText(int(x), int(baseline), self._text)
        else:
            painter.setPen(self._color)
            painter.drawText(int(x), int(baseline), self._text)

        # 行尾图标：确认态画红色对勾（常显），否则悬停时画垃圾桶
        if self._confirming:
            self._paint_check(painter)
        elif self._hovered:
            self._paint_trash(painter)
        painter.end()

    def _paint_check(self, painter):
        """画红色对勾：确认删除。"""
        from PySide6.QtGui import QPen

        cx = self.width() - self.TRASH_W / 2
        cy = self.height() / 2
        pen = QPen(QColor(255, 90, 90, 240))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        pen.setWidthF(2.2)
        painter.setPen(pen)
        # 对勾两段线
        painter.drawLine(int(cx - 4), int(cy), int(cx - 1), int(cy + 3.5))
        painter.drawLine(int(cx - 1), int(cy + 3.5), int(cx + 4.5), int(cy - 3.5))

    def _paint_trash(self, painter):
        """在行尾画一个简笔垃圾桶：盖子 + 桶身 + 提手。"""
        from PySide6.QtGui import QPen

        w = 8  # 桶身宽度（窄于高度，保持竖直比例）
        h = 10  # 桶身高度
        cx = self.width() - self.TRASH_W / 2  # 热区中心
        cy = self.height() / 2
        pen = QPen(QColor(255, 120, 120, 220))
        pen.setCapStyle(Qt.RoundCap)
        pen.setWidthF(1.6)
        painter.setPen(pen)
        # 桶身（圆角矩形轮廓）：整体以 cy 为中心上下分布
        top = cy - h / 2 + 2
        painter.drawRoundedRect(
            int(cx - w / 2), int(top), w, h, 2, 2
        )
        # 盖子横线（略宽于桶身）
        painter.drawLine(
            int(cx - w / 2 - 1.5), int(top), int(cx + w / 2 + 1.5), int(top)
        )
        # 提手小竖线
        painter.drawLine(int(cx), int(top - 2.5), int(cx), int(top))


class LibraryPopup(QWidget):
    """阅读列表弹层：紧贴主浮窗左侧、顶部平齐的置顶窗口。"""

    # 请求切换到指定文件（参数：LibraryEntry.file 源路径）
    file_selected = Signal(str)
    # 请求移除指定文件的书目（参数：LibraryEntry.file 源路径）
    remove_requested = Signal(str)
    # 弹层关闭（无论何种方式），供调用方清理引用
    popup_closed = Signal()

    def __init__(self, entries, font: QFont, color: QColor, outline: bool,
                 outline_width: float, current_file: str | None, anchor: QWidget):
        super().__init__(None)
        self.entries = entries
        self.anchor = anchor
        self._current_file = current_file

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        # 外层布局：只放一个滚动区域；内边距交给内部容器与滚动区
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 滚动区域：条目超量时出现竖向滚动条，宽度不额外占用横向滚动条
        self._scroll = QScrollArea(self)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        outer.addWidget(self._scroll)

        # 内部容器：承载所有条目，高度随条目数增长
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(2)  # 条目间距收紧，减少行间空隙
        self._scroll.setWidget(container)

        # 底色卡片，与浮窗风格一致；滚动条做成浅色细条
        self.setStyleSheet(
            """
            LibraryPopup {
                background: rgba(20, 20, 20, 200);
                border-radius: 14px;
            }
            QScrollArea { background: transparent; }
            QScrollArea > QWidget > QWidget { background: transparent; }
            QScrollBar:vertical {
                background: transparent;
                width: 6px;
                margin: 2px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 90);
                border-radius: 3px;
                min-height: 24px;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical { background: transparent; }
            """
        )

        for entry in entries:
            full_name = os.path.basename(entry.file)
            # 只显示前 6 个字，超出用省略号（完整名见悬停 tooltip）
            name = full_name[:6] + "…" if len(full_name) > 6 else full_name
            label = LibraryItemLabel(
                name, font, color, outline, outline_width,
                full_name=full_name, parent=self,
            )
            if entry.file == current_file:
                # 当前书高亮（不可点击，或点击无操作）
                label.clicked.connect(lambda: None)
            else:
                # mypy: 捕获循环变量
                label.clicked.connect(
                    lambda f=entry.file: self._on_select(f)
                )
            # 垃圾桶：请求移除（含当前书，由主浮窗确认后处理）
            label.delete_clicked.connect(
                lambda f=entry.file: self.remove_requested.emit(f)
            )
            layout.addWidget(label)

        self._fit_size()

    def _fit_size(self):
        """按内容计算尺寸，并把高度钳制在屏幕可用高度的 80% 以内。

        未超限时正常自适应；超限时固定到上限并让滚动区出现竖向滚动条，
        同时为滚动条预留一点宽度，避免遮住文件名。
        """
        container = self._scroll.widget()
        hint = container.sizeHint()
        w = hint.width()
        h = hint.height()
        screen = self.anchor.screen().availableGeometry()
        max_h = int(screen.height() * 0.8)
        if h > max_h:
            h = max_h
            w += self._scroll.verticalScrollBar().sizeHint().width() + 4
        self.setFixedSize(w, h)

    def _on_select(self, file: str):
        self.file_selected.emit(file)
        self.close()

    def showEvent(self, event):
        super().showEvent(event)
        self.position_beside_anchor()
        _set_tool_window_level(self)

    def position_beside_anchor(self):
        """紧贴主浮窗左侧（稍留间距），顶部与浮窗平齐。

        左侧空间不足时优先压缩列表宽度（截断文件名），
        仅当浮窗几乎贴死屏幕左缘、连最窄列表都放不下时才改放右侧。
        """
        geo = self.anchor.frameGeometry()
        screen = self.anchor.screen().availableGeometry()
        x = geo.left() - self.width() + 15
        if x < screen.left():
            # 压缩宽度：可用宽度 = 浮窗左缘 - 屏幕左缘 - 间距 - 左右内边距
            avail = geo.left() - screen.left() - 2 - 16
            if avail >= 80:
                self._shrink_to(avail)
                x = geo.left() - self.width() + 15
            else:
                x = geo.right() + 2  # 实在放不下才放右侧
        y = geo.top()
        if y + self.height() > screen.bottom():
            y = screen.bottom() - self.height()
        self.move(x, y)

    def _shrink_to(self, avail: int):
        """把列表压缩到不超过 avail 像素宽（截断各行文件名）。"""
        changed = False
        for item in self.findChildren(LibraryItemLabel):
            # sizeHint 额外含左右内边距约 20px
            item.elide_text(max(40, avail - 20))
            changed = True
        if changed:
            self._scroll.widget().layout().activate()
            self._fit_size()

    def leaveEvent(self, event):
        """鼠标离开列表后自动关闭。"""
        self.close()
        super().leaveEvent(event)

    def closeEvent(self, event):
        self.popup_closed.emit()
        super().closeEvent(event)
