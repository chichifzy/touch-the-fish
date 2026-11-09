"""可选黑色描边的文字标签（自绘，QLabel 样式表无法真正描边）。

左对齐、垂直居中，尺寸随文字与字号自适应，行为对齐原先的 QLabel。
从 floating_widget 抽出，供主浮窗、翻页动画与阅读列表共用。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter
from PySide6.QtWidgets import QWidget


class OutlinedLabel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""
        self._font = QFont()
        self._color = QColor(255, 255, 255)
        self._outline = False
        self._outline_color = QColor(0, 0, 0)
        self._outline_width = 3.0
        self.setAttribute(Qt.WA_TranslucentBackground)

    def setText(self, text: str):
        if text != self._text:
            self._text = text
            self.updateGeometry()
            self.update()

    def text(self) -> str:
        return self._text

    def configure(self, font: QFont, color: QColor, outline: bool, outline_width: float = 3.0):
        """设置字体、文字颜色、是否描边及描边宽度，并触发重排/重绘。"""
        self._font = font
        self._color = color
        self._outline = outline
        self._outline_width = max(1.0, outline_width)
        self.updateGeometry()
        self.update()

    def sizeHint(self):
        from PySide6.QtCore import QSize

        fm = QFontMetricsF(self._font)
        text = self._text or "\u00A0"
        w = fm.horizontalAdvance(text)
        h = fm.height()
        pad = (int(round(self._outline_width)) + 1) if self._outline else 1
        return QSize(int(w) + pad * 2, int(h) + pad * 2)

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, event):
        if not self._text:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.setFont(self._font)
        fm = QFontMetricsF(self._font)
        # 垂直居中的基线位置；左对齐留出描边所需边距
        pad = (int(round(self._outline_width)) + 1) if self._outline else 1
        baseline = (self.height() + fm.ascent() - fm.descent()) / 2.0
        x = float(pad)

        if self._outline:
            # 多方向偏移描边：沿 8 个方向以小偏移画黑色底字，笔画清晰不糊，
            # 再在正中叠白字。偏移量取较小值（1~2px），避免中文笔画粘连。
            d = max(1, int(round(self._outline_width)))
            painter.setPen(self._outline_color)
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
        painter.end()
