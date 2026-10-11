"""会话 / 世界观隔离与场外不变量（硬断言）。"""
from __future__ import annotations

from pathlib import Path

from backend.eval.fake_llm import FakeLLM
from backend.metrics import count_offscreen_leaks
from backend.session import WorldSession

from conftest import make_config, make_session


def _session(tmp_path, code: str, llm=None) -> WorldSession:
    from backend.eval.replay import _make_kb
    kb = _make_kb(Path(tmp_path) / code)
    return WorldSession(f"s-{code}", f"会话{code}", str(kb), llm or FakeLLM(),
                        Path(tmp_path) / code / "sessions", make_config("off"))


def test_agents_do_not_leak_between_sessions(tmp_path) -> None:
    a = _session(tmp_path, "a")
    b = _session(tmp_path, "b")

    a.runtime.create_agent("阿明")
    assert a.registry.get("阿明") is not None
    assert b.registry.get("阿明") is None

    a.registry.get("阿明").long_memory.append("A 世界专属记忆")
    assert "A 世界专属记忆" not in (b.registry.get("阿明").long_memory if b.registry.get("阿明") else [])


def test_memory_stores_are_separate(tmp_path) -> None:
    a = _session(tmp_path, "a")
    b = _session(tmp_path, "b")
    assert a.memory.char_dir != b.memory.char_dir
    a.runtime.create_agent("阿明")
    assert not (b.memory.char_dir / "阿明.json").exists()


def test_world_state_is_per_session(tmp_path) -> None:
    a = _session(tmp_path, "a")
    b = _session(tmp_path, "b")
    a.world.try_set_date("2030-01-01")
    a.world.location = "A 城"
    assert b.world.date != "2030-01-01"
    assert b.world.location != "A 城"


def test_offscreen_never_enters_transcript(tmp_path) -> None:
    from backend.eval.fake_llm import FakeLLM as F
    llm = F(world_issue_script=[["违规"], []])
    session = make_session(tmp_path, llm, mode="enforce")
    session.runtime.create_agent("阿明")
    session.director.run_group_turn("开始")
    session.director.run_agent_turn("阿明", "场外私聊")
    session.director.world_check("事件", "旁白", ["阿明"])

    assert count_offscreen_leaks(session.transcript) == 0
    roles = {m.get("role") for m in session.transcript}
    assert roles <= {"user", "narrator", "assistant"}
