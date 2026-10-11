"""导演：世界校验自动修正闭环、日期单调、调用图、场外隔离。"""
from __future__ import annotations

from backend.eval.fake_llm import FakeLLM
from backend.metrics import count_offscreen_leaks

from conftest import make_session


def test_enforce_mode_auto_corrects_violation(tmp_path) -> None:
    llm = FakeLLM(world_issue_script=[["地点不合理：深夜的教室不应有阳光"], []])
    session = make_session(tmp_path, llm, mode="enforce")
    result = session.director.run_group_turn("大家开始聊天。")

    assert result["world_corrected"] is True
    assert result["world_check_initial_issues"] == ["地点不合理：深夜的教室不应有阳光"]
    assert result["world_check_issues"] == []          # 修正后无问题
    assert result["location"] == "图书馆"               # 采纳了修正后的规划
    assert len(llm.world_issue_script) == 2


def test_advisory_mode_only_records(tmp_path) -> None:
    llm = FakeLLM(world_issue_script=[["地点不合理"]])
    session = make_session(tmp_path, llm, mode="advisory")
    result = session.director.run_group_turn("大家开始聊天。")

    assert result["world_corrected"] is False
    assert result["world_check_initial_issues"] == ["地点不合理"]
    assert llm.normal_plan_calls == 1


def test_date_never_goes_backwards(tmp_path) -> None:
    plans = [
        {"narration": "第一幕", "participants": ["阿明"], "location": "教室",
         "date": "2026年10月1日", "time_of_day": "白天", "event": "第一幕"},
        {"narration": "第二幕", "participants": ["阿明"], "location": "教室",
         "date": "2026年9月1日", "time_of_day": "白天", "event": "第二幕"},
    ]
    llm = FakeLLM(director_plans=plans)
    session = make_session(tmp_path, llm, mode="off")

    first = session.director.run_group_turn("第一轮")
    assert first["date_reverted"] is False
    assert first["date"] == "2026-10-01"

    second = session.director.run_group_turn("第二轮")
    assert second["date_reverted"] is True
    assert second["date"] == "2026-10-01"               # 保持不回退
    dates = [e["date"] for e in session.world.timeline]
    assert dates == sorted(dates)


def test_agent_call_graph_recorded(tmp_path) -> None:
    llm = FakeLLM(memories_script=[[{"role": "阿明", "fact": "阿明认识小红"}]])
    session = make_session(tmp_path, llm, mode="enforce")
    result = session.director.run_group_turn("开始")

    kinds = [call["kind"] for call in result["agent_calls"]]
    assert "director_plan" in kinds
    assert "character_reply" in kinds
    assert "memory_extract" in kinds
    assert all("duration_ms" in call and "ok" in call for call in result["agent_calls"])

    turns = session.memory.load_turns(10)
    assert turns and turns[-1]["llm_calls"] == len(result["agent_calls"])
    assert turns[-1]["ok"] is True


def test_world_check_feedback_is_offscreen(tmp_path) -> None:
    llm = FakeLLM(world_issue_script=[["问题一"], []])
    session = make_session(tmp_path, llm, mode="enforce")
    session.director.run_group_turn("开始")

    # 校验反馈、修正指令都不得写入转录
    assert count_offscreen_leaks(session.transcript) == 0
    joined = "\n".join(m.get("content", "") for m in session.transcript)
    assert "世界校验反馈" not in joined
    assert "请据此修正你的规划" not in joined


def test_side_chat_does_not_touch_transcript_or_memory(tmp_path) -> None:
    llm = FakeLLM()
    session = make_session(tmp_path, llm, mode="off")
    session.runtime.create_agent("阿明")
    before_memory = list(session.registry.get("阿明").long_memory)

    result = session.director.run_agent_turn("阿明", "你好呀")
    assert result["reply"]
    assert session.transcript == []                                  # 不进群聊转录
    assert session.registry.get("阿明").long_memory == before_memory  # 不抽取记忆
    assert session.side_chats["阿明"]
