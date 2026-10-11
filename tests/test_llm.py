"""可插拔 LLM：provider 解析、工厂、请求路由、以及 /api/config 的安全暴露。"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.config import Config
from backend.llm import LLMProtocol, create_llm
from backend.llm_client import LLMClient


def _config(tmp_path) -> Config:
    cfg = Config(api_key_file=str(Path(tmp_path) / "missing.md"), strict=False, data_dir=tmp_path)
    cfg.base_url = "https://main.test"
    cfg.api_key = "main-key"
    cfg.model = "main-model"
    cfg.llm_providers = {
        "kimi": {"base_url": "https://kimi.test", "api_key": "kimi-key", "model": "kimi-8k"},
    }
    return cfg


def test_resolve_llm_override_and_fallback(tmp_path) -> None:
    cfg = _config(tmp_path)
    assert cfg.resolve_llm("kimi") == ("https://kimi.test", "kimi-key", "kimi-8k")
    assert cfg.resolve_llm("unknown") == ("https://main.test", "main-key", "main-model")
    assert cfg.resolve_llm(None) == ("https://main.test", "main-key", "main-model")
    cfg.provider = "kimi"
    assert cfg.resolve_llm() == ("https://kimi.test", "kimi-key", "kimi-8k")
    assert cfg.provider_names() == ["kimi"]


def test_update_cleans_providers_and_resets_provider(tmp_path) -> None:
    cfg = _config(tmp_path)
    cfg.update(llm_providers={"a": {"base_url": "u", "api_key": "k", "model": "m"}},
               provider="a", persist=False)
    assert cfg.provider == "a"
    cfg.update(llm_providers={}, provider="a", persist=False)
    assert cfg.provider == ""            # provider 已不存在 → 复位


def test_create_llm_satisfies_protocol(tmp_path) -> None:
    client = create_llm(_config(tmp_path), provider="kimi")
    assert isinstance(client, LLMClient)
    assert isinstance(client, LLMProtocol)
    assert client._connection() == ("https://kimi.test", "kimi-key", "kimi-8k")


def test_chat_uses_provider_endpoint_and_model(tmp_path, monkeypatch) -> None:
    captured: dict = {}

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "hi"}}], "model": "kimi-8k",
                    "usage": {"prompt_tokens": 3, "completion_tokens": 1}}

    def fake_post(url, headers=None, json=None, timeout=None):  # noqa: A002
        captured.update(url=url, headers=headers, payload=json)
        return _Resp()

    monkeypatch.setattr("backend.llm_client.httpx.post", fake_post)
    client = create_llm(_config(tmp_path), provider="kimi")
    assert client.chat([{"role": "user", "content": "x"}]) == "hi"
    assert captured["url"] == "https://kimi.test/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer kimi-key"
    assert captured["payload"]["model"] == "kimi-8k"
    assert client.last_model == "kimi-8k"
    assert client.usage_tokens() == (3, 1)


def test_config_api_exposes_providers_without_keys(tmp_path, monkeypatch) -> None:
    from backend import main as main_mod

    sessions = Path(tmp_path) / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(main_mod.manager, "sessions_root", sessions)
    monkeypatch.setattr(main_mod.config, "data_dir", Path(tmp_path))
    monkeypatch.setattr(main_mod.config, "config_file", Path(tmp_path) / "config.json")
    monkeypatch.setattr(main_mod.config, "llm_providers", {})
    monkeypatch.setattr(main_mod.config, "provider", "")

    client = TestClient(main_mod.app)
    response = client.post("/api/config", json={
        "provider": "kimi",
        "llm_providers": {"kimi": {"base_url": "https://kimi.test", "api_key": "secret",
                                   "model": "kimi-8k"}},
    })
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "kimi"
    providers = {p["name"]: p for p in body["providers"]}
    assert providers["kimi"]["base_url"] == "https://kimi.test"
    assert providers["kimi"]["key_loaded"] is True
    assert "api_key" not in providers["kimi"]          # 绝不返回原始 key
    assert "secret" not in response.text
