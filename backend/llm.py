"""可插拔 LLM 工厂（V3）。

统一从 `create_llm` 构造 LLM 客户端，便于：
- 切换到任意 OpenAI 兼容后端（DeepSeek / Kimi / 本地模型…）；
- 在测试与离线回放中注入 `FakeLLM`（只要满足 `LLMProtocol`）。
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .llm_client import LLMClient


@runtime_checkable
class LLMProtocol(Protocol):
    """导演/记忆/梗概等只依赖这些成员。"""

    last_usage: dict

    def chat(self, messages: list[dict], temperature: float | None = ...,
             json_mode: bool = ..., max_tokens: int | None = ..., attempts: int = ...) -> str: ...

    def chat_json(self, messages: list[dict], temperature: float | None = ...,
                  max_tokens: int | None = ...) -> Any: ...


def create_llm(config, provider: str | None = None) -> LLMClient:
    """按配置构造 LLM 客户端；provider 命中则使用该后端覆盖主配置。"""
    return LLMClient(config, provider=provider)
