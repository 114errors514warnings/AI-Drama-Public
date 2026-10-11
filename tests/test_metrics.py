"""评测指标：场外泄漏检测、门禁判定、会话汇总。"""
from __future__ import annotations

from backend.eval.fake_llm import FakeLLM
from backend.metrics import count_offscreen_leaks, evaluate_session_gates, session_metrics

from conftest import make_session


def test_count_offscreen_leaks_detects_bad_role() -> None:
    transcript = [{"role": "system", "content": "内部指令"}, {"role": "user", "content": "你好"}]
    assert count_offscreen_leaks(transcript) == 1


def test_count_offscreen_leaks_detects_marker() -> None:
    transcript = [{"role": "assistant", "speaker": "导演", "content": "调度备忘：让阿明出场"}]
    assert count_offscreen_leaks(transcript) == 1


def test_count_offscreen_leaks_clean_transcript() -> None:
    transcript = [
        {"role": "user", "content": "开始吧"},
        {"role": "narrator", "speaker": "导演", "content": "夜幕降临。"},
        {"role": "assistant", "speaker": "阿明", "content": "好的。"},
    ]
    assert count_offscreen_leaks(transcript) == 0


def test_evaluate_gates() -> None:
    verdicts = evaluate_session_gates({
        "offscreen_leak_count": 0,
        "agent_orchestration_success_rate": 1.0,
        "world_violation_rate": 0.03,
        "timeline_issues": 0,
        "world_leak_from_excluded": 0,
    })
    assert verdicts == {
        "offscreen_leak_count": "PASS",
        "agent_orchestration_success_rate": "PASS",
        "world_violation_rate": "PASS",
        "timeline_issues": "PASS",
        "world_leak_from_excluded": "PASS",
    }


def test_evaluate_gates_fail() -> None:
    verdicts = evaluate_session_gates({
        "offscreen_leak_count": 1,
        "agent_orchestration_success_rate": 0.5,
        "world_violation_rate": 0.4,
        "timeline_issues": 2,
        "world_leak_from_excluded": 1,
    })
    assert set(verdicts.values()) == {"FAIL"}


def test_memory_usage_rate_proxy(tmp_path) -> None:
    """观察项：有长期记忆的角色发言与记忆有词面重叠即计入。"""
    session = make_session(tmp_path, FakeLLM(), mode="off")
    agent = session.runtime.create_agent("阿明")
    agent.long_memory = ["阿明认识小红"]
    session.transcript = [
        {"role": "assistant", "speaker": "阿明", "content": "我记得小红是我的同学。"},
        {"role": "assistant", "speaker": "阿明", "content": "天气不错。"},
    ]
    from backend.metrics import memory_usage_rate
    assert memory_usage_rate(session) == 0.5
    assert memory_usage_rate(session) is not None


def test_session_metrics_from_turns(tmp_path) -> None:
    session = make_session(tmp_path, FakeLLM())
    session.memory.append_turn({"ok": True, "world_issues": 0, "latency_ms": 10, "prompt_tokens": 5, "completion_tokens": 5})
    session.memory.append_turn({"ok": False, "world_issues": 1, "world_corrected": True, "latency_ms": 30,
                                "prompt_tokens": 5, "completion_tokens": 5})
    metrics = session_metrics(session)
    assert metrics["turns_total"] == 2
    assert metrics["turns_completed"] == 1
    assert metrics["agent_orchestration_success_rate"] == 0.5
    assert metrics["world_violation_rate"] == 0.5
    assert metrics["world_correction_rate"] == 1.0
    assert metrics["avg_tokens_per_turn"] == 10
    assert metrics["gates"]["offscreen_leak_count"] == "PASS"
    assert metrics["gates"]["agent_orchestration_success_rate"] == "FAIL"
    assert metrics["gates"]["timeline_issues"] == "PASS"


def test_count_excluded_lore_leaks() -> None:
    from backend.metrics import count_excluded_lore_leaks
    assert count_excluded_lore_leaks("这是一所普通高中。") == 0
    assert count_excluded_lore_leaks("Pipeline 配置速查：质量门禁 quality-gate") >= 2


def test_transcript_ai_flavor_rate(tmp_path) -> None:
    from backend.metrics import transcript_ai_flavor
    session = make_session(tmp_path, FakeLLM(), mode="off")
    session.transcript = [
        {"role": "assistant", "speaker": "阿明", "content": "他不禁轻轻地叹了口气，仿佛整个世界都安静了。"},
        {"role": "user", "content": "你怎么了"},
    ]
    stats = transcript_ai_flavor(session)
    assert stats["ai_flavor_hits"] >= 3
    assert stats["ai_flavor_rate"] > 0


def test_example_injected_ratio(tmp_path) -> None:
    from backend.metrics import example_injected_ratio
    session = make_session(tmp_path, FakeLLM(), mode="off")
    agent = session.runtime.create_agent("阿明")
    assert example_injected_ratio(session) == 0.0
    agent.system_prompt = "# 你说话的示例\n<START>\n阿明：嗯。"
    assert example_injected_ratio(session) == 1.0


def test_world_leak_gate_present(tmp_path) -> None:
    from backend.metrics import GATES
    assert GATES["world_leak_from_excluded"]["value"] == 0
    session = make_session(tmp_path, FakeLLM(), mode="off")
    assert session_metrics(session)["gates"]["world_leak_from_excluded"] == "PASS"
