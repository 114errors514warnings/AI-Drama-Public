"""V4：配置可移植性——无本地 Key 文件也能启动，环境变量优先。"""
from __future__ import annotations

from backend.config import Config


def test_config_without_key_file_does_not_fail(tmp_path) -> None:
    """他人部署：不提供任何本地 Key 文件时，不应启动失败。"""
    cfg = Config(api_key_file="", strict=True, data_dir=tmp_path)
    assert cfg.api_key == ""
    assert cfg.error == ""
    assert cfg.config_file == tmp_path / "config.json"


def test_env_overrides_config(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AIDRAMA_API_KEY", "sk-test-123456")
    monkeypatch.setenv("AIDRAMA_BASE_URL", "https://example.com/v1/")
    monkeypatch.setenv("AIDRAMA_MODEL", "my-model")
    cfg = Config(api_key_file="", strict=True, data_dir=tmp_path)
    assert cfg.api_key == "sk-test-123456"
    assert cfg.base_url == "https://example.com/v1"
    assert cfg.model == "my-model"
    assert cfg.masked_key() == "sk-tes…3456"


def test_data_dir_from_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AIDRAMA_DATA_DIR", str(tmp_path / "d"))
    cfg = Config(api_key_file="", strict=True)
    assert cfg.data_dir == tmp_path / "d"
    assert cfg.config_file == tmp_path / "d" / "config.json"
