"""V3: Agent Runtime Manager —— 真正动态的 Agent 生命周期管理。

支持：
- create_agent(character)   创建并注册（不存在时经 Factory 从知识库构建）
- destroy_agent(agent_id)   销毁（先保存记忆）
- pause_agent(agent_id)     暂停（保存状态）
- resume_agent(agent_id)    恢复
"""
from __future__ import annotations

from .agents import Agent, STATUS_DESTROYED
from .memory import sanitize
from .prompts import (
    build_character_system_prompt,
    build_director_system_prompt,
    build_world_check_system_prompt,
    build_memory_extract_system_prompt,
    build_synopsis_system_prompt,
)


class RuntimeManager:
    def __init__(self, session, llm, kb, memory, world):
        self.session = session
        self.llm = llm
        self.kb = kb
        self.memory = memory
        self.world = world

    # ---------- Factory（V2 Character Factory）----------
    def build_agent(self, name: str) -> Agent:
        display = self.kb.resolve_character(name)
        if not display:
            raise KeyError(f"知识库中找不到角色: {name}")
        profile = self.kb.get_character_profile(display)
        return Agent(
            agent_id=f"agent_{sanitize(display)}",
            name=display,
            profile=profile or "",
            system_prompt="",
            status="active",
        )

    def _finalize_system_prompt(self, agent: Agent) -> None:
        # V4：用户手动编辑过提示词则不覆盖
        if getattr(agent, "prompt_locked", False):
            return
        # V4：结构化角色卡（性格/语感/语言示例）+ 全局文风规范
        card = self.kb.get_character_card(agent.name) if hasattr(self.kb, "get_character_card") else None
        style_spec = self.kb.style_spec() if hasattr(self.kb, "style_spec") else ""
        anti_ai = bool(getattr(self.session.config, "anti_ai_flavor", True))
        agent.system_prompt = build_character_system_prompt(
            agent.name, agent.profile, agent.long_memory,
            self.world.world_name, self.world.effective_rules,
            card=card, style_spec=style_spec, anti_ai=anti_ai)

    # ---------- 导演 Agent（Director 也作为一等 Agent 处理）----------
    def create_director_agent(self) -> Agent:
        existing = self.session.registry.get("导演")
        if existing:
            return existing
        agent = Agent(
            agent_id="agent_director",
            name="导演",
            role="director",
            profile=(f"「{self.world.world_name}」群聊剧情的导演 Agent。"
                     f"可调度角色：{'、'.join(self.kb.character_names())}。"),
            system_prompt="",
            status="active",
        )
        # 若导演曾被销毁，恢复其历史长期记忆
        saved = self._load_saved_memory("导演")
        if saved and saved.get("status") == STATUS_DESTROYED:
            agent.long_memory = saved.get("long_memory", [])
        self._finalize_director_prompt(agent)
        self.session.registry.register(agent)
        self.memory.save_agent(agent)
        return agent

    def _finalize_director_prompt(self, agent: Agent) -> None:
        if getattr(agent, "prompt_locked", False):
            return
        agent.system_prompt = build_director_system_prompt(
            self.world.world_name, self.kb.character_names(),
            self.world.effective_rules, agent.long_memory)

    def refresh_director_prompt(self, agent: Agent) -> None:
        self._finalize_director_prompt(agent)

    # ---------- 功能性 Agent（World / Memory Manager / Synopsis）----------
    _FUNCTIONAL_NAMES = {"世界": "world", "记忆管理": "memory", "梗概": "synopsis"}

    def _functional_prompt(self, role: str) -> str:
        if role == "world":
            return build_world_check_system_prompt(self.world.world_name, self.world.effective_rules)
        if role == "memory":
            return build_memory_extract_system_prompt()
        if role == "synopsis":
            return build_synopsis_system_prompt(self.world.world_name)
        return ""

    def create_functional_agent(self, name: str) -> Agent | None:
        role = self._FUNCTIONAL_NAMES.get(name)
        if not role:
            return None
        existing = self.session.registry.get(name)
        if existing:
            return existing
        profile = {
            "world": f"「{self.world.world_name}」世界的管理者（World Agent）：校验剧情是否符合世界规则。",
            "memory": "记忆管理器（Memory Manager）：为角色抽取长期记忆。",
            "synopsis": f"「{self.world.world_name}」世界的剧情梗概整理者（Synopsis Agent）。",
        }[role]
        agent = Agent(agent_id=f"agent_{role}", name=name, role=role,
                      profile=profile, system_prompt="", status="active")
        saved = self._load_saved_memory(name)
        if saved and saved.get("status") == STATUS_DESTROYED:
            agent.long_memory = saved.get("long_memory", [])
        agent.system_prompt = self._functional_prompt(role)
        self.session.registry.register(agent)
        self.memory.save_agent(agent)
        return agent

    def create_functional_agents(self) -> None:
        for name in self._FUNCTIONAL_NAMES:
            self.create_functional_agent(name)

    # ---------- Lifecycle ----------
    def create_agent(self, name: str) -> Agent:
        existing = self.session.registry.get(name)
        if existing:
            return existing
        resolved = self.kb.resolve_character(name)
        if resolved and self.session.registry.has(resolved):
            return self.session.registry.get(resolved)
        agent = self.build_agent(name)
        # 若该角色此前被销毁，恢复其历史长期记忆/情感/关系
        saved = self._load_saved_memory(agent.name)
        if saved and saved.get("status") == STATUS_DESTROYED:
            agent.long_memory = saved.get("long_memory", [])
            agent.emotion_state = saved.get("emotion_state", "平静")
            agent.relationships = saved.get("relationships", {})
        elif not agent.long_memory:
            # 首次创建：以 Memory/<名>.md 的内容作为该角色的初始长期记忆
            initial = self.kb.get_character_memory(agent.name)
            if initial:
                agent.long_memory = [
                    line.strip() for line in initial.splitlines()
                    if line.strip() and not line.lstrip().startswith("#")
                ]
        self._finalize_system_prompt(agent)
        self.session.registry.register(agent)
        self.memory.save_agent(agent)
        return agent

    def _load_saved_memory(self, name: str) -> dict | None:
        import json  # noqa: PLC0415
        p = self.memory.char_dir / f"{sanitize(name)}.json"
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                return None
        return None

    def ensure(self, name: str) -> Agent | None:
        try:
            return self.create_agent(name)
        except KeyError:
            return None

    def destroy_agent(self, name: str) -> bool:
        agent = self.session.registry.get(name)
        if not agent:
            return False
        agent.status = STATUS_DESTROYED
        self.memory.save_agent(agent)  # 先标记销毁再保存，重启后不会复活
        self.session.registry.unregister(name)
        return True


    def pause_agent(self, name: str) -> bool:
        agent = self.session.registry.get(name)
        if not agent:
            return False
        agent.status = "paused"
        self.memory.save_agent(agent)
        return True

    def resume_agent(self, name: str) -> bool:
        agent = self.session.registry.get(name)
        if not agent:
            if name == "导演":
                agent = self.create_director_agent()
            else:
                agent = self.create_agent(name)
        agent.status = "active"
        if not getattr(agent, "prompt_locked", False):
            if agent.role == "director":
                self._finalize_director_prompt(agent)
            else:
                self._finalize_system_prompt(agent)
        self.memory.save_agent(agent)
        return True

    def refresh_system_prompt(self, agent: Agent) -> None:
        self._finalize_system_prompt(agent)

    def refresh_prompt(self, agent: Agent) -> None:
        """按 Agent 类型重建 System Prompt（导演 / 功能 Agent / 角色）。"""
        if getattr(agent, "prompt_locked", False):
            return
        if agent.role == "director":
            self._finalize_director_prompt(agent)
        elif agent.role in ("world", "memory", "synopsis"):
            agent.system_prompt = self._functional_prompt(agent.role)
        else:
            self._finalize_system_prompt(agent)

    def set_prompt(self, agent: Agent, system_prompt: str, lock: bool = True) -> None:
        """设置/覆盖 Agent 提示词并落盘（lock=True 时不再被自动重建覆盖）。"""
        agent.system_prompt = system_prompt or ""
        agent.prompt_locked = bool(lock)
        self.memory.save_agent(agent)

    def reset_prompt(self, agent: Agent) -> None:
        """解除手动覆盖，恢复为按角色卡/世界自动生成。"""
        agent.prompt_locked = False
        self.refresh_prompt(agent)

    def get_or_create_agent(self, name: str) -> Agent | None:
        """按名字取 Agent；不存在则按类型创建（导演 / 功能 Agent / 角色），
        使功能 Agent（导演、世界、记忆管理、梗概）与角色一样可被详情/记忆接口读写。"""
        agent = self.session.registry.get(name)
        if agent:
            return agent
        if name == "导演":
            return self.create_director_agent()
        if name in self._FUNCTIONAL_NAMES:
            return self.create_functional_agent(name)
        try:
            return self.create_agent(name)
        except KeyError:
            return None

    # ---------- 恢复 ----------
    def restore_agents(self, saved: list[dict]) -> None:
        for d in saved:
            agent = Agent.from_memory_dict(d)
            if agent.status == STATUS_DESTROYED:
                continue
            # 迁移：旧名（标题别名/旧规范名）→ 新规范名（文档名），记忆与资料完整保留
            canonical = self.kb.resolve_character(agent.name)
            if canonical and canonical != agent.name:
                agent.name = canonical
            # 按 Agent 类型重建提示词（导演 / 世界 / 记忆管理 / 梗概 / 角色），
            # 避免功能 Agent 被误用角色 Prompt（重启后仍保持各自职责）。
            self.refresh_prompt(agent)
            self.session.registry.register(agent)
