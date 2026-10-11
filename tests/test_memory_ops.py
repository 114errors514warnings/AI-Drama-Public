"""记忆治理：去重 / 冲突消解 / 上限裁剪。"""
from __future__ import annotations

from backend.memory_ops import MAX_MEMORY, detect_conflicts, merge_facts, normalize_fact, similarity


def test_normalize_fact_strips_noise() -> None:
    assert normalize_fact("  阿明喜欢 吃苹果 ， 。 ") == "阿明喜欢 吃苹果"
    assert normalize_fact("") == ""


def test_merge_facts_dedupes_exact_and_near_duplicates() -> None:
    existing = ["阿明认识小红"]
    incoming = ["阿明认识小红", "阿明认识小红", "阿明认识小红！"]
    merged, stats = merge_facts(existing, incoming)
    assert merged.count("阿明认识小红") == 1
    assert stats["deduped"] >= 2


def test_merge_facts_resolves_conflict_keeps_newer() -> None:
    existing = ["阿明的生日是3月5日"]
    incoming = ["阿明的生日是4月1日"]
    merged, stats = merge_facts(existing, incoming)
    assert merged == ["阿明的生日是4月1日"]
    assert stats["conflicts_resolved"] == 1


def test_merge_facts_truncates_to_limit() -> None:
    incoming = [f"关于主题{chr(0x4e00 + i)}的独特事实" for i in range(120)]
    merged, stats = merge_facts([], incoming)
    assert len(merged) == MAX_MEMORY
    assert stats["truncated"] == 120 - MAX_MEMORY


def test_detect_conflicts_flags_similar_but_different() -> None:
    pairs = detect_conflicts(["阿明的生日是3月5日", "阿明的生日是4月1日", "小红喜欢画画"])
    assert any("3月5日" in a and "4月1日" in b for a, b in pairs)


def test_similarity_bounds() -> None:
    assert similarity("完全一样的事实", "完全一样的事实") == 1.0
    assert similarity("甲", "乙") < 0.5
