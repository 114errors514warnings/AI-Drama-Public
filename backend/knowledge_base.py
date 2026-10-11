"""知识库（Knowledge Base）：按「Character / Memory / World」三目录约定扫描、分类、检索。

一个知识库 = 一个世界，根目录内主要读取三个文件夹：
- Character/：角色档案（人设），严格按 md 读取，按文件名归档为对应角色
- Memory/：角色长期记忆，严格按 md 读取，按文件名归到对应角色，
  创建角色时作为其初始长期记忆
- World/：混杂世界观背景知识，在世界审查（审核）/ 梗概总结时检索引用

若根目录不存在或三目录缺失，由会话创建逻辑自动新建。
"""
from __future__ import annotations

import re
from pathlib import Path

from .character_card import parse_character_card
from .lorebook import load_entries, render_entries, select_entries
from .style import load_style_spec

CHARACTER_DIR_RE = re.compile(r"(人物|人设|角色|character|characters)", re.IGNORECASE)
RULE_DIR_RE = re.compile(r"(规则|评判标准|rule|rules)", re.IGNORECASE)
SKIP_RE = re.compile(r"(\.obsidian|\.backup|\.git|node_modules|草稿|备份)", re.IGNORECASE)
COLLECTION_NAME_RE = re.compile(r"(名录|列表|合集|目录|一览|总结|模板|索引|README)", re.IGNORECASE)

# V4：世界观内容里"永不注入角色提示词"的用途目录/文件。
# 写作辅助 / 评判标准 / 风格分析 / 大纲 / 草稿 + 模板与名录类索引。
LORE_EXCLUDE_RE = re.compile(
    r"(\.obsidian|\.backup|\.git|node_modules|"
    r"写作辅助|评判标准|风格相关|草稿|备份|大纲|"
    r"模板|名录|README)",
    re.IGNORECASE,
)

# V4：结构化世界观目录（建立后启用"常驻/词条"机制，否则回退旧行为）
WORLD_BACKGROUND_DIRS = ("背景", "设定背景")
WORLD_RULE_DIRS = ("规则",)
WORLD_ENTRY_DIRS = ("词条", "词条库", "lore", "lorebook")
WORLD_STYLE_DIRS = ("文风", "style")

MAX_PROFILE = 6000
MAX_DOC = 1500


