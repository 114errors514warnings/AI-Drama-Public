"""V4: 文风规范与"去 AI 腔"工具。

集中放置：
- ``ANTI_AI_WORDS``：反 AI 腔负面词表（提示词约束 + 规则检测共用，单一来源）；
- ``find_ai_flavor`` / ``ai_flavor_hit_rate``：规则通道检测；
- ``split_action_dialogue``：把（动作/神态）与对白切分，供前端分层渲染与后端统计；
- ``DEFAULT_STYLE_GUIDE`` / ``load_style_spec``：全局文风规范（知识库 ``World/文风`` 优先）。
"""
from __future__ import annotations

import re
from pathlib import Path

# 反 AI 腔负面词表（单一来源）：提示词里作为"避免这些词"，指标里作为规则检测词。
ANTI_AI_WORDS: tuple[str, ...] = (
    "仿佛", "彷佛", "宛若", "宛如", "犹如", "如同",
    "一丝", "一抹", "眼中闪过一丝", "意味深长", "若有所思",
    "嘴角勾起", "嘴角微微上扬", "嘴角上扬", "眼神深邃", "瞳孔骤缩", "瞳孔微缩",
    "心中一凛", "五味杂陈", "百感交集", "不禁", "不由自主", "下意识",
    "轻轻地", "缓缓地", "悠悠地", "呢喃", "喃喃", "缱绻", "氤氲",
    "空气仿佛凝固", "沉默了片刻", "陷入了沉思", "陷入沉思", "微微一愣", "微微一顿",
    "挑了挑眉", "叹了口气", "眼神暗了暗", "眼神一黯",
    "这一刻，", "整个世界都安静", "空气凝固", "静谧", "涟漪",
)

# 结构性 AI 腔特征（过度使用标点/对偶）
_DASH_RE = re.compile(r"——")
_ELLIPSIS_RE = re.compile(r"…{2,}|\.{3,}")
_COUPLING_RE = re.compile(r"不仅.{0,20}而且|既.{1,12}又.{1,12}")
# （动作/神态）——中文或英文括号
ACTION_RE = re.compile(r"[（(][^）)\n]{0,80}[）)]")


def find_ai_flavor(text: str) -> dict[str, int]:
    """返回命中词 -> 次数（仅统计 >0 的）。"""
    text = text or ""
    hits: dict[str, int] = {}
    for word in ANTI_AI_WORDS:
        count = text.count(word)
        if count:
            hits[word] = count
    return hits


def ai_flavor_hits(text: str) -> int:
    return sum(find_ai_flavor(text).values())


def ai_flavor_hit_rate(text: str) -> float:
    """每千字命中的反 AI 腔词数（词表口径）。空文本返回 0。"""
    text = text or ""
    if not text:
        return 0.0
    return round(ai_flavor_hits(text) / max(1.0, len(text) / 1000.0), 3)


def structural_flags(text: str) -> dict[str, int]:
    """结构性 AI 腔特征计数（破折号 / 省略号 / 对偶句）。"""
    text = text or ""
    return {
        "dash": len(_DASH_RE.findall(text)),
        "ellipsis": len(_ELLIPSIS_RE.findall(text)),
        "coupling": len(_COUPLING_RE.findall(text)),
    }


def split_action_dialogue(text: str) -> list[tuple[str, str]]:
    """把文本切成 [(kind, chunk)]，kind ∈ {action, dialogue}。

    动作 = ``（…）`` / ``(…)``（不跨行）。用于前端把动作降级渲染，或统计旁白化程度。
    """
    text = text or ""
    out: list[tuple[str, str]] = []
    pos = 0
    for m in ACTION_RE.finditer(text):
        if m.start() > pos:
            out.append(("dialogue", text[pos:m.start()]))
        out.append(("action", m.group()))
        pos = m.end()
    if pos < len(text):
        out.append(("dialogue", text[pos:]))
    return out


def actions_only_ratio(text: str) -> float:
    """动作字数占全文比例（用于"整段都是旁白动作"的判定）。"""
    text = text or ""
    if not text:
        return 0.0
    act = sum(len(c) for k, c in split_action_dialogue(text) if k == "action")
    return round(act / len(text), 3)


def normalize_for_display(text: str) -> str:
    """渲染前规范化：``\\r\\n``→``\\n``，折叠 3+ 连续空行，去首尾空白。"""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# 未配置 World/文风 时的默认文风规范
DEFAULT_STYLE_GUIDE = (
    "【文风要求】\n"
    "- 口语优先：像真人聊天，短句为主，允许省略、停顿、半句话。\n"
    "- 不写书面语与哲理长句；不堆砌成语与比喻。\n"
    "- 不总结、不升华、不排比；每句不必工整对仗。\n"
    "- 少用破折号「——」，省略号「……」每 3 句最多 1 次。\n"
    "- 用动作本身传递情绪，少用「慢慢地/轻轻地/缓缓地」等副词修饰。\n"
    "- 避免：" + "、".join(ANTI_AI_WORDS[:24]) + " 等词。"
)


def build_anti_ai_clause(limit: int = 20) -> str:
    """生成提示词用的一句话负面词表。"""
    return "、".join(ANTI_AI_WORDS[:limit])


def load_style_spec(files: list[Path], limit: int = 2000) -> str:
    """读取 ``World/文风`` 下的规范文件并拼接；无文件返回空串。"""
    parts: list[str] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8").strip()
        except Exception:  # noqa: BLE001
            continue
        if text:
            parts.append(f"【{f.stem}】\n{text}")
    out = "\n\n".join(parts)
    return out[:limit]
