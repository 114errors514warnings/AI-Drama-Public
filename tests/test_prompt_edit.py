"""V4：提示词查看/编辑——手动覆盖（锁定不被重建）、重置、世界背景覆盖。"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.eval.fake_llm import FakeLLM
from backend.eval.replay import _make_kb

from conftest import make_session


def _client(tmp_path, monkeypatch) -> TestClient:
    from backend import main as main_mod

    sessions = Path(tmp_path) / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(main_mod.manager, "sessions_root", sessions)
    main_mod.manager.sessions.clear()
    main_mod.manager.active_id = None
    return TestClient(main_mod.app)


def test_set_prompt_locks_and_survives_refresh(tmp_path) -> None:
    session = make_session(tmp_path, FakeLLM(), mode="off")
    agent = session.runtime.create_agent("阿明")
    session.runtime.set_prompt(agent, "【自定义提示词】只准说一句话。", lock=True)
    # 记忆变更触发的自动重建不应覆盖手动编辑
    session.runtime.refresh_system_prompt(agent)
    assert agent.system_prompt == "【自定义提示词】只准说一句话。"
    assert agent.prompt_locked is True


def test_reset_prompt_restores_auto(tmp_path) -> None:
    session = make_session(tmp_path, FakeLLM(), mode="off")
    agent = session.runtime.create_agent("阿明")
    session.runtime.set_prompt(agent, "手动内容", lock=True)
    session.runtime.reset_prompt(agent)
    assert agent.prompt_locked is False
    assert "手动内容" not in agent.system_prompt
    assert "你是谁" in agent.system_prompt


def test_world_rules_override_effective(tmp_path) -> None:
    session = make_session(tmp_path, FakeLLM(), mode="off")
    assert session.world.effective_rules == session.world.rules
    session.world.rules_override = "【覆盖背景】这是一个测试世界。"
    assert session.world.effective_rules == "【覆盖背景】这是一个测试世界。"


def test_prompt_endpoints(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    kb = _make_kb(Path(tmp_path))
    sid = client.post("/api/sessions", json={"name": "提示词会话", "kb_path": str(kb)}).json()["id"]

    # 角色提示词覆盖
    r = client.put(f"/api/sessions/{sid}/agents/prompt",
                   json={"name": "阿明", "system_prompt": "【手改】阿明只说短句。", "lock": True})
    assert r.status_code == 200, r.text
    assert r.json()["prompt_locked"] is True

    detail = client.get(f"/api/sessions/{sid}/character?name=阿明").json()
    assert detail["system_prompt"] == "【手改】阿明只说短句。"
    assert detail["prompt_locked"] is True

    # 重置
    r2 = client.delete(f"/api/sessions/{sid}/agents/prompt?name=阿明")
    assert r2.status_code == 200
    assert r2.json()["prompt_locked"] is False
    assert "【手改】" not in r2.json()["system_prompt"]

    # 世界背景覆盖 + 撤销
    r3 = client.put(f"/api/sessions/{sid}/world/rules", json={"rules": "【覆盖】只有一条规则。"})
    assert r3.status_code == 200
    world = client.get(f"/api/sessions/{sid}/world").json()
    assert world["rules_override"] == "【覆盖】只有一条规则。"
    assert world["effective_rules"] == "【覆盖】只有一条规则。"

    r4 = client.delete(f"/api/sessions/{sid}/world/rules")
    assert r4.status_code == 200
    world2 = client.get(f"/api/sessions/{sid}/world").json()
    assert world2["rules_override"] == ""
