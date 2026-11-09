#!/usr/bin/env bash
# 一键打包脚本：生成 macOS 风格圆角图标 (.icns) 并打包成 .app
#
# 用法：
#   ./build.sh            # 用现有 AppIcon.icns 打包（最快）
#   ./build.sh --icon     # 先从 bookIcon.png 重新生成圆角图标再打包（换图标后用）
#
# 产物：dist/TouchTheFish.app

set -e
cd "$(dirname "$0")"

PY=.venv/bin/python
PYINSTALLER=.venv/bin/pyinstaller

# 确保 PyInstaller 已安装
if [ ! -f "$PYINSTALLER" ]; then
    echo "==> 未检测到 PyInstaller，正在安装…"
    .venv/bin/pip install pyinstaller
fi

# 可选：从 bookIcon.png 重新生成 macOS 风格圆角图标
if [ "$1" = "--icon" ]; then
    echo "==> 从 bookIcon.png 生成圆角图标…"
    "$PY" -c "
import main
from PySide6.QtWidgets import QApplication
app = QApplication([])
main.make_macos_icon(main.ICON_PATH).pixmap(1024, 1024).save('icon_master.png')
"
    rm -rf AppIcon.iconset && mkdir -p AppIcon.iconset
    for s in 16 32 128 256 512; do
        sips -z $s $s icon_master.png --out AppIcon.iconset/icon_${s}x${s}.png >/dev/null
        d=$((s * 2))
        sips -z $d $d icon_master.png --out AppIcon.iconset/icon_${s}x${s}@2x.png >/dev/null
    done
    cp icon_master.png AppIcon.iconset/icon_512x512@2x.png
    iconutil -c icns AppIcon.iconset -o AppIcon.icns
    rm -rf AppIcon.iconset icon_master.png
    echo "==> 已生成 AppIcon.icns"
fi

# 打包
echo "==> 开始打包…"
"$PYINSTALLER" --noconfirm TouchTheFish.spec

echo "==> 完成！产物：dist/TouchTheFish.app"
