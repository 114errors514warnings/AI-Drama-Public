"""LLM 裁判（观察项）：人设一致率等主观指标。

严格约束（对齐《执行方案》§1.5 / §4.4）：
- **只作观察项，绝不进入硬门禁**（返回体显式 `in_gates=False`）；
- **多采样取均值**降低方差，并给出标准差；
- 裁判调用失败/输出非法时降级为 `None`（BASELINE），不影响主流程。
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from . import prompts
from .llm_client import LLMError


@dataclass
class JudgeObservation:
    metric: str
    value: float | None
    samples: list[float] = field(default_factory=list)
    model: str = ""

    @property
    def stdev(self) -> float | None:
        return round(statistics.pstdev(self.samples), 4) if len(self.samples) > 1 else None


def _score_from(data: Any) -> float | None:
    if not isinstance(data, dict):
        return None
    try:
        score = float(data.get("score"))
    except (TypeError, ValueError):
        return None
    if 0.0 <= score <= 1.0:
        return score
    return None


def judge_persona_consistency(llm, profile: str, speech: str,
                              emotion: str = "", relationships: dict | None = None,
                              samples: int = 3) -> JudgeObservation:
    """对单个角色的最近发言做「人设一致率」多采样评分。"""
    scores: list[float] = []
    model = ""
    for _ in range(max(1, int(samples))):
        try:
            data = llm.chat_json([
                {"role": "system", "content": prompts.build_judge_system_prompt()},
                {"role": "user", "content": prompts.build_judge_user(
                    profile, emotion, relationships or {}, speech)},
            ], max_tokens=200)
        except LLMError:
            continue
        score = _score_from(data)
        if score is not None:
            scores.append(score)
        model = getattr(llm, "last_model", "") or model
    value = round(sum(scores) / len(scores), 4) if scores else None
    return JudgeObservation("persona_consistency", value, scores, model)


def judge_ai_flavor(llm, speech: str, samples: int = 3) -> JudgeObservation:
    """对一段发言做「AI 腔」多采样评分（1=自然像真人，0=明显 AI 腔）。观察项。"""
    scores: list[float] = []
    model = ""
    for _ in range(max(1, int(samples))):
        try:
            data = llm.chat_json([
                {"role": "system", "content": prompts.build_flavor_judge_system_prompt()},
                {"role": "user", "content": prompts.build_flavor_judge_user(speech)},
            ], max_tokens=200)
        except LLMError:
            continue
        score = _score_from(data)
        if score is not None:
            scores.append(score)
        model = getattr(llm, "last_model", "") or model
    value = round(sum(scores) / len(scores), 4) if scores else None
    return JudgeObservation("ai_flavor_naturalness", value, scores, model)


def judge_session(session, samples: int = 3, max_characters: int = 3) -> dict:
    """对会话中最近有发言的角色做观察项评分（最多 max_characters 个角色）。"""
    last_speech: dict[str, str] = {}
    for message in session.transcript:
        if message.get("role") == "assistant" and message.get("speaker"):
            last_speech[message["speaker"]] = str(message.get("content", ""))

    per_character: list[dict] = []
    for agent in session.registry.list():
        if agent.role != "character":
            continue
        speech = last_speech.get(agent.name)
        if not speech:
            continue
        observation = judge_persona_consistency(
            session.llm, agent.profile, speech, agent.emotion_state, agent.relationships,
            samples=samples)
        per_character.append({
            "name": agent.name, "value": observation.value,
            "samples": observation.samples, "stdev": observation.stdev,
        })
        if len(per_character) >= max(1, int(max_characters)):
            break

    values = [c["value"] for c in per_character if c["value"] is not None]
    all_samples = [s for c in per_character for s in c["samples"]]

    # V4：文风裁判（AI 腔，观察项）——对参与评分角色的发言合并评分
    speeches = [last_speech[c["name"]] for c in per_character if last_speech.get(c["name"])]
    flavor = judge_ai_flavor(session.llm, "\n\n".join(speeches)[:2000], samples=samples) if speeches else None

    return {
        "observation": True,
        "in_gates": False,
        "metric": "persona_consistency",
        "value": round(sum(values) / len(values), 4) if values else None,
        "samples": all_samples,
        "stdev": round(statistics.pstdev(all_samples), 4) if len(all_samples) > 1 else None,
        "model": getattr(session.llm, "last_model", "") or "",
        "characters": per_character,
        "ai_flavor": None if flavor is None else {
            "observation": True,
            "in_gates": False,
            "metric": "ai_flavor_naturalness",
            "value": flavor.value,
            "samples": flavor.samples,
            "stdev": flavor.stdev,
            "note": "文风裁判观察项：1=完全像真人闲聊，0=明显 AI 腔；仅观察",
        },
        "note": "LLM 裁判观察项：多采样取均值，仅观察，不进入硬门禁",
    }
