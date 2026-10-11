"""记忆治理：去重、冲突消解、上限裁剪（V2 长程一致性）。

长程一致性要求：
- 同一事实反复抽取 → **去重**（近重复合并，保留最先出现的一条）；
- 同一对象出现互斥的取值 → **冲突消解**（保留更新的一条，并记录冲突对）；
- 记忆总量有上限 → **裁剪**（默认 80 条，与既有规则一致）。

本模块全部为纯函数，便于离线单测，不依赖 LLM / 文件系统。
"""
from __future__ import annotations

import re

MAX_MEMORY = 80
_TRAILING = "。．，,；;、!！?？… \t"
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]")
# 值类片段：数字（含日期/时间/数量的数字部分）
_VALUE_RE = re.compile(r"\d+")


def normalize_fact(text: str) -> str:
    """去掉首尾空白、压缩内部空白、去掉句末标点。"""
    text = re.sub(r"\s+", " ", (text or "").strip())
    return text.strip(_TRAILING)


def mask_values(text: str) -> str:
    """把数字（日期/时间/数量）统一替换为占位符。

    两条记忆若「掩码后完全相同」，则视为对同一对象的**互斥取值**（冲突）。
    这样既不会把「不同主题的两条独立事实」误判为冲突，也能识别日期/数量级别的矛盾。
    """
    return _VALUE_RE.sub("«v»", normalize_fact(text))


def _ngrams(text: str) -> set[str]:
    """字符 bigram 集合（CJK 与 ASCII 统一，用于相似度）。"""
    tokens = _TOKEN_RE.findall(text.lower())
    grams = set(tokens)
    for i in range(len(tokens) - 1):
        grams.add(tokens[i] + tokens[i + 1])
    return grams


def similarity(a: str, b: str) -> float:
    """字符 bigram Jaccard 相似度，0~1。"""
    ga, gb = _ngrams(a), _ngrams(b)
    if not ga or not gb:
        return 0.0
    inter = len(ga & gb)
    union = len(ga | gb)
    return inter / union if union else 0.0


NEAR_DUPLICATE = 0.9


def merge_facts(existing: list[str], incoming: list[str], limit: int = MAX_MEMORY) -> tuple[list[str], dict]:
    """把新抽取的 facts 合入已有记忆，返回 (新列表, 统计)。

    统计字段：added / deduped / conflicts_resolved / truncated。
    - 近重复（相似度 ≥ 0.9）→ 丢弃；
    - 冲突（掩码后相同但取值不同）→ 用更新的那一条替换旧的；
    - 其它 → 追加。列表保持「旧 → 新」顺序。
    """
    kept: list[str] = []
    masks: list[str] = []
    stats = {"added": 0, "deduped": 0, "conflicts_resolved": 0, "truncated": 0}

    for raw in list(existing) + list(incoming):
        fact = normalize_fact(raw)
        if not fact:
            continue
        is_new = raw not in existing
        mask = mask_values(fact)
        duplicate = False
        conflict_idx = None
        for idx, old in enumerate(kept):
            if similarity(fact, old) >= NEAR_DUPLICATE:
                duplicate = True
                break
            if masks[idx] == mask and old != fact:
                conflict_idx = idx  # 掩码一致但取值不同 → 冲突
        if duplicate:
            stats["deduped"] += 1
            continue
        if conflict_idx is not None:
            kept[conflict_idx] = fact
            masks[conflict_idx] = mask
            stats["conflicts_resolved"] += 1
            if is_new:
                stats["added"] += 1
            continue
        kept.append(fact)
        masks.append(mask)
        if is_new:
            stats["added"] += 1

    if len(kept) > limit:
        stats["truncated"] = len(kept) - limit
        kept = kept[-limit:]
    return kept, stats


def detect_conflicts(facts: list[str]) -> list[tuple[str, str]]:
    """返回疑似冲突的事实对（掩码后相同、取值不同），供人工/审计查看。"""
    pairs: list[tuple[str, str]] = []
    for i in range(len(facts)):
        for j in range(i + 1, len(facts)):
            a, b = normalize_fact(facts[i]), normalize_fact(facts[j])
            if not a or not b or a == b:
                continue
            if mask_values(a) == mask_values(b):
                pairs.append((facts[i], facts[j]))
    return pairs
