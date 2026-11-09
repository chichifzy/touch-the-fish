"""配置管理模块：负责读取/写入用户配置。

配置以 JSON 形式保存在用户主目录下的 ~/.touch_the_fish/config.json。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import asdict, dataclass, field


CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".touch_the_fish")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
# 导入文档的本地缓存目录（原文件删除/移动后仍可从这里继续阅读）
CACHE_DIR = os.path.join(CONFIG_DIR, "cache")


@dataclass
class LibraryEntry:
    """阅读列表中的一本书：源文件路径 + 缓存副本 + 独立阅读进度。"""

    # 源文件路径（可能已被删除/移动，仅用于更新检测）
    file: str

    # 缓存副本路径（阅读的"真相源"）
    cache: str | None = None

    # 本书独立的阅读进度行号
    index: int = 0

    # 加入阅读列表的时间（秒级时间戳），用于排序（最近导入在前）
    added_at: float = 0.0

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict):
        valid = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        return cls(**valid)


@dataclass
class Config:
    # 显示模式："single" 单行 / "double" 双行 / "triple" 三行（类似歌词）
    display_mode: str = "single"

    # 跳行方式："auto" 自动 / "manual" 手动
    advance_mode: str = "manual"

    # 自动模式下的跳行间隔（毫秒）
    auto_interval_ms: int = 3000

    # 每次前进/后退的行数（单行=1；双行可 1/2；三行可 1/3）
    step: int = 1

    # 悬浮文字字号（px）
    font_size: int = 22

    # 每行文字数量（超过则切分为多显示行）
    chars_per_line: int = 20

    # 双行模式下两行之间的行间距（px）
    line_spacing: int = 6

    # 文字描边：开启后文字周围出现黑色描边，提升在浅色背景上的可读性
    text_outline: bool = False

    # 翻页动画："none" 无动画（瞬间切换）/ "smooth" 平滑滚动
    page_animation: str = "none"

    # 隐藏 Dock 栏图标（仅 macOS）：开启后应用不在 Dock 显示图标
    hide_dock_icon: bool = False

    # 手动模式专属：鼠标未悬浮在迷你圆点上时隐藏文本浮窗（带淡入淡出）
    hide_text_when_not_hovering: bool = False

    # 最近一次导入的文档路径（启动时尝试恢复）
    last_file: str | None = None

    # 最近一次导入文档的本地缓存副本路径（原文件缺失时回退使用）
    last_cache: str | None = None

    # 阅读列表：所有导入过的文件（含缓存与独立进度）
    library: list[LibraryEntry] = field(default_factory=list)

    # 旧配置（无 library 字段）是否已完成一次性迁移到阅读列表
    library_migrated: bool = False

    # 最近阅读到的行号（与 last_file 绑定，启动时恢复到该行）
    last_index: int = 0

    # 悬浮窗上次退出时的位置（屏幕坐标）；为 None 时使用默认位置
    pos_x: int | None = None
    pos_y: int | None = None

    # 迷你导航窗上次退出时的位置
    mini_pos_x: int | None = None
    mini_pos_y: int | None = None

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict):
        library = [
            LibraryEntry.from_dict(e)
            for e in data.get("library", [])
            if isinstance(e, dict) and e.get("file")
        ]
        valid = {
            f: data[f]
            for f in cls.__dataclass_fields__
            if f in data and f != "library"
        }
        cfg = cls(**valid)
        cfg.library = library
        return cfg


def load_config() -> Config:
    """从磁盘加载配置，不存在时返回默认配置。"""
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return Config.from_dict(json.load(f))
        except (json.JSONDecodeError, OSError):
            return Config()
    return Config()


def save_config(config: Config) -> None:
    """将配置写入磁盘。"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config.to_dict(), f, ensure_ascii=False, indent=2)


def cache_document(path: str) -> str:
    """把导入的文档复制到缓存目录，返回缓存副本路径。

    多文件共存：按源文件绝对路径的 MD5 前 12 位命名（保留原扩展名），
    同一文件重复导入时覆盖旧副本，不同文件互不影响。
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    key = hashlib.md5(os.path.abspath(path).encode("utf-8")).hexdigest()[:12]
    ext = os.path.splitext(path)[1].lower()
    cache_path = os.path.join(CACHE_DIR, f"{key}{ext}")
    shutil.copy2(path, cache_path)
    return cache_path
