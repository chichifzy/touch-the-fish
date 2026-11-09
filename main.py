"""程序入口：启动悬浮文本浏览工具。"""

import os
import sys

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QApplication

from src.floating_widget import FloatingWidget

ICON_PATH = os.path.join(
    getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))),
    "bookIcon.png",
)


def make_macos_icon(path, canvas=1024):
    """把方形图片处理成 macOS 风格图标：四周留白 + 圆角。"""
    src = QPixmap(path)
    if src.isNull():
        return QIcon(path)

    content = round(canvas * 0.82)  # 实际内容约占画布 82%，四周留白
    radius = content * 0.225  # 圆角半径约为内容边长的 22.5%
    offset = (canvas - content) / 2

    scaled = src.scaled(
        content, content, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
    )

    result = QPixmap(canvas, canvas)
    result.fill(Qt.transparent)

    painter = QPainter(result)
    painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    rect = QRectF(offset, offset, content, content)
    path_clip = QPainterPath()
    path_clip.addRoundedRect(rect, radius, radius)
    painter.setClipPath(path_clip)
    # 居中绘制（KeepAspectRatioByExpanding 可能略大于内容区）
    painter.drawPixmap(
        int(offset - (scaled.width() - content) / 2),
        int(offset - (scaled.height() - content) / 2),
        scaled,
    )
    painter.end()

    return QIcon(result)


def main():
    app = QApplication(sys.argv)
    app.setWindowIcon(make_macos_icon(ICON_PATH))  # 设置应用图标（Dock / 窗口）
    app.setQuitOnLastWindowClosed(False)  # 关闭窗口不退出，由右键菜单退出

    widget = FloatingWidget()
    widget.show()

    # 兜底：Cmd+Q 等非右键退出时也保存阅读进度
    app.aboutToQuit.connect(widget.save_progress)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
