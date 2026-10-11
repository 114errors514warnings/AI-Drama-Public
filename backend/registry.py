"""V2: Agent Registry —— 保存所有角色 Agent 实例。

每个角色拥有独立生命周期、独立记忆、独立状态（文档中的正确方案，
而不是"一个通用 Agent 切角色 Prompt"的错误方案）。
"""
from __future__ import annotations

from .agents import Agent


class AgentRegistry:
    def __init__(self):
        self._agents: dict[str, Agent] = {}

    def register(self, agent: Agent) -> None:
        self._agents[agent.name] = agent

    def unregister(self, name: str) -> Agent | None:
        return self._agents.pop(name, None)

    def get(self, name: str) -> Agent | None:
        return self._agents.get(name)

    def has(self, name: str) -> bool:
        return name in self._agents

    def list(self) -> list[Agent]:
        return list(self._agents.values())

    def clear(self) -> None:
        self._agents.clear()

    def to_dict(self) -> list[dict]:
        return [{
            "name": a.name,
            "role": a.role,
            "status": a.status,
            "emotion": a.emotion_state,
            "relationships": a.relationships,
            "long_memory_count": len(a.long_memory),
        } for a in self.list()]
