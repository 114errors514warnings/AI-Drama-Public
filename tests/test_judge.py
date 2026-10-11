"""LLM 裁判观察项：多采样取均值、非法输出降级、且永不进入硬门禁。"""
from __future__ import annotations

from backend.eval.fake_llm import FakeLLM
from backend.judge import judge_ai_flavor, judge_persona_consistency, judge_session
from backend.llm_client import LLMError

from conftest import make_session


def test_persona_consistency_averages_samples(tmp_path) -> None:
    llm = FakeLLM(judge_scores=[0.8, 0.9, 1.0])
    obs = judge_persona_consistency(llm, profile="阿明是理科生", speech="我来算一下", samples=3)
    assert obs.value == 0.9
    assert len(obs.samples) == 3
    assert obs.stdev is not None
    assert obs.model


class _BadLLM:
    last_usage: dict = {}
    last_model = "bad"

    def __init__(self, mode: str):
        self.mode = mode

    def chat_json(self, messages, temperature=None, max_tokens=None):
        if self.mode == "raise":
            raise LLMError("boom")
        return {"score": 2.0}      # 越界 → 非法


def test_invalid_judge_output_degrades_to_none() -> None:
    assert judge_persona_consistency(_BadLLM("bad"), "p", "s", samples=2).value is None
    assert judge_persona_consistency(_BadLLM("raise"), "p", "s", samples=2).value is None


def test_judge_session_is_observation_only(tmp_path) -> None:
    llm = FakeLLM(judge_scores=[0.9], flavor_scores=[0.8, 0.7])
    session = make_session(tmp_path, llm, mode="off")
    session.director.run_group_turn("大家聊聊。")

    result = judge_session(session, samples=2)
    assert result["observation"] is True
    assert result["in_gates"] is False
    assert result["value"] is not None
    assert result["characters"]
    assert result["ai_flavor"]["in_gates"] is False
    assert result["ai_flavor"]["value"] is not None


def test_judge_ai_flavor_degrades_to_none() -> None:
    assert judge_ai_flavor(_BadLLM("bad"), "某段发言", samples=2).value is None
    assert judge_ai_flavor(_BadLLM("raise"), "某段发言", samples=2).value is None


def test_judge_not_part_of_hard_gates(tmp_path) -> None:
    from backend.metrics import GATES
    assert "persona_consistency" not in GATES
    assert "judge" not in GATES
