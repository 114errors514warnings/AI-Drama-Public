"""确定性 Fake LLM：离线回放群聊，不触网、不消耗 token。

它按 System Prompt 识别「导演规划 / 世界校验 / 记忆抽取 / 梗概 / 角色发言」五种调用，
用脚本化的响应保证可复现（固定种子等价物）。
"""
from __future__ import annotations

import json
import re
from typing import Any

CHARACTER_RE = re.compile(r"角色「(.+?)」")
DIRECTOR_MARK = "请只输出导演规划 JSON"
REVISION_MARK = "请据此修正你的规划"


class FakeLLM:
    def __init__(self,
                 director_plans: list[dict] | None = None,
                 revised_plan: dict | None = None,
                 world_issue_script: list[list[str]] | None = None,
                 memories_script: list[dict] | None = None,
                 judge_scores: list[float] | None = None,
                 flavor_scores: list[float] | None = None,
                 synopsis_template: str = "截至目前，{names}在{location}推进了剧情。") -> None:
        self.director_plans = director_plans or [self._default_plan()]
        self.revised_plan = revised_plan or self._default_plan(location="图书馆")
        self.world_issue_script = list(world_issue_script or [])
        self.memories_script = list(memories_script or [])
        self.judge_scores = list(judge_scores or [])
        self.flavor_scores = list(flavor_scores or [])
        self.synopsis_template = synopsis_template

        self.director_calls = 0
        self.normal_plan_calls = 0
        self.world_calls = 0
        self.memory_calls = 0
        self.judge_calls = 0
        self.flavor_calls = 0
        self.calls: list[dict] = []
        self.last_usage: dict = {"prompt_tokens": 0, "completion_tokens": 0}
        self.last_model = "fake-deepseek"

    # ---------- 工具 ----------
    @staticmethod
    def _default_plan(location: str = "教室") -> dict:
        return {
            "narration": f"众人在{location}聚拢，新的一幕开始了。",
            "participants": ["阿明", "小红"],
            "location": location,
            "date": "2026年9月1日",
            "time_of_day": "白天",
            "event": f"在{location}的日常",
        }

    @staticmethod
    def _system(messages: list[dict]) -> str:
        return str(messages[0].get("content", "")) if messages else ""

    @staticmethod
    def _last_user(messages: list[dict]) -> str:
        for m in reversed(messages):
            if m.get("role") == "user":
                return str(m.get("content", ""))
        return ""

    @staticmethod
    def _all_user(messages: list[dict]) -> str:
        return "\n".join(str(m.get("content", "")) for m in messages if m.get("role") == "user")

    def _kind(self, messages: list[dict]) -> str:
        system = self._system(messages)
        if "World Agent" in system:
            return "world"
        if "Memory Manager" in system:
            return "memory"
        if "Synopsis Agent" in system:
            return "synopsis"
        if "文风裁判" in system:
            return "flavor"
        if "评分裁判" in system:
            return "judge"
        if "导演 Agent（Director）" in system or DIRECTOR_MARK in self._all_user(messages):
            return "director"
        return "character"

    def _estimate_usage(self, messages: list[dict], output: str) -> None:
        self.last_usage = {
            "prompt_tokens": max(1, sum(len(str(m.get("content", ""))) for m in messages) // 4),
            "completion_tokens": max(1, len(output) // 4),
        }

    # ---------- LLM 接口 ----------
    def chat(self, messages: list[dict], temperature: float | None = None,
             json_mode: bool = False, max_tokens: int | None = None,
             attempts: int = 2, **_kwargs: Any) -> str:
        kind = self._kind(messages)
        if kind == "director":
            revision = REVISION_MARK in self._last_user(messages)
            self.director_calls += 1
            if revision:
                plan = dict(self.revised_plan)
            else:
                plan = dict(self.director_plans[self.normal_plan_calls % len(self.director_plans)])
                self.normal_plan_calls += 1
            # 让每轮事件随用户输入变化（贴近真实导演行为，避免逐字重复事件）
            snippet = re.sub(r"\s+", " ", self._last_user(messages)).strip()[:16]
            if snippet:
                plan["event"] = f"{plan.get('event', '')}｜{snippet}"
                plan["narration"] = f"{plan.get('narration', '')}（{snippet}）"
            output = json.dumps(plan, ensure_ascii=False)
        elif kind == "world":
            issues = self.world_issue_script[self.world_calls] if self.world_calls < len(self.world_issue_script) else []
            self.world_calls += 1
            output = json.dumps({"ok": not issues, "issues": issues}, ensure_ascii=False)
        elif kind == "memory":
            memories = self.memories_script[self.memory_calls] if self.memory_calls < len(self.memories_script) else []
            self.memory_calls += 1
            output = json.dumps({"memories": memories}, ensure_ascii=False)
        elif kind == "synopsis":
            match = CHARACTER_RE.search(self._system(messages))
            _ = match
            output = self.synopsis_template.format(names="阿明与小红", location="教室")
        elif kind == "judge":
            score = self.judge_scores[self.judge_calls % len(self.judge_scores)] if self.judge_scores else 0.9
            self.judge_calls += 1
            output = json.dumps({"score": score, "reason": "fake"}, ensure_ascii=False)
        elif kind == "flavor":
            score = self.flavor_scores[self.flavor_calls % len(self.flavor_scores)] if self.flavor_scores else 0.8
            self.flavor_calls += 1
            output = json.dumps({"score": score, "reason": "fake"}, ensure_ascii=False)
        else:
            match = CHARACTER_RE.search(self._system(messages))
            name = match.group(1) if match else "角色"
            output = f"{name}：好的，我明白了。"
        self._estimate_usage(messages, output)
        self.calls.append({"kind": kind, "output": output[:120]})
        return output

    def chat_json(self, messages: list[dict], temperature: float | None = None,
                  max_tokens: int | None = None, **_kwargs: Any) -> Any:
        return json.loads(self.chat(messages, temperature=temperature, json_mode=True, max_tokens=max_tokens))
