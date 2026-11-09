"""圆形半透明小圆点导航窗。

仅在"手动跳行"模式下出现。当鼠标指针位于小圆点上方时，
按键盘"上键"上一行、"下键"下一行。
- macOS：用 NSEvent 全局/本地监听按键，不抢占其他程序的焦点
- 其他平台：回退到 Qt 焦点方式
- 可左键拖动移动位置
"""

import sys

try:
    import objc
except ImportError:
    objc = None

from PySide6.QtCore import (
    Qt,
    QTimer,
    Signal,
    QRectF,
    QRect,
    QPropertyAnimation,
    QEasingCurve,
)
from PySide6.QtGui import QCursor, QPainter, QColor, QPen
from PySide6.QtWidgets import QWidget


# macOS 方向键的 keyCode（与键盘布局无关，比字符更可靠）
_KEYCODE_UP = 126
_KEYCODE_DOWN = 125

# 出现动画：起始放大倍数
_APPEAR_SCALE = 5.0


class MiniWidget(QWidget):
    # 请求上一行 / 下一行（由浮窗连接处理）
    nav_up = Signal()
    nav_down = Signal()
    quit_requested = Signal()
    # 鼠标悬停状态变化（True=进入圆点，False=离开）
    hover_changed = Signal(bool)
    # 双击圆点：请求切换“未悬浮隐藏文本”配置
    toggle_hide_text_requested = Signal()

    DIAMETER = 30

    def __init__(self, config):
        super().__init__()
        self.config = config
        self._drag_pos = None
        self._hovering = False
        self._global_monitor = None
        self._local_monitor = None
        self._appear_anim = None

        self._init_window()

        # 悬停轮询：判断鼠标是否位于小圆点内（仅用于视觉高亮与按键门控）
        self.hover_timer = QTimer(self)
        self.hover_timer.timeout.connect(self._poll_hover)
        self.hover_timer.start(120)

    def _init_window(self):
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(self.DIAMETER, self.DIAMETER)
        # 固定尺寸，禁止拖拽改变大小（出现动画期间会临时放开）
        self.setFixedSize(self.DIAMETER, self.DIAMETER)
        # 位置：优先恢复上次位置，否则默认屏幕右下角附近
        if self.config.mini_pos_x is not None and self.config.mini_pos_y is not None:
            self.move(self.config.mini_pos_x, self.config.mini_pos_y)
        else:
            screen = self.screen().availableGeometry()
            self.move(screen.right() - 120, screen.bottom() - 140)

    def showEvent(self, event):
        super().showEvent(event)
        self._set_window_level_top()
        self._install_key_monitor()
        self._play_appear_animation()

    def _play_appear_animation(self):
        """出现动画：从放大数倍缩小到正常大小，保持中心不变，便于定位。"""
        d = self.DIAMETER
        final = self.geometry()
        cx = final.x() + d / 2
        cy = final.y() + d / 2
        big = int(d * _APPEAR_SCALE)
        start = QRect(int(cx - big / 2), int(cy - big / 2), big, big)

        # 动画需改变尺寸，临时放开固定尺寸约束（结束后恢复以禁止拖拽缩放）
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)

        anim = QPropertyAnimation(self, b"geometry", self)
        anim.setDuration(420)
        anim.setStartValue(start)
        anim.setEndValue(final)
        anim.setEasingCurve(QEasingCurve.OutBack)
        anim.valueChanged.connect(lambda _: self.update())  # 缩放过程中持续重绘
        # 动画结束后重新固定尺寸，防止拖拽改变大小
        anim.finished.connect(lambda: self.setFixedSize(d, d))
        anim.start()
        self._appear_anim = anim  # 保持引用，防止被回收

    def closeEvent(self, event):
        self._remove_key_monitor()
        super().closeEvent(event)

    def _set_window_level_top(self):
        """macOS：将小圆点提升到状态栏级并跨所有 Space（含全屏应用）显示。"""
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
        window.setHidesOnDeactivate_(False)
        window.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorStationary
            | AppKit.NSWindowCollectionBehaviorIgnoresCycle
            | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
        )

    # ---------- 全局按键监听（macOS） ----------
    def _install_key_monitor(self):
        """安装 NSEvent 监听：不抢焦点，仅当鼠标在小圆点内时响应上下键。

        - 全局监听：其他程序处于前台时也能收到按键（仅观察，不吞事件）
        - 本地监听：本程序前台时收到按键，返回 None 可吞掉事件避免误滚动
        需要在"系统设置 → 隐私与安全性 → 辅助功能"授权后全局监听才生效。
        """
        if sys.platform != "darwin" or objc is None:
            return
        try:
            import AppKit
        except ImportError:
            return

        mask = AppKit.NSEventMaskKeyDown

        def handle(event):
            if not self._hovering:
                return event
            code = event.keyCode()
            if code == _KEYCODE_UP:
                self.nav_up.emit()
                return None
            if code == _KEYCODE_DOWN:
                self.nav_down.emit()
                return None
            return event

        # 全局：观察其他应用前台时的按键（不能修改/吞掉，返回值被忽略）
        self._global_monitor = (
            AppKit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                mask, lambda e: handle(e)
            )
        )
        # 本地：本应用前台时的按键，返回 None 吞掉以避免背景滚动
        self._local_monitor = (
            AppKit.NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                mask, handle
            )
        )

    def _remove_key_monitor(self):
        if sys.platform != "darwin" or objc is None:
            return
        try:
            import AppKit
        except ImportError:
            return
        if self._global_monitor is not None:
            AppKit.NSEvent.removeMonitor_(self._global_monitor)
            self._global_monitor = None
        if self._local_monitor is not None:
            AppKit.NSEvent.removeMonitor_(self._local_monitor)
            self._local_monitor = None

    def _poll_hover(self):
        """判断鼠标是否在小圆点内，切换视觉高亮（同时作为按键响应的门控）。"""
        inside = self._point_in_circle(self.mapFromGlobal(QCursor.pos()))
        if inside != self._hovering:
            self._hovering = inside
            self.update()
            self.hover_changed.emit(inside)

    def is_hovering(self) -> bool:
        """当前鼠标是否悬浮在圆点内。"""
        return self._hovering

    def _point_in_circle(self, pos) -> bool:
        w = self.width()
        h = self.height()
        r = min(w, h) / 2
        dx = pos.x() - w / 2
        dy = pos.y() - h / 2
        return dx * dx + dy * dy <= r * r

    # ---------- 键盘（非 macOS 回退：需窗口聚焦） ----------
    def keyPressEvent(self, event):
        if not self._hovering:
            super().keyPressEvent(event)
            return
        if event.key() == Qt.Key_Up:
            self.nav_up.emit()
            event.accept()
        elif event.key() == Qt.Key_Down:
            self.nav_down.emit()
            event.accept()
        else:
            super().keyPressEvent(event)

    # ---------- 拖动 ----------
    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.quit_requested.emit()  # 右击立即退出程序
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            self._drag_pos = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        if self._drag_pos is not None:
            from .config import save_config

            pos = self.pos()
            self.config.mini_pos_x = pos.x()
            self.config.mini_pos_y = pos.y()
            save_config(self.config)
        self._drag_pos = None

    def mouseDoubleClickEvent(self, event):
        """左键双击圆点：切换“未悬浮隐藏文本”配置。"""
        if event.button() == Qt.LeftButton:
            self._drag_pos = None  # 取消本次拖动态，避免双击后误保存位置
            self.toggle_hide_text_requested.emit()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    # ---------- 绘制 ----------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 用当前实际尺寸绘制，动画放大时圆点随之放大
        d = min(self.width(), self.height())
        ox = (self.width() - d) / 2
        oy = (self.height() - d) / 2
        rect = QRectF(ox + 2, oy + 2, d - 4, d - 4)

        # 半透明小圆点：悬停时加深并高亮描边，提示"可用上下键翻行"
        if self._hovering:
            painter.setBrush(QColor(40, 40, 40, 210))
            painter.setPen(QPen(QColor(200, 200, 200, 150), 2))
        else:
            painter.setBrush(QColor(30, 30, 30, 130))
            painter.setPen(QPen(QColor(255, 255, 255, 90), 1.5))
        painter.drawEllipse(rect)

        # 中央小圆心点缀（随尺寸缩放）
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 220 if self._hovering else 120))
        cr = d * 0.1
        painter.drawEllipse(
            QRectF(ox + d / 2 - cr, oy + d / 2 - cr, cr * 2, cr * 2)
        )
        painter.end()
