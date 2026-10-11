"""全局配置：API Key / 模型 / 采样参数等。

配置优先级（后者覆盖前者）：
1. 内置默认值
2. `data/config.json`（UI 保存的配置）
3. **环境变量**：`AIDRAMA_API_KEY` / `AIDRAMA_BASE_URL` / `AIDRAMA_MODEL`
4. 可选的本地 Key 文件：环境变量 `AIDRAMA_API_KEY_FILE` 指向的文件（默认不读取）

安全约定：
- Key 只保存在内存中，绝不写入代码、日志、接口响应或前端。
- 对外只暴露掩码（如 sk-****…****）。
- UI 中设置的配置持久化到 `data/config.json`；他人部署推荐用环境变量，不必落盘。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# 可选的本地 Key 文件（默认不读取）：他人部署请用 UI 或环境变量 AIDRAMA_API_KEY 配置
DEFAULT_API_KEY_FILE = os.environ.get("AIDRAMA_API_KEY_FILE", "").strip()
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_TEMPERATURE = 0.7


class Config:
    """运行期全局配置。"""

    def __init__(self, api_key_file: str = DEFAULT_API_KEY_FILE, strict: bool = True,
                 data_dir: str | Path | None = None):
        self.api_key_file = api_key_file
        self.api_key: str = ""
        self.base_url: str = "https://api.deepseek.com"
        self.model: str = DEFAULT_MODEL
        self.temperature: float = DEFAULT_TEMPERATURE
        self.world_check: bool = False
        # 世界校验模式：off（关闭）/ advisory（仅记录，默认）/ enforce（校验不通过则反馈导演闭环修正）
        self.world_check_mode: str = "advisory"
        self.world_check_retries: int = 2
        # 可插拔 LLM：provider 名称 + 多后端配置（name -> {base_url, api_key, model}）
        self.provider: str = ""
        self.llm_providers: dict = {}
        # V4 采样参数（OpenAI 兼容）：去 AI 腔用
        self.top_p: float = 0.95
        self.frequency_penalty: float = 0.4
        self.presence_penalty: float = 0.2
        self.max_tokens: int = 600
        self.character_temperature: float = 1.0
        self.anti_ai_flavor: bool = True
        self.error: str = ""
        # 时间显示格式：date(年月日) / datetime(年月日+时段) / relative(第N天)
        self.time_format: str = "date"
        self.time_fallback: str = "时间未定"
        self.data_dir = Path(data_dir) if data_dir else (
            Path(os.environ["AIDRAMA_DATA_DIR"]) if os.environ.get("AIDRAMA_DATA_DIR", "").strip()
            else Path(__file__).resolve().parent.parent / "data")
        self.config_file = self.data_dir / "config.json"
        try:
            self.load()
        except Exception as exc:  # noqa: BLE001
            if strict:
                raise
            self.error = str(exc)
        self._apply_env()

    def _apply_env(self) -> None:
        """环境变量优先（容器 / 他人部署用，避免把密钥写进仓库）。"""
        api_key = os.environ.get("AIDRAMA_API_KEY", "").strip()
        base_url = os.environ.get("AIDRAMA_BASE_URL", "").strip()
        model = os.environ.get("AIDRAMA_MODEL", "").strip()
        if api_key:
            self.api_key = api_key
        if base_url:
            self.base_url = base_url.rstrip("/")
        if model:
            self.model = model

    @staticmethod
    def _read_json(p: Path):
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _write_json(p: Path, data) -> None:
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self) -> None:
        # 优先读取 UI 持久化的本地配置（data/config.json）
        local = self._read_json(self.config_file)
        if local:
            self.model = str(local.get("model", DEFAULT_MODEL) or DEFAULT_MODEL)
            self.temperature = float(local.get("temperature", DEFAULT_TEMPERATURE))
            self.world_check = bool(local.get("world_check", False))
            self.world_check_mode = str(local.get("world_check_mode", "advisory") or "advisory")
            self.world_check_retries = int(local.get("world_check_retries", 2) or 0)
            self.provider = str(local.get("provider", "") or "")
            providers = local.get("llm_providers")
            if isinstance(providers, dict):
                self.llm_providers = {str(k): dict(v) for k, v in providers.items() if isinstance(v, dict)}
            self.time_format = str(local.get("time_format", "date") or "date")
            self.time_fallback = str(local.get("time_fallback", "时间未定") or "时间未定")
            self.top_p = float(local.get("top_p", 0.95))
            self.frequency_penalty = float(local.get("frequency_penalty", 0.4))
            self.presence_penalty = float(local.get("presence_penalty", 0.2))
            self.max_tokens = int(local.get("max_tokens", 600) or 600)
            self.character_temperature = float(local.get("character_temperature", 1.0))
            self.anti_ai_flavor = bool(local.get("anti_ai_flavor", True))
            base = local.get("base_url")
            if base:
                self.base_url = str(base).strip().rstrip("/")
            key = local.get("api_key")
            if key:
                self.api_key = str(key).strip()
                return
        # 兜底：从**可选**的本地 Key 文件读取；未指定则跳过（由 UI / 环境变量配置）
        if not self.api_key_file:
            return
        p = Path(self.api_key_file)
        if not p.exists():
            raise FileNotFoundError(f"找不到 API Key 文件: {p}")
        text = p.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("sk-"):
                self.api_key = line
            elif line.lower().startswith("url:"):
                self.base_url = line.split(":", 1)[1].strip().rstrip("/")
        if not self.api_key:
            raise RuntimeError(f"在 {p} 中未找到 sk- 开头的 API Key")
        if not self.base_url:
            self.base_url = "https://api.deepseek.com"

    def update(self, model=None, temperature=None, world_check=None,
               base_url=None, api_key=None, time_format=None, time_fallback=None,
               world_check_mode=None, world_check_retries=None,
               provider=None, llm_providers=None,
               top_p=None, frequency_penalty=None, presence_penalty=None,
               max_tokens=None, character_temperature=None, anti_ai_flavor=None,
               persist: bool = True) -> None:
        if model is not None and str(model).strip():
            self.model = str(model).strip()
        if temperature is not None:
            self.temperature = max(0.0, min(2.0, float(temperature)))
        if world_check is not None:
            self.world_check = bool(world_check)
        if world_check_mode is not None and str(world_check_mode).strip() in ("off", "advisory", "enforce"):
            self.world_check_mode = str(world_check_mode).strip()
        if world_check_retries is not None:
            self.world_check_retries = max(0, min(5, int(world_check_retries)))
        if isinstance(llm_providers, dict):
            cleaned: dict = {}
            for name, cfg in llm_providers.items():
                if isinstance(cfg, dict):
                    cleaned[str(name)] = {
                        "base_url": str(cfg.get("base_url", "")).strip().rstrip("/"),
                        "api_key": str(cfg.get("api_key", "")).strip(),
                        "model": str(cfg.get("model", "")).strip(),
                    }
            self.llm_providers = cleaned
            if self.provider and self.provider not in cleaned:
                self.provider = ""
        if provider is not None:
            name = str(provider).strip()
            self.provider = name if (not name or name in self.llm_providers) else self.provider
        if base_url is not None and str(base_url).strip():
            self.base_url = str(base_url).strip().rstrip("/")
        if api_key is not None and str(api_key).strip():
            self.api_key = str(api_key).strip()
        if time_format is not None and str(time_format).strip():
            self.time_format = str(time_format).strip()
        if time_fallback is not None and str(time_fallback).strip():
            self.time_fallback = str(time_fallback).strip()
        if top_p is not None:
            self.top_p = max(0.0, min(1.0, float(top_p)))
        if frequency_penalty is not None:
            self.frequency_penalty = max(-2.0, min(2.0, float(frequency_penalty)))
        if presence_penalty is not None:
            self.presence_penalty = max(-2.0, min(2.0, float(presence_penalty)))
        if max_tokens is not None:
            self.max_tokens = max(64, min(4096, int(max_tokens)))
        if character_temperature is not None:
            self.character_temperature = max(0.0, min(2.0, float(character_temperature)))
        if anti_ai_flavor is not None:
            self.anti_ai_flavor = bool(anti_ai_flavor)
        if persist:
            self.save()

    def resolve_llm(self, provider: str | None = None) -> tuple[str, str, str]:
        """解析 (base_url, api_key, model)：provider 命中则覆盖主配置，否则用主配置。"""
        name = (provider if provider is not None else self.provider) or ""
        cfg = self.llm_providers.get(name) if name else None
        if isinstance(cfg, dict):
            return (
                str(cfg.get("base_url") or self.base_url).rstrip("/"),
                str(cfg.get("api_key") or self.api_key),
                str(cfg.get("model") or self.model),
            )
        return self.base_url, self.api_key, self.model

    def provider_names(self) -> list[str]:
        return sorted(self.llm_providers)

    def save(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._write_json(self.config_file, {
            "api_key": self.api_key,
            "base_url": self.base_url,
            "model": self.model,
            "temperature": self.temperature,
            "world_check": self.world_check,
            "world_check_mode": self.world_check_mode,
            "world_check_retries": self.world_check_retries,
            "provider": self.provider,
            "llm_providers": self.llm_providers,
            "time_format": self.time_format,
            "time_fallback": self.time_fallback,
            "top_p": self.top_p,
            "frequency_penalty": self.frequency_penalty,
            "presence_penalty": self.presence_penalty,
            "max_tokens": self.max_tokens,
            "character_temperature": self.character_temperature,
            "anti_ai_flavor": self.anti_ai_flavor,
        })

    def masked_key(self) -> str:
        if not self.api_key:
            return ""
        return self.api_key[:6] + "…" + self.api_key[-4:]

    def chat_url(self) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/v1"):
            return base + "/chat/completions"
        return base + "/chat/completions"

