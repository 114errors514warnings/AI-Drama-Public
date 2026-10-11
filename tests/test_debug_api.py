"""V4：调试/自检接口（TODO-4：群聊编排 + 单 Agent 系统 Agent 对话）。

覆盖：
- 群聊模式：预览导演规划消息（不调 LLM）/ dry-run 真调用一次（不写状态）
- 单 Agent：构建消息、提示词是否强制 JSON、dry-run 对话、场外记录隔离
- 上下文自检：场外单聊未被群聊规划引用
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.eval.fake_llm import FakeLLM
from backend.eval.replay import _make_kb

from conftest import make_session


# ---------- 直接调用（FakeLLM，确定性） ----------
def test_preview_group_plan_excludes_side_chat(tmp_path) -> None:
    session = make_session(tmp_path, FakeLLM(), mode="off")
    session.side_chats["导演"] = [
        {"role": "user", "content": "先确认一下出场角色白名单"},
        {"role": "assistant", "speaker": "导演", "content": "白名单：A、B"},
    ]
    pv = session.director.preview_group_plan("推进剧情")
    assert pv["system_prompt_requires_json"] is True
    assert "只输出导演规划 JSON" in pv["system_prompt"]
    assert pv["side_chat_included"] is False
    # TODO-4 现象2：场外单聊内容不得出现在群聊规划消息里
    joined = "\n".join(m["content"] for m in pv["messages"])
    assert "白名单：A、B" not in joined
    assert pv["messages"][0]["role"] == "system"
    assert pv["messages"][-1]["content"].endswith("请只输出导演规划 JSON。")


def test_run_group_plan_does_not_mutate_state(tmp_path) -> None:
    session = make_session(tmp_path, FakeLLM(), mode="off")
    transcript_before = list(session.transcript)
    events_before = list(session.world.events)
    result = session.director.run_group_plan("推进剧情")
    assert result["ok"] is True
    assert result["output_is_json"] is True
    assert isinstance(result["plan"], dict) and "narration" in result["plan"]
    assert session.transcript == transcript_before
    assert session.world.events == events_before


def test_build_agent_messages_director_prompt_requires_json(tmp_path) -> None:
    session = make_session(tmp_path, FakeLLM(), mode="off")
    agent = session.registry.get("导演")
    msgs = session.director.build_agent_messages(agent, "我们接下来怎么写")
    assert msgs[0]["role"] == "system"
    # TODO-4 现象1 的根因：导演的单聊也沿用了"只输出 JSON"的提示词
    assert "只输出导演规划 JSON" in msgs[0]["content"]
    assert msgs[-1]["content"] == "我们接下来怎么写"


def test_agent_turn_dry_run_then_commit(tmp_path) -> None:
    session = make_session(tmp_path, FakeLLM(), mode="off")
    dry = session.director.run_agent_turn("导演", "聊聊剧情结构", commit=False)
    assert dry["committed"] is False
    assert session.side_chats.get("导演", []) == []
    # FakeLLM 按导演提示词返回规划 JSON —— 复现"回复意义不明"
    assert dry["reply"].lstrip().startswith("{")
    assert dry["system_prompt_requires_json"] is True

    real = session.director.run_agent_turn("导演", "聊聊剧情结构", commit=True)
    assert real["committed"] is True
    assert len(session.side_chats["导演"]) == 2


def test_agent_turn_supports_functional_agents(tmp_path) -> None:
    session = make_session(tmp_path, FakeLLM(), mode="off")
    # JSON 型：导演/世界/记忆管理；非 JSON 型：梗概（输出正文）
    expect_json = {"导演": True, "世界": True, "记忆管理": True, "梗概": False}
    for name, exp in expect_json.items():
        r = session.director.run_agent_turn(name, "自检", commit=False)
        assert "error" not in r, r
        assert r["speaker"] == name
        assert r["system_prompt_requires_json"] is exp


def test_debug_context_reports_side_chats_not_used(tmp_path) -> None:
    session = make_session(tmp_path, FakeLLM(), mode="off")
    session.side_chats["导演"] = [{"role": "user", "content": "x"}]
    ctx = session.director.debug_context("导演")
    assert ctx["side_chats_used_in_group_plan"] is False
    assert ctx["side_chats"] == {"导演": 1}
    assert ctx["agent"]["name"] == "导演"
    assert ctx["director"]["name"] == "导演"


# ---------- HTTP 接口 ----------
def _client(tmp_path, monkeypatch) -> TestClient:
    from backend import main as main_mod

    sessions = Path(tmp_path) / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(main_mod.manager, "sessions_root", sessions)
    monkeypatch.setattr(main_mod.manager, "llm", FakeLLM())   # 避免真实 LLM 调用
    main_mod.manager.sessions.clear()
    main_mod.manager.active_id = None
    return TestClient(main_mod.app)


def test_debug_http_endpoints(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    kb = _make_kb(Path(tmp_path))
    sid = client.post("/api/sessions", json={"name": "调试会话", "kb_path": str(kb)}).json()["id"]

    # 群聊：预览（不调 LLM）
    pv = client.get(f"/api/sessions/{sid}/debug/group/preview", params={"message": "推进"}).json()
    assert pv["system_prompt_requires_json"] is True
    assert pv["messages"][0]["role"] == "system"

    # 群聊：dry-run 真调用
    plan = client.post(f"/api/sessions/{sid}/debug/group/plan", json={"message": "推进"}).json()
    assert plan["output_is_json"] is True and plan["ok"] is True

    # 单 Agent：系统 Agent 全可测（梗概输出正文，不强制 JSON）
    expect_json = {"导演": True, "世界": True, "记忆管理": True, "梗概": False}
    for name, exp in expect_json.items():
        resp = client.get(f"/api/sessions/{sid}/debug/agent/messages",
                          params={"agent_name": name, "message": "你好"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["messages"][-1]["content"] == "你好"
        assert body["system_prompt_requires_json"] is exp, name

    # 单聊 dry-run 不写场外记录
    turn = client.post(f"/api/sessions/{sid}/debug/agent/turn",
                       json={"agent_name": "导演", "message": "聊聊"}).json()
    assert turn["committed"] is False
    assert turn["system_prompt_requires_json"] is True
    assert client.get(f"/api/sessions/{sid}/debug/context").json()["side_chats"] == {}

    # 提交后 context 可见，再清空
    client.post(f"/api/sessions/{sid}/debug/agent/turn",
                json={"agent_name": "导演", "message": "聊聊", "commit": True})
    assert client.get(f"/api/sessions/{sid}/debug/context").json()["side_chats"]["导演"] == 2
    cleared = client.delete(f"/api/sessions/{sid}/debug/side-chats").json()
    assert cleared["side_chats"] == {}


def test_debug_agent_messages_404_for_unknown(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    kb = _make_kb(Path(tmp_path))
    sid = client.post("/api/sessions", json={"name": "调试会话2", "kb_path": str(kb)}).json()["id"]
    resp = client.get(f"/api/sessions/{sid}/debug/agent/messages",
                      params={"agent_name": "不存在的角色", "message": "hi"})
    assert resp.status_code == 404
