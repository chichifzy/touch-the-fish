"""文档解析与分行。

支持导入 .txt / .md / .docx，统一解析为纯文本段落，
再按"每行文字数量"切分为逐行显示的显示行列表。
"""

from __future__ import annotations

import difflib
import os


def _read_txt(path: str) -> list[str]:
    """读取纯文本 / Markdown，按换行拆分为段落。"""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    return content.split("\n")


def _read_docx(path: str) -> list[str]:
    """读取 Word 文档，每个段落作为一行。"""
    from docx import Document

    doc = Document(path)
    return [p.text for p in doc.paragraphs]


def parse_document(path: str) -> list[str]:
    """解析文档，返回段落列表（未按每行字数切分）。

    根据扩展名选择解析方式，.docx 用 python-docx，其余按纯文本处理。
    """
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        paragraphs = _read_docx(path)
    else:
        paragraphs = _read_txt(path)
    # 去掉每段行尾空白；保留空段落以维持原有分段的呼吸感
    return [p.rstrip() for p in paragraphs]


def split_lines(paragraphs: list[str], chars_per_line: int) -> list[str]:
    """把段落按每行字数切分为显示行列表。

    - 每个段落独立切分，不跨段落合并
    - 空段落保留为一个空行
    - chars_per_line 至少为 1
    """
    n = max(1, int(chars_per_line))
    lines: list[str] = []
    for para in paragraphs:
        text = para.strip()
        if not text:
            lines.append("")
            continue
        for i in range(0, len(text), n):
            lines.append(text[i : i + n])
    if not lines:
        lines = [""]
    return lines


def diff_documents(
    old_paragraphs: list[str], new_paragraphs: list[str], preview_limit: int = 6
) -> dict:
    """按段落对比新旧文档，统计增删行数并生成类 git diff 预览。

    返回字典：
    - added：新增行数
    - removed：删除行数
    - changed：是否有任何差异
    - preview：预览行列表，元素形如 "+文本" / "-文本"（最多 preview_limit 条）
    """
    added = 0
    removed = 0
    preview: list[str] = []
    matcher = difflib.SequenceMatcher(a=old_paragraphs, b=new_paragraphs)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        for line in old_paragraphs[i1:i2]:
            removed += 1
            if len(preview) < preview_limit:
                preview.append("-" + line)
        for line in new_paragraphs[j1:j2]:
            added += 1
            if len(preview) < preview_limit:
                preview.append("+" + line)
    return {
        "added": added,
        "removed": removed,
        "changed": added > 0 or removed > 0,
        "preview": preview,
    }
