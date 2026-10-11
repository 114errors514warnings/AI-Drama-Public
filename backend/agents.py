"""V2: Agent 实例 —— 每个角色拥有独立的资料、记忆、状态与关系。

Agent Instance = System Prompt + Character Profile + Memory + State + Skill + Tool + Runtime Context
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

STATUS_ACTIVE = "active"
STATUS_PAUSED = "paused"
STATUS_DESTROYED = "destroyed"


@dataclass
class Agent:
    agent_id: str
    name: str
    role: str = "character"  # character（角色） / director（导演）
    profile: str = ""
    system_prompt: str = ""
    status: str = STATUS_ACTIVE
    emotion_state: str = "平静"
    relationships: dict = field(default_factory=dict)
    long_memory: list = field(default_factory=list)
    skills: list = field(default_factory=list)
    prompt_locked: bool = False   # V4：用户手动编辑过提示词 → 不再自动重建

    def to_memory_dict(self) -> dict:
        """导出为可持久化到角色记忆库的字典。"""
        return asdict(self)

    @classmethod
    def from_memory_dict(cls, d: dict) -> "Agent":
        return cls(
            agent_id=d.get("agent_id", ""),
            name=d.get("name", ""),
            role=d.get("role", "character"),
            profile=d.get("profile", ""),
            system_prompt=d.get("system_prompt", ""),
            status=d.get("status", STATUS_ACTIVE),
            emotion_state=d.get("emotion_state", "平静"),
            relationships=d.get("relationships", {}),
            long_memory=d.get("long_memory", []),
            skills=d.get("skills", []),
            prompt_locked=bool(d.get("prompt_locked", False)),
        )
