"""V4：知识库结构化——排除写作辅助/评判标准、常驻世界观、词条触发、角色卡。"""
from __future__ import annotations

from pathlib import Path

from backend.knowledge_base import KnowledgeBase


def _kb(tmp_path: Path) -> KnowledgeBase:
    root = tmp_path / "kb"
    (root / "Character").mkdir(parents=True)
    (root / "Memory").mkdir(parents=True)
    (root / "World").mkdir(parents=True)
    return KnowledgeBase(root)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_meta_content_excluded_from_world(tmp_path) -> None:
    kb = _kb(tmp_path)
    w = kb.root / "World"
    _write(w / "写作辅助" / "Pipeline配置速查.md", "质量门禁 quality-gate 与 writer 修复流程")
    _write(w / "评判标准" / "文风评判标准.md", "H1 视角统一 S2 对话自然度")
    _write(w / "风格相关" / "文风分析总结.md", "繁复细腻，长句主导")
    _write(w / "设定合集" / "剧情大纲（仅供参考）" / "故事大纲.md", "大纲内容")
    _write(w / "背景" / "世界观.md", "这是一所普通的城市高中。")

    kb2 = KnowledgeBase(kb.root)
    constant = kb2.world_constant()
    assert "城市高中" in constant
    assert "quality-gate" not in constant
    assert "H1 视角统一" not in constant
    assert "文风分析总结" not in constant
    assert "大纲内容" not in constant
    # 散装检索语料同样排除
    joined = " ".join(str(f) for f in kb2.lore_files)
    assert "写作辅助" not in joined and "评判标准" not in joined


def test_world_scheme_enables_constant_and_entries(tmp_path) -> None:
    kb = _kb(tmp_path)
    w = kb.root / "World"
    _write(w / "背景" / "世界观.md", "学校分为三个年级。")
    _write(w / "词条" / "社团.md", "---\nkeys: [社团, 学生会]\n---\n社团活动都在放学后。")
    _write(w / "设定合集" / "常识" / "城市.md", "这座城市分为上下两城。")

    kb2 = KnowledgeBase(kb.root)
    assert kb2.has_world_scheme is True
    constant = kb2.world_constant()
    assert "三个年级" in constant
    # 已启用结构化：散装常识不进常驻
    assert "上下两城" not in constant
    # 关键词命中才注入
    assert "社团活动" in kb2.match_lore("我想说说社团活动的事")
    assert "社团活动" not in kb2.match_lore("今天天气怎么样")


def test_legacy_kb_falls_back_to_all_lore(tmp_path) -> None:
    kb = _kb(tmp_path)
    w = kb.root / "World"
    _write(w / "设定合集" / "常识" / "城市.md", "这座城市分为上下两城。")
    _write(w / "设定合集" / "常识" / "势力.md", "共有三方势力。")

    kb2 = KnowledgeBase(kb.root)
    assert kb2.has_world_scheme is False
    constant = kb2.world_constant()
    assert "上下两城" in constant and "三方势力" in constant


def test_get_character_card(tmp_path) -> None:
    kb = _kb(tmp_path)
    _write(kb.root / "Character" / "A.md",
           "# A\n\n## 性格核心\n外冷内热。\n\n## 语言风格\n每句 ≤ 25 字。\n")
    card = KnowledgeBase(kb.root).get_character_card("A")
    assert card is not None
    assert card.structured is True
    assert "每句 ≤ 25 字" in card.style
