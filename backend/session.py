"""会话与世界隔离：一个会话 = 一个知识库 = 一套独立的 Agent 集合。

- 允许多个群聊会话同时运行，各自由独立的 Director + 角色 Agent 管理。
- 切换会话不销毁任何数据；重启服务后从磁盘恢复全部会话与角色记忆。
- 删除会话是唯一会移除记忆的途径，且必须显式调用。
"""
from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path

from .director import DirectorAgent
from .knowledge_base import KnowledgeBase
from .llm import create_llm
from .memory import MemoryStore
from .registry import AgentRegistry
from .runtime import RuntimeManager
from .world import WorldState


class WorldSession:
    def __init__(self, session_id: str, name: str, kb_path: str,
                 llm: LLMClient, sessions_root: str | Path, config):
        self.id = session_id
        self.name = name
        self.kb_path = str(kb_path)
        self.config = config
        self.llm = llm
        self.kb = KnowledgeBase(self.kb_path)
        # 知识库三目录约定：缺失时自动新建 Character / Memory / World
        for _sub in ("Character", "Memory", "World"):
            (self.kb.root / _sub).mkdir(parents=True, exist_ok=True)
        self.world = WorldState(world_name=self.kb.world_name, rules=self.kb.world_constant())
        self.registry = AgentRegistry()
        self.memory = MemoryStore(Path(sessions_root) / session_id)
        self.runtime = RuntimeManager(self, llm, self.kb, self.memory, self.world)
        self.director = DirectorAgent(self, llm, self.kb, self.runtime, self.world)
        self.transcript: list[dict] = []
        self.side_chats: dict[str, list[dict]] = {}  # 场外对话记录
        self._restore()

    def _restore(self) -> None:
        """恢复持久化状态。角色 Agent 不再预实例化全部：首次参与群聊时才懒创建。"""
        state = self.memory.load_session_state()
        if state:
            self.name = state.get("name", self.name)
            self.world.restore(state.get("world"))
            self.side_chats = state.get("side_chats", {}) or {}
        # V4：世界背景以知识库为准重新装载（存量会话里可能残留旧的"写作辅助/评判标准"污染）
        self.world.rules = self.kb.world_constant()
        self.transcript = self.memory.load_transcript() or []
        saved = self.memory.load_agents()
        if saved:
            self.runtime.restore_agents(saved)
        # 导演作为一等 Agent 始终存在；功能 Agent（世界/记忆管理/梗概）共同维护群聊
        self.runtime.create_director_agent()
        self.runtime.create_functional_agents()
        self.save()

    def save(self) -> None:
        self.memory.save_session_state({
            "id": self.id,
            "name": self.name,
            "kb_path": self.kb_path,
            "world": {
                **self.world.to_dict(),
                "synopsis_base_len": self.world.synopsis_base_len,
            },
            "side_chats": self.side_chats,
        })
        self.memory.save_transcript(self.transcript)

    def rename(self, name: str) -> None:
        name = (name or "").strip()
        if name:
            self.name = name
            self.save()

    def clear_transcript(self) -> None:
        """清空对话记录并重置世界状态/时间线/梗概，但保留全部角色长期记忆。"""
        self.transcript = []
        self.world.date = ""
        self.world.time_of_day = ""
        self.world.location = "未知地点"
        self.world.events = []
        self.world.timeline = []
        self.world.synopsis = ""
        self.world.synopsis_base_len = 0
        self.save()

    def to_info(self, time_format: str = "date", fallback: str = "时间未定") -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "kb_path": self.kb_path,
            "world_name": self.world.world_name,
            "characters": sum(1 for a in self.registry.list() if a.role == "character"),
            "transcript_len": len(self.transcript),
            "time": self.world.display_time(time_format, fallback),
            "location": self.world.location,
        }


class SessionManager:
    def __init__(self, config, sessions_root: str | Path):
        self.config = config
        self.sessions_root = Path(sessions_root)
        (self.sessions_root).mkdir(parents=True, exist_ok=True)
        self.llm = create_llm(config)
        self.sessions: dict[str, WorldSession] = {}
        self.active_id: str | None = None
        self._load_existing()

    def _load_existing(self) -> None:
        for d in sorted(self.sessions_root.iterdir()):
            if not d.is_dir():
                continue
            state_file = d / "session.json"
            if not state_file.exists():
                continue
            try:
                state = json.loads(state_file.read_text(encoding="utf-8"))
                self.sessions[d.name] = WorldSession(
                    d.name,
                    state.get("name", d.name),
                    state.get("kb_path", ""),
                    self.llm,
                    self.sessions_root,
                    self.config,
                )
            except Exception:  # noqa: BLE001
                continue
        if self.sessions:
            self.active_id = next(iter(self.sessions))

    def create(self, name: str, kb_path: str) -> WorldSession:
        sid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        ws = WorldSession(sid, name, kb_path, self.llm, self.sessions_root, self.config)
        self.sessions[sid] = ws
        self.active_id = sid
        return ws

    def get(self, sid: str) -> WorldSession | None:
        return self.sessions.get(sid)

    def activate(self, sid: str) -> WorldSession:
        if sid not in self.sessions:
            raise KeyError(sid)
        self.active_id = sid
        return self.sessions[sid]

    def delete(self, sid: str) -> None:
        """显式删除会话（唯一会删除记忆的操作）。"""
        if sid not in self.sessions:
            raise KeyError(sid)
        target = self.sessions_root / sid
        if target.exists():
            shutil.rmtree(target)
        del self.sessions[sid]
        if self.active_id == sid:
            self.active_id = next(iter(self.sessions), None)

    def list_info(self) -> list[dict]:
        return [self.sessions[s].to_info() for s in self.sessions]
