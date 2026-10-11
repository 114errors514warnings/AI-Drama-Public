"""V4：提示词重构——结构化角色卡拼装、语言示例、语感、反 AI 腔约束。"""
from __future__ import annotations

from backend.character_card import parse_character_card
from backend.config import Config
from backend.prompts import (
    build_character_system_prompt,
    build_director_system_prompt,
    build_world_check_system_prompt,
)

CARD_MD = """# A

## 性格核心
外冷内热，善良开朗。

## 关键标签
cheerful, gentle

## 人物气质
外柔内刚。人前开朗，独处时才露出敏感与不安。

## 语言风格
- 每句 ≤ 25 字
- 口癖：无奈时「唉」

## 对话示例
<START>
用户：你今天怎么没精神？
A：（把书合上）……没什么，昨晚没睡好而已。
"""


def test_character_prompt_has_examples_style_and_anti_ai() -> None:
    card = parse_character_card(CARD_MD, "A")
    prompt = build_character_system_prompt(
        "A", card.raw, ["答应过要陪她去图书馆"], "示例世界", "这是一所普通高中。",
        card=card)
    assert "# 你是谁" in prompt
    assert "你说话的示例" in prompt
    assert "（把书合上）" in prompt
    assert "每句 ≤ 25 字" in prompt
    assert "外冷内热" in prompt and "外柔内刚" in prompt
    assert "避免这些词" in prompt
    assert "答应过要陪她去图书馆" in prompt


def test_character_prompt_legacy_fallback_when_no_card() -> None:
    prompt = build_character_system_prompt(
        "B", "身份：示例高中学生。性格：沉默寡言。", [], "示例世界", "世界规则")
    assert "沉默寡言" in prompt
    # 无结构化卡片：仍需有默认语感规范，且不出现"示例"小节
    assert "文风要求" in prompt
    assert "你说话的示例" not in prompt


def test_director_prompt_has_narration_style() -> None:
    prompt = build_director_system_prompt("示例世界", ["A", "B"], "规则", [])
    assert "旁白文风要求" in prompt
    assert "JSON" in prompt


def test_world_check_prompt_has_style_checks() -> None:
    prompt = build_world_check_system_prompt("示例世界", "规则")
    assert "视角越界" in prompt
    assert "AI 腔" in prompt


def test_config_sampling_fields_clamped(tmp_path) -> None:
    cfg = Config(api_key_file="nonexistent", strict=False, data_dir=tmp_path)
    cfg.update(top_p=5, frequency_penalty=-9, presence_penalty=9,
               max_tokens=99999, character_temperature=9, anti_ai_flavor=False)
    assert cfg.top_p == 1.0
    assert cfg.frequency_penalty == -2.0
    assert cfg.presence_penalty == 2.0
    assert cfg.max_tokens == 4096
    assert cfg.character_temperature == 2.0
    assert cfg.anti_ai_flavor is False
