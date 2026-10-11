"""V4: 世界观词条（World Info / Lorebook）。

把 ``World/`` 下的背景资料从"整篇语料打分检索"升级为 SillyTavern 式的**词条**：
- ``constant: true`` → 每轮常驻注入（世界观背景 / 硬规则）；
- 带 ``keys`` 的条目 → 命中当前对话/场景关键词时才注入（selective）；
- 无 ``keys`` 且非常驻 → 不主动注入，仅作为全文检索的兜底语料。

条目文件格式（front matter 可选）：

    ---
    keys: [社团, 学生会, 招新]
    constant: false
    position: before_char   # before_char / after_char / at_depth
    depth: 4
    priority: 10
    probability: 100
    ---
    正文……

解析不依赖 PyYAML（避免新增依赖），只识别上述标量/列表。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


@dataclass
class LoreEntry:
    title: str = ""
    content: str = ""
    keys: list[str] = field(default_factory=list)
    constant: bool = False
    position: str = "before_char"   # before_char / after_char / at_depth
    depth: int = 4
    priority: int = 0
    probability: int = 100
    path: str = ""

    @property
    def selective(self) -> bool:
        return bool(self.keys) and not self.constant

    def matches(self, text: str) -> bool:
        if self.constant:
            return True
        if not self.keys:
            return False
        low = (text or "").lower()
        return any(k and k.lower() in low for k in self.keys)

    def to_dict(self) -> dict:
        return {
            "title": self.title, "content": self.content, "keys": list(self.keys),
            "constant": self.constant, "position": self.position, "depth": self.depth,
            "priority": self.priority, "probability": self.probability, "path": self.path,
        }


def _parse_scalar(value: str):
    value = value.strip().strip("'\"")
    if value.lower() in ("true", "yes", "1"):
        return True
    if value.lower() in ("false", "no", "0"):
        return False
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value


def parse_entry(text: str, title: str = "", path: str = "") -> LoreEntry:
    """解析单条词条（front matter + 正文）。"""
    text = text or ""
    entry = LoreEntry(title=title, path=path)
    body = text
    m = _FRONT_MATTER_RE.match(text)
    if m:
        body = text[m.end():]
        for line in m.group(1).splitlines():
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            key, _, value = line.partition(":")
            key, value = key.strip().lower(), value.strip()
            if key == "keys":
                if value.startswith("[") and value.endswith("]"):
                    entry.keys = [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]
                elif value:
                    entry.keys = [v.strip() for v in re.split(r"[，,]", value) if v.strip()]
            elif key in ("constant", "position", "depth", "priority", "probability"):
                setattr(entry, key, _parse_scalar(value))
            elif key == "title" and not title:
                entry.title = str(value).strip("'\"")
    entry.content = body.strip()
    if not entry.title:
        entry.title = path or "词条"
    return entry


def load_entries(files: list[Path]) -> list[LoreEntry]:
    """把文件列表解析为词条（同一文件多条目暂不支持，一份文件一条）。"""
    entries: list[LoreEntry] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            continue
        if not text.strip():
            continue
        entries.append(parse_entry(text, title=f.stem, path=str(f)))
    return entries


def constant_entries(entries: list[LoreEntry]) -> list[LoreEntry]:
    return sorted((e for e in entries if e.constant), key=lambda e: -e.priority)


def select_entries(entries: list[LoreEntry], query: str, limit: int = 4) -> list[LoreEntry]:
    """按关键词命中挑选条目（常驻优先，其次优先级），最多 ``limit`` 条。"""
    picked = constant_entries(entries)
    selective = [e for e in entries if e.selective and e.matches(query)]
    selective.sort(key=lambda e: -e.priority)
    for e in selective:
        if e not in picked:
            picked.append(e)
    return picked[:max(1, limit)]


def render_entries(entries: list[LoreEntry]) -> str:
    if not entries:
        return ""
    return "\n\n".join(f"【{e.title}】\n{e.content}" for e in entries if e.content.strip())
