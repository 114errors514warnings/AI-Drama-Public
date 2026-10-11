"""V4：结构化角色卡解析（对齐《人设提示词模板.md》，向后兼容自由文本）。"""
from __future__ import annotations

from backend.character_card import parse_character_card

STRUCTURED = """# A

## 性格核心
外冷内热，善良开朗。

## 关键标签
cheerful, gentle, struggles between duty and self-will

## 人物气质
外柔内刚。人前开朗，独处时才露出敏感与不安。

## 语言风格
- 每句 ≤ 25 字
- 口癖：无奈时「唉」

## 对话示例
<START>
用户：你今天怎么没精神？
A：（把书合上）……没什么，昨晚没睡好而已。
<START>
用户：骗人。
A：（笑了笑，别过头）真没有。
"""

FREEFORM = """# B

**身份：** 示例高中学生
**性格：** 沉默寡言，重情义。
"""


def test_structured_card_fields() -> None:
    card = parse_character_card(STRUCTURED, "A")
    assert card.structured is True
    assert "外冷内热" in card.personality_core
    assert "cheerful" in card.tags
    assert "外柔内刚" in card.temperament
    assert "每句 ≤ 25 字" in card.style
    assert len(card.examples_list()) == 2
    assert "外冷内热" in card.personality
    assert "外柔内刚" in card.description


def test_freeform_card_falls_back_to_description() -> None:
    card = parse_character_card(FREEFORM, "B")
    assert card.structured is False
    assert card.style == "" and card.examples == ""
    # 未结构化：description 退化为全文，保证与旧行为一致
    assert "沉默寡言" in card.description
    assert "沉默寡言" in card.raw


def test_front_matter_aliases() -> None:
    raw = "---\naliases: [小昕, 昕]\n---\n\n## 性格核心\n外冷内热。\n"
    card = parse_character_card(raw, "A")
    assert card.aliases == ["小昕", "昕"]
    assert card.structured is True


def test_to_dict_has_expected_keys() -> None:
    d = parse_character_card(STRUCTURED, "A").to_dict()
    for key in ("name", "personality", "description", "style", "examples", "structured"):
        assert key in d
