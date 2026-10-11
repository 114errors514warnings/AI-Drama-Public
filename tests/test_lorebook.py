"""V4：世界观词条（Lorebook）——front matter 触发 / 常驻 / 选择。"""
from __future__ import annotations

from backend.lorebook import (
    constant_entries,
    load_entries,
    parse_entry,
    render_entries,
    select_entries,
)

SELECTIVE = """---
keys: [社团, 组织, 学生会]
priority: 10
---
社团活动都在放学后。
"""

CONSTANT = """---
constant: true
priority: 5
---
这是一所普通的城市高中。
"""


def test_parse_entry_front_matter() -> None:
    e = parse_entry(SELECTIVE, title="社团")
    assert e.keys == ["社团", "组织", "学生会"]
    assert e.priority == 10
    assert e.selective is True
    assert "社团活动" in e.content
    assert e.matches("他去了社团") is True
    assert e.matches("今天天气不错") is False


def test_constant_entry_always_matches() -> None:
    e = parse_entry(CONSTANT, title="世界观")
    assert e.constant is True
    assert e.selective is False
    assert e.matches("任意文本") is True


def test_select_entries_prefers_constant_then_hits() -> None:
    entries = [parse_entry(CONSTANT, "世界观"), parse_entry(SELECTIVE, "社团")]
    picked = select_entries(entries, "聊聊社团活动", limit=2)
    assert any(e.title == "世界观" for e in picked)
    assert any(e.title == "社团" for e in picked)


def test_no_keys_not_selective() -> None:
    e = parse_entry("普通背景资料", title="背景")
    assert e.selective is False
    assert e.matches("普通背景资料") is False


def test_load_and_render(tmp_path) -> None:
    d = tmp_path / "World" / "词条"
    d.mkdir(parents=True)
    (d / "社团.md").write_text(SELECTIVE, encoding="utf-8")
    (d / "世界观.md").write_text(CONSTANT, encoding="utf-8")
    entries = load_entries(sorted(d.glob("*.md")))
    assert len(entries) == 2
    assert len(constant_entries(entries)) == 1
    assert "社团活动" in render_entries(entries)
