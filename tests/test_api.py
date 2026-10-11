"""API 冒烟：会话创建 / 指标 / 每轮明细 / 导出 / 记忆治理接口。"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.eval.replay import _make_kb


def _client(tmp_path, monkeypatch) -> TestClient:
    from backend import main as main_mod

    sessions = Path(tmp_path) / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(main_mod.manager, "sessions_root", sessions)
    main_mod.manager.sessions.clear()
    main_mod.manager.active_id = None
    return TestClient(main_mod.app)


def test_session_lifecycle_and_metrics(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    kb = _make_kb(Path(tmp_path))

    created = client.post("/api/sessions", json={"name": "回归会话", "kb_path": str(kb)})
    assert created.status_code == 200, created.text
    sid = created.json()["id"]

    metrics = client.get(f"/api/sessions/{sid}/metrics")
    assert metrics.status_code == 200
    body = metrics.json()
    assert body["turns_total"] == 0
    assert body["offscreen_leak_count"] == 0
    assert "gates" in body

    turns = client.get(f"/api/sessions/{sid}/turns").json()
    assert turns["turns"] == []


def test_export_endpoints(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    kb = _make_kb(Path(tmp_path))
    sid = client.post("/api/sessions", json={"name": "导出会话", "kb_path": str(kb)}).json()["id"]

    markdown = client.get(f"/api/sessions/{sid}/export?format=md")
    assert markdown.status_code == 200
    assert markdown.text.startswith("#")
    assert "世界观" in markdown.text or "导出会话" in markdown.text

    payload = client.get(f"/api/sessions/{sid}/export?format=json").json()
    assert payload["session"]["id"] == sid
    assert "transcript" in payload and "agents" in payload


def test_frontend_exposes_observability_tab(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    html = client.get("/").text
    assert 'data-tab="observe"' in html
    assert 'id="obs-metrics"' in html
    assert 'id="obs-turns"' in html
    assert 'id="btn-obs-judge"' in html


def test_judge_endpoint_returns_observation(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    kb = _make_kb(Path(tmp_path))
    sid = client.post("/api/sessions", json={"name": "裁判会话", "kb_path": str(kb)}).json()["id"]

    # 无可用 key 时，裁判应降级为观察项（value=None）而非 5xx
    response = client.post(f"/api/sessions/{sid}/judge")
    assert response.status_code == 200
    body = response.json()
    assert body["observation"] is True
    assert body["in_gates"] is False
    assert body["metric"] == "persona_consistency"


def test_memory_endpoint_uses_dedupe_and_conflict_resolution(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    kb = _make_kb(Path(tmp_path))
    sid = client.post("/api/sessions", json={"name": "记忆会话", "kb_path": str(kb)}).json()["id"]

    response = client.put(
        f"/api/sessions/{sid}/character/memory?name=阿明",
        json={"long_memory": ["阿明认识小红", "阿明认识小红", "", "小红是班长"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["long_memory"] == ["阿明认识小红", "小红是班长"]
    assert body["stats"]["deduped"] >= 1