class KnowledgeBase:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)  # 允许创建新知识库（根目录不存在时一并新建）
        self.world_name = self.root.name
        self.character_files: dict[str, list[Path]] = {}
        self.memory_files: dict[str, list[Path]] = {}
        self.character_aliases: dict[str, str] = {}  # 标题别名 → 规范名（文档名）
        self.lore_files: list[Path] = []
        # V4：结构化世界观目录（背景/规则/词条/文风）
        self.background_files: list[Path] = []
        self.rule_files: list[Path] = []
        self.entry_files: list[Path] = []
        self.style_files: list[Path] = []
        self._scan()

    # ---------- 扫描 ----------
    def _scan(self) -> None:
        """按 Character / Memory / World 三目录约定读取。

        - Character/ → 角色档案（按文件名归档）
        - Memory/   → 角色长期记忆（按文件名归档，创建角色时作为初始记忆）
        - World/    → 混杂世界观背景（作为检索语料）
        """
        char_dir = self.root / "Character"
        mem_dir = self.root / "Memory"
        world_dir = self.root / "World"
        for base, attr in ((char_dir, self.character_files), (mem_dir, self.memory_files)):
            if base.exists():
                for f in base.rglob("*.md"):
                    rel_str = str(f.relative_to(self.root)).lower()
                    if SKIP_RE.search(rel_str):
                        continue
                    canonical, heading = self._extract_name(f)
                    if not canonical or COLLECTION_NAME_RE.search(canonical):
                        continue
                    attr.setdefault(canonical, []).append(f)
                    if heading and heading != canonical and attr is self.character_files:
                        # 文档标题降级为别名（用于匹配，不再作为正式名字）
                        self.character_aliases.setdefault(heading, canonical)
        if world_dir.exists():
            self._scan_world(world_dir)

    def _scan_world(self, world_dir: Path) -> None:
        """扫描 World/：区分结构化目录（背景/规则/词条/文风）与旧的散装语料。

        V4：``写作辅助 / 评判标准 / 风格相关 / 大纲 / 草稿 / 模板 / 名录`` 一律排除，
        绝不进入角色提示词（根治"角色被诱导成写手/审稿人"）。
        """
        legacy: list[Path] = []
        for f in world_dir.rglob("*.md"):
            rel_str = str(f.relative_to(self.root)).lower()
            if LORE_EXCLUDE_RE.search(rel_str):
                continue
            rel_parts = f.relative_to(world_dir).parts
            top = rel_parts[0] if len(rel_parts) > 1 else ""
            if top in WORLD_BACKGROUND_DIRS:
                self.background_files.append(f)
            elif top in WORLD_RULE_DIRS:
                self.rule_files.append(f)
            elif top in WORLD_ENTRY_DIRS:
                self.entry_files.append(f)
            elif top in WORLD_STYLE_DIRS:
                self.style_files.append(f)
            else:
                legacy.append(f)
        self.lore_files = legacy

        # 顶层 Style/ 目录等价于 World/文风/
        style_dir = self.root / "Style"
        if style_dir.exists():
            for f in style_dir.rglob("*.md"):
                if not LORE_EXCLUDE_RE.search(str(f.relative_to(self.root)).lower()):
                    self.style_files.append(f)

    @property
    def has_world_scheme(self) -> bool:
        """是否已启用结构化世界观（建立了 背景/词条/文风 任一日录）。"""
        return bool(self.background_files or self.entry_files or self.style_files)

    @staticmethod
    def _extract_name(f: Path) -> tuple[str, str]:
        """角色名以文档文件名为准；文档 # 标题仅作为别名返回。

        返回 (规范名, 标题别名)。
        """
        canonical = re.split(r"\s*[-—–]\s*", f.stem.strip())[0].strip()
        heading = ""
        try:
            with f.open(encoding="utf-8") as fh:
                for _ in range(20):
                    line = fh.readline()
                    if not line:
                        break
                    if line.startswith("# "):
                        heading = re.split(r"\s*[-—–]\s*", line[2:].strip())[0].strip()
                        break
        except Exception:  # noqa: BLE001
            pass
        return canonical, heading


    # ---------- 基本信息 ----------
    def character_names(self) -> list[str]:
        return sorted(self.character_files)

    def lore_topics(self) -> list[str]:
        return sorted({f.stem for f in self.lore_files})

    def overview(self) -> dict:
        return {
            "world_name": self.world_name,
            "root": str(self.root),
            "characters": self.character_names(),
            "lore_topics": self.lore_topics(),
        }

    # ---------- 读取 ----------
    @staticmethod
    def _read(f: Path, limit: int) -> str:
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            return ""
        if len(text) > limit * 2:
            text = text[: limit * 2]
        return text.strip()

    @staticmethod
    def _render_files(files: list[Path], limit: int) -> str:
        parts = []
        for f in files:
            text = KnowledgeBase._read(f, MAX_DOC)
            if text.strip():
                parts.append(f"【{f.stem}】\n{text.strip()}")
        out = "\n\n".join(parts)
        if len(out) > limit:
            out = out[:limit] + "\n…（已截断）"
        return out

    def world_constant(self, limit: int = 3500) -> str:
        """常驻世界观：``World/背景`` + ``World/词条`` 之外的世界观语料。

        - 已启用结构化世界观（存在 背景/词条/文风 目录）→ 只取 ``背景`` + ``规则``；
        - 未启用（旧知识库）→ 回退为"全部未排除的世界观语料"（已踢掉写作辅助/评判标准等）。
        """
        if self.has_world_scheme:
            return self._render_files(self.background_files + self.rule_files, limit)
        return self._render_files(self.lore_files, limit)

    def rules_text(self, limit: int = 3500) -> str:
        """[兼容] 旧接口，等价于 :meth:`world_constant`。"""
        return self.world_constant(limit=limit)

    def lore_entries(self) -> list:
        """世界观词条（Lorebook）：``World/词条`` 的条目 + 旧散装语料（无 keys，仅检索兜底）。"""
        return load_entries(list(self.entry_files) + list(self.lore_files))

    def match_lore(self, query: str, limit: int = 3) -> str:
        """按关键词命中挑选世界观词条并渲染（selective 注入）。"""
        return render_entries(select_entries(self.lore_entries(), query, limit=limit))

    def style_spec(self, limit: int = 2000) -> str:
        """全局文风规范（``World/文风`` 或 ``Style/``）。"""
        return load_style_spec(self.style_files, limit=limit)

    def get_character_card(self, name: str):
        """解析结构化角色卡（V4）；未结构化时 description 退化为全文。"""
        key = self.resolve_character(name)
        if not key:
            return None
        return parse_character_card(self.get_character_profile(key) or "", key)

    # ---------- 角色检索 ----------
    def resolve_character(self, name: str) -> str | None:
        """把用户/导演给的角色名解析为知识库中的规范角色名（文档名）。

        匹配顺序：规范名精确 → 标题别名 → 子串 → 去括号核心名。
        """
        name = (name or "").strip()
        if not name:
            return None
        if name in self.character_files:
            return name
        if name in self.character_aliases:
            return self.character_aliases[name]
        for key in self.character_files:
            if name in key or key in name:
                return key
        core = re.split(r"[（(]", name)[0].strip()
        if core:
            for key in self.character_files:
                kc = re.split(r"[（(]", key)[0].strip()
                if core == kc or core in kc or kc in core:
                    return key
        return None

    def get_character_profile(self, name: str) -> str | None:
        key = self.resolve_character(name)
        if not key:
            return None
        files = self.character_files[key]
        parts: list[str] = []
        total = 0
        for f in files:
            text = self._read(f, 4000)
            if not text.strip():
                continue
            header = f"{f.parent.name}/{f.stem}" if len(files) > 1 else f.stem
            parts.append(f"【{header}】\n{text.strip()}")
            total += len(text)
            if total >= MAX_PROFILE:
                break
        return "\n\n".join(parts)[:MAX_PROFILE]

    def get_character_memory(self, name: str) -> str:
        """读取 Memory/<文件名>.md 的内容，作为该角色的初始长期记忆。"""
        key = self.resolve_character(name)
        if not key:
            return ""
        files = self.memory_files.get(key, [])
        parts: list[str] = []
        for f in files:
            text = self._read(f, 4000)
            if text.strip():
                parts.append(text.strip())
        return "\n\n".join(parts)[:8000]

    def get_character_brief(self, name: str, limit: int = 40) -> str:
        """抽取角色档案正文里「标题之后」的第一段描述作为一行简介。

        跳过 markdown 标题（# 角色名、## 人设 等）与空行，以及短的收集类小标题，
        取第一个描述性正文行，截断到 ≤limit 字（超出加 …）。抽不出则返回空串。
        """
        key = self.resolve_character(name)
        if not key:
            return ""
        files = self.character_files.get(key, [])
        if not files:
            return ""
        text = self._read(files[0], 3000)
        for line in text.splitlines():
            raw = line.strip().lstrip("\ufeff\u3000")
            if not raw:
                continue
            if raw.startswith("#"):
                continue  # markdown 标题
            if len(raw) <= 12 and COLLECTION_NAME_RE.search(raw):
                continue  # 短的收集类小标题（“人设”“关系”等）
            brief = raw
            if len(brief) > limit:
                brief = brief[:limit].rstrip("，。；、！？… ") + "…"
            return brief
        return ""

    # ---------- 世界观检索 ----------
    def search_lore(self, query: str, top_k: int = 4) -> list[dict]:
        q_tokens = tokenize(query)
        scored: list[tuple[float, Path]] = []
        for f in self.lore_files:
            text = self._read(f, 4000).lower()
            if not text:
                continue
            score = 0.0
            for t in q_tokens:
                c = text.count(t)
                if c:
                    score += 1 + min(c, 3) * 0.5
            if query.strip() and query.strip().lower() in text:
                score += 10
            if score > 0:
                scored.append((score, f))
        scored.sort(key=lambda x: x[0], reverse=True)
        out = []
        for score, f in scored[:top_k]:
            out.append({
                "title": f.stem,
                "path": str(f.relative_to(self.root)),
                "score": round(score, 2),
                "content": self._read(f, MAX_DOC),
            })
        return out


def tokenize(text: str) -> list[str]:
    """中文文本关键词：ASCII 词 + 中文连续段及其二元组。"""
    tokens: list[str] = []
    for m in re.finditer(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", text):
        seg = m.group()
        if seg[0].isascii():
            tokens.append(seg.lower())
        else:
            tokens.append(seg)
            if len(seg) > 1:
                for i in range(len(seg) - 1):
                    tokens.append(seg[i:i + 2])
    return tokens

