"""V4: 结构化角色卡解析（对齐知识库既有的《人设提示词模板.md》与 SillyTavern 角色卡）。

角色档案按固定二级/三级标题分块；解析后得到结构化字段，供 V4 提示词拼装：
- ``personality``  ← 性格核心 / 关键标签（ST: personality）
- ``description``  ← 人物气质 + 其他补充（ST: description）
- ``style``        ← 语言风格（V4 新增，ST 里对应 system/post-history 的风格约束）
- ``examples``     ← 对话示例（ST: mes_example，去 AI 味最关键）
- ``relationships``← 重要关系 / 用户关系定位
- ``scenario``     ← 场景 / 开场白

向后兼容：若文档没有这些小节，``structured=False``，``description`` 退化为全文，
``style`` / ``examples`` 为空——与改动前行为一致，不破坏存量角色。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_HEADING_RE = re.compile(r"^\s{0,3}#{2,3}\s*(.+?)\s*#*\s*$")
_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_EXAMPLE_SPLIT_RE = re.compile(r"<START>", re.IGNORECASE)

# 标题别名（同义词归一）→ 结构化字段
SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "personality_core": ("性格核心", "性格", "核心性格"),
    "tags": ("关键标签", "标签", "关键词"),
    "temperament": ("人物气质", "气质", "人物简介", "简介"),
    "style": ("语言风格", "说话方式", "语感", "语言习惯", "口癖"),
    "examples": ("对话示例", "语言示例", "示例对话", "对话例子", "示例"),
    "user_relation": ("用户关系定位", "关系定位", "与用户", "用户定位"),
    "relationships": ("重要关系", "人际关系", "关系"),
    "scenario": ("场景", "当前场景"),
    "greeting": ("开场白", "第一句话", "打招呼"),
}
# 这些小节归入 description（人设正文）
_DESCRIPTION_FIELDS = {"personality_core", "tags", "temperament"}


@dataclass
class CharacterCard:
    name: str = ""
    aliases: list[str] = field(default_factory=list)
    # 结构化字段
    personality_core: str = ""
    tags: str = ""
    temperament: str = ""
    style: str = ""
    examples: str = ""
    user_relation: str = ""
    relationships: str = ""
    scenario: str = ""
    greeting: str = ""
    extra: str = ""            # 未识别小节的正文
    raw: str = ""              # 原始文档
    structured: bool = False   # 是否命中结构化小节

    # ---------- 供提示词使用 ----------
    @property
    def personality(self) -> str:
        """ST: personality = 性格核心 + 关键标签。"""
        parts = [self.personality_core, self.tags]
        return "\n".join(p for p in parts if p.strip())

    @property
    def description(self) -> str:
        """ST: description = 人物气质 + 其余补充；无结构化时退化为全文。"""
        parts = [self.temperament, self.extra]
        body = "\n\n".join(p for p in parts if p.strip())
        return body if body.strip() else (self.raw if not self.structured else "")

    def examples_list(self) -> list[str]:
        """把 ``<START>`` 分隔的示例切成独立示例块。"""
        if not self.examples:
            return []
        chunks = _EXAMPLE_SPLIT_RE.split(self.examples)
        return [c.strip() for c in chunks if c.strip()]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "aliases": list(self.aliases),
            "personality": self.personality,
            "description": self.description,
            "style": self.style,
            "examples": self.examples,
            "user_relation": self.user_relation,
            "relationships": self.relationships,
            "scenario": self.scenario,
            "greeting": self.greeting,
            "structured": self.structured,
        }


def _field_for_heading(heading: str) -> str | None:
    h = heading.strip()
    for field_name, aliases in SECTION_ALIASES.items():
        for a in aliases:
            if h == a or h.startswith(a):
                return field_name
    return None


def _parse_front_matter(text: str) -> tuple[dict, str]:
    """解析极简 YAML front matter（仅 name/aliases/color 等标量），返回 (meta, 正文)。"""
    m = _FRONT_MATTER_RE.match(text)
    if not m:
        return {}, text
    meta: dict = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if value.startswith("[") and value.endswith("]"):
            items = [v.strip().strip("'\"") for v in value[1:-1].split(",")]
            meta[key] = [i for i in items if i]
        else:
            meta[key] = value.strip("'\"")
    return meta, text[m.end():]


def parse_character_card(raw: str, name: str = "") -> CharacterCard:
    """解析结构化角色卡；无结构化小节时退化为整篇 description。"""
    raw = raw or ""
    card = CharacterCard(name=name, raw=raw)
    meta, body = _parse_front_matter(raw)
    if isinstance(meta.get("aliases"), list):
        card.aliases = meta["aliases"]
    elif isinstance(meta.get("aliases"), str) and meta["aliases"]:
        card.aliases = [meta["aliases"]]
    if meta.get("name"):
        card.name = str(meta["name"])

    sections: list[tuple[str | None, list[str]]] = []
    cur_field: str | None = None
    cur_lines: list[str] = []
    for line in body.splitlines():
        hm = _HEADING_RE.match(line)
        if hm:
            sections.append((cur_field, cur_lines))
            cur_field = _field_for_heading(hm.group(1))
            cur_lines = []
        else:
            cur_lines.append(line)
    sections.append((cur_field, cur_lines))

    extras: list[str] = []
    for field_name, lines in sections:
        text = "\n".join(lines).strip()
        if not text:
            continue
        if field_name is None:
            extras.append(text)
        elif field_name in _DESCRIPTION_FIELDS:
            setattr(card, field_name, (getattr(card, field_name) + "\n" + text).strip())
        else:
            prev = getattr(card, field_name)
            setattr(card, field_name, (prev + "\n\n" + text).strip() if prev else text)
    card.extra = "\n\n".join(extras).strip()

    card.structured = bool(card.personality.strip() or card.style.strip()
                           or card.examples.strip() or card.temperament.strip())
    return card
