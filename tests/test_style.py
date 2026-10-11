"""V4：文风工具（反 AI 腔词表 / 动作对白切分 / 文本规范化）。"""
from __future__ import annotations

from backend.style import (
    ANTI_AI_WORDS,
    ai_flavor_hit_rate,
    find_ai_flavor,
    normalize_for_display,
    split_action_dialogue,
)


def test_find_ai_flavor_counts_words() -> None:
    hits = find_ai_flavor("他不禁轻轻地叹了口气，仿佛整个世界都安静了。")
    assert hits.get("不禁") == 1
    assert "轻轻" not in hits  # 词表为「轻轻地」，不做子串误判
    assert "仿佛" in hits


def test_ai_flavor_hit_rate_scales_with_length() -> None:
    assert ai_flavor_hit_rate("") == 0.0
    rate = ai_flavor_hit_rate("不禁" * 1000)
    assert rate > 0


def test_anti_ai_words_unique_and_nonempty() -> None:
    assert len(ANTI_AI_WORDS) == len(set(ANTI_AI_WORDS))
    assert all(w.strip() for w in ANTI_AI_WORDS)


def test_split_action_dialogue() -> None:
    parts = split_action_dialogue("（把书合上）今天不去了。")
    assert parts[0][0] == "action" and "把书合上" in parts[0][1]
    assert any(k == "dialogue" and "今天不去了" in c for k, c in parts)


def test_split_action_dialogue_handles_halfwidth() -> None:
    kinds = [k for k, _ in split_action_dialogue("(笑了笑)嗯。")]
    assert kinds[0] == "action"


def test_normalize_for_display_collapses_blank_lines() -> None:
    assert normalize_for_display("a\r\n\n\n\nb\r") == "a\n\nb"
