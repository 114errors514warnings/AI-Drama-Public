"""DeepSeek（OpenAI 兼容接口）客户端。"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .config import Config


class LLMError(RuntimeError):
    pass


def extract_json(text: str) -> Any:
    """鲁棒地从 LLM 输出中提取 JSON。"""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    raise LLMError(f"无法解析 LLM 返回的 JSON: {text[:200]}")


class LLMClient:
    """OpenAI 兼容聊天补全封装（可插拔：换 base_url + model + key 即可接入其他后端）。"""

    def __init__(self, config: Config, provider: str | None = None):
        self.config = config
        self.provider = provider
        # 最近一次调用的用量与模型名（供导演做「每轮 token」计量；本地单会话顺序调用，无并发歧义）
        self.last_usage: dict = {}
        self.last_model: str = ""

    def _connection(self) -> tuple[str, str, str]:
        """返回 (base_url, api_key, model)；provider 命中则覆盖主配置。"""
        return self.config.resolve_llm(self.provider)

    @staticmethod
    def _chat_url(base_url: str) -> str:
        return base_url.rstrip("/") + "/chat/completions"

    def usage_tokens(self) -> tuple[int, int]:
        """返回 (prompt_tokens, completion_tokens)，无用量时返回 (0, 0)。"""
        usage = self.last_usage or {}
        prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        completion = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        return prompt, completion

    def chat(self, messages: list[dict], temperature: float | None = None,
             json_mode: bool = False, max_tokens: int | None = None,
             attempts: int = 2, top_p: float | None = None,
             frequency_penalty: float | None = None,
             presence_penalty: float | None = None) -> str:
        base_url, api_key, model = self._connection()
        if not api_key:
            raise LLMError("API Key 未加载，无法调用模型。请检查 config 文件。")
        cfg = self.config
        payload_top_p = cfg.top_p if top_p is None else top_p
        payload_freq = cfg.frequency_penalty if frequency_penalty is None else frequency_penalty
        payload_pres = cfg.presence_penalty if presence_penalty is None else presence_penalty
        last_err: Exception | None = None
        for _ in range(attempts):
            try:
                payload: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "temperature": cfg.temperature if temperature is None else temperature,
                    "stream": False,
                }
                # V4：采样参数（去 AI 腔）；json_mode 时不加（JSON 输出需要更确定）
                if not json_mode:
                    if payload_top_p is not None:
                        payload["top_p"] = payload_top_p
                    if payload_freq is not None:
                        payload["frequency_penalty"] = payload_freq
                    if payload_pres is not None:
                        payload["presence_penalty"] = payload_pres
                if json_mode:
                    payload["response_format"] = {"type": "json_object"}
                if max_tokens:
                    payload["max_tokens"] = max_tokens
                resp = httpx.post(
                    self._chat_url(base_url),
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=180,
                )
                resp.raise_for_status()
                data = resp.json()
                self.last_usage = data.get("usage") or {}
                self.last_model = str(data.get("model") or model)
                return data["choices"][0]["message"]["content"].strip()
            except Exception as exc:  # noqa: BLE001
                last_err = exc
        raise LLMError(f"DeepSeek 调用失败: {last_err}")

    def chat_json(self, messages: list[dict], temperature: float | None = None,
                  max_tokens: int | None = None) -> Any:
        raw = self.chat(messages, temperature=temperature,
                        json_mode=True, max_tokens=max_tokens)
        try:
            return extract_json(raw)
        except LLMError:
            # json_object 模式偶发返回空白/非 JSON，降级为普通模式重试（提示词仍要求输出 JSON）
            raw2 = self.chat(messages, temperature=temperature,
                             json_mode=False, max_tokens=max_tokens)
            return extract_json(raw2)

