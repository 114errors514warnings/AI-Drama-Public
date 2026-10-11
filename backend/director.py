"""V4: Director Agent（导演）—— 群聊剧情编排核心。

流程（群聊模式）：
用户输入 → Director 决策（参与角色/旁白/事件/时间/地点）
        → World Agent 校验（可选）
        → 各角色 Agent 依次发言（后发言者可见前面发言）
        → Memory Manager 抽取长期记忆 → 全部落盘

单角色模式（V1）：Character Selector → Retriever → Prompt Builder → LLM → 回复。
"""
from __future__ import annotations

import time
from contextlib import contextmanager

from . import prompts
from .llm_client import LLMError
from .memory_ops import merge_facts


class DirectorAgent:
    def __init__(self, session, llm, kb, runtime, world):
        self.session = session
        self.llm = llm
        self.kb = kb
        self.runtime = runtime
        self.world = world
        # 每轮 Agent 调用图（kind/耗时/token），用于可观测与评测
        self._calls: list[dict] = []
        self._memory_stats: dict = self._empty_memory_stats()

    # ---------- 调用计量 ----------
    @staticmethod
    def _empty_memory_stats() -> dict:
        return {"added": 0, "deduped": 0, "conflicts_resolved": 0, "truncated": 0}

    @contextmanager
    def _timed(self, kind: str, agent_name: str, role: str):
        """记录一次 LLM 调用的种类 / 角色 / 耗时 / token（OK 或异常都会落一条）。"""
        started = time.perf_counter()
        entry = {
            "agent": agent_name, "role": role, "kind": kind,
            "duration_ms": 0, "ok": True, "error": None,
            "prompt_tokens": 0, "completion_tokens": 0,
        }
        try:
            yield entry
        except Exception as exc:  # noqa: BLE001
            entry["ok"] = False
            entry["error"] = type(exc).__name__
            raise
        finally:
            entry["duration_ms"] = round((time.perf_counter() - started) * 1000)
            usage = getattr(self.llm, "last_usage", {}) or {}
            entry["prompt_tokens"] = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            entry["completion_tokens"] = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
            self._calls.append(entry)

    def _record_turn(self, record: dict, started: float) -> None:
        calls = list(self._calls)
        record["latency_ms"] = round((time.perf_counter() - started) * 1000)
        record["calls"] = calls
        record["llm_calls"] = len(calls)
        record["prompt_tokens"] = sum(int(c.get("prompt_tokens", 0)) for c in calls)
        record["completion_tokens"] = sum(int(c.get("completion_tokens", 0)) for c in calls)
        record["memory_stats"] = dict(self._memory_stats)
        record["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            self.session.memory.append_turn(record)
        except Exception:  # noqa: BLE001
            pass

    # ---------- 工具 ----------
    def _history(self, n: int = 30) -> list[dict]:
        """把转录转换为 LLM 消息历史（name 字段标识说话者）。"""
        msgs: list[dict] = []
        for m in self.session.transcript[-n:]:
            role = m.get("role", "assistant")
            if role == "user":
                msgs.append({"role": "user", "name": "用户", "content": m["content"]})
            elif role == "narrator":
                msgs.append({"role": "user", "name": "导演", "content": m["content"]})
            else:
                msgs.append({
                    "role": "assistant",
                    "name": m.get("speaker", "角色"),
                    "content": m["content"],
                })
        return msgs

    def _append(self, role: str, content: str, speaker: str | None = None) -> None:
        m: dict = {"role": role, "content": content}
        if speaker:
            m["speaker"] = speaker
        self.session.transcript.append(m)
        self.session.memory.save_transcript(self.session.transcript)

    def _reply_as(self, agent, user_input: str, narration: str, history: list[dict],
                  lore_block: str = "") -> str:
        msgs: list[dict] = [{"role": "system", "content": agent.system_prompt}]
        msgs.extend(history[-24:])
        last: list[str] = []
        if narration:
            last.append(
                f"【场景】（导演的场景描述，请勿复述或模仿其写法，请以第一人称自然回应）\n{narration}")
        if lore_block:
            last.append(f"【相关世界常识（你可能知道的部分，只可作参考）】\n{lore_block}")
        last.append(f"【用户】{user_input}")
        # V4 终局指令（post-history）：把模型逼回"角色本人、像示例那样说话"
        last.append(
            f"（现在轮到「{agent.name}」说话：用你自己的语气，像上面示例那样，"
            f"只写 1~3 段你自己的话；不要旁白别人，不要总结。）")
        msgs.append({"role": "user", "name": "用户", "content": "\n".join(last)})
        cfg = self.session.config
        try:
            with self._timed("character_reply", agent.name, agent.role):
                return self.llm.chat(
                    msgs,
                    temperature=float(getattr(cfg, "character_temperature", 1.0) or 1.0),
                    max_tokens=int(getattr(cfg, "max_tokens", 600) or 600),
                )
        except LLMError as exc:
            return f"（{agent.name} 沉默了片刻，欲言又止……）\n[生成出错: {exc}]"

    def _build_lore_block(self, query: str, top_k: int = 3) -> str:
        """RAG：优先用世界观词条命中（V4），无命中时退回整篇语料检索。"""
        if hasattr(self.kb, "match_lore"):
            block = self.kb.match_lore(query, limit=top_k)
            if block:
                return block
        docs = self.kb.search_lore(query, top_k=top_k)
        if not docs:
            return ""
        return "\n\n".join(
            f"【{d['title']}】\n{d['content']}" for d in docs)


    # ---------- V4 群聊 ----------
    def build_director_messages(self, user_input: str, revision: str = "") -> list[dict]:
        """构建「导演规划」要发送的完整消息（供调试/自检：可看到真实提示词与上下文）。"""
        director_agent = self.session.registry.get("导演")
        sys_prompt = (director_agent.system_prompt if director_agent
                      else prompts.build_director_system_prompt(
                          self.world.world_name, self.kb.character_names(),
                          self.world.effective_rules, []))
        director_msgs: list[dict] = [{"role": "system", "content": sys_prompt}]
        director_msgs.extend(self._history(20))
        director_lore = self._build_lore_block(user_input, top_k=2)
        if director_lore:
            director_msgs.append({
                "role": "user", "name": "世界常识",
                "content": "以下是当前场景相关的世界常识，供你规划剧情与选择角色时参考：\n" + director_lore,
            })
        director_msgs.append({
            "role": "user", "name": "用户",
            "content": user_input + "\n\n请只输出导演规划 JSON。",
        })
        if revision:
            director_msgs.append({
                "role": "user", "name": "世界校验反馈",
                "content": revision + "\n请据此修正你的规划，然后重新只输出导演规划 JSON。",
            })
        return director_msgs

    def _director_plan(self, user_input: str, revision: str = "") -> dict:
        """调用导演 Agent 生成规划 JSON。

        唯一来源 = 导演 Agent 的 system_prompt（可在 Agent 详情中查看/重建），
        不再每轮临时拼装，使提示词编辑真正影响群聊。
        """
        director_msgs = self.build_director_messages(user_input, revision)
        with self._timed("director_plan", "导演", "director"):
            plan = self.llm.chat_json(director_msgs)
        return plan if isinstance(plan, dict) else {}

    # ---------- V4 调试 / 自检（只读或 dry-run，不污染转录与世界状态） ----------
    def preview_group_plan(self, user_input: str) -> dict:
        """群聊模式：构建导演规划消息但不调用 LLM（验证提示词与上下文来源）。"""
        msgs = self.build_director_messages(user_input)
        system = msgs[0]["content"] if msgs else ""
        director = self.session.registry.get("导演")
        return {
            "messages": msgs,
            "system_prompt": system,
            "system_prompt_requires_json": "只输出导演规划 JSON" in system,
            "history_len": len(self._history(20)),
            "transcript_len": len(self.session.transcript),
            "side_chat_included": False,          # 群聊规划不引用场外单聊（TODO-4 现象2）
            "director_memory": list(director.long_memory) if director else [],
            "director_prompt_locked": bool(getattr(director, "prompt_locked", False)),
            "world_rules_source": "override" if self.world.rules_override.strip() else "kb",
            "world_rules_len": len(self.world.effective_rules or ""),
        }

    def run_group_plan(self, user_input: str) -> dict:
        """群聊模式：真的调用一次导演规划，返回原始输出 + 解析结果；不写入任何状态。"""
        from .llm_client import extract_json  # noqa: PLC0415
        msgs = self.build_director_messages(user_input)
        try:
            with self._timed("director_plan_debug", "导演", "director"):
                raw = self.llm.chat(msgs, json_mode=True, max_tokens=600)
        except LLMError as exc:
            return {"ok": False, "error": str(exc), "raw": "", "plan": None, "output_is_json": False}
        plan = None
        try:
            plan = extract_json(raw)
        except LLMError:
            plan = None
        return {
            "ok": isinstance(plan, dict),
            "raw": raw,
            "plan": plan if isinstance(plan, dict) else None,
            "output_is_json": isinstance(plan, dict),
        }

    def build_agent_messages(self, agent, user_input: str) -> list[dict]:
        """单 Agent（含系统 Agent）对话要发送的完整消息（供调试/自检）。"""
        msgs: list[dict] = [{"role": "system", "content": agent.system_prompt}]
        for m in self.session.side_chats.get(agent.name, [])[-20:]:
            if m.get("role") == "user":
                msgs.append({"role": "user", "name": "用户", "content": m["content"]})
            else:
                msgs.append({"role": "assistant", "name": agent.name, "content": m["content"]})
        msgs.append({"role": "user", "name": "用户", "content": user_input})
        return msgs

    def debug_context(self, agent_name: str = "") -> dict:
        """上下文自检：群聊规划实际引用什么、单聊记录是否被引用。"""
        director = self.session.registry.get("导演")
        agent = self.session.registry.get(agent_name) if agent_name else None
        return {
            "session_id": self.session.id,
            "transcript_len": len(self.session.transcript),
            "history_in_group_plan": len(self._history(20)),
            "side_chats": {k: len(v) for k, v in self.session.side_chats.items()},
            "side_chats_used_in_group_plan": False,
            "world_rules_source": "override" if self.world.rules_override.strip() else "kb",
            "world_rules_len": len(self.world.effective_rules or ""),
            "director": None if not director else {
                "name": director.name,
                "prompt_locked": bool(getattr(director, "prompt_locked", False)),
                "system_prompt": director.system_prompt,
                "long_memory": list(director.long_memory),
            },
            "agent": None if not agent else {
                "name": agent.name,
                "role": agent.role,
                "status": agent.status,
                "prompt_locked": bool(getattr(agent, "prompt_locked", False)),
                "system_prompt": agent.system_prompt,
                "side_chat_len": len(self.session.side_chats.get(agent.name, [])),
            },
        }

    def _parse_plan(self, plan: dict) -> tuple[str, str, str, str, str, list]:
        """把导演规划 JSON 规整为 (narration, location, date, time_of_day, event, participants)。"""
        narration = str(plan.get("narration", "")).strip()
        location = str(plan.get("location", "")).strip() or self.world.location
        date_raw = str(plan.get("date", "")).strip()
        tod_raw = str(plan.get("time_of_day", "")).strip()
        event = str(plan.get("event", "")).strip() or narration[:80]
        raw_participants = plan.get("participants", [])
        if isinstance(raw_participants, str):
            raw_participants = [raw_participants]
        date = self._normalize_date(date_raw) if date_raw else self.world.date
        tod = tod_raw or self.world.time_of_day
        return narration, location, date, tod, event, raw_participants

    def run_group_turn(self, user_input: str) -> dict:
        """群聊一轮（带计时与 Agent 调用图）。

        无论成功还是抛错，都会向 `turns.jsonl` 追加一条记录，
        以便统计「Agent 编排成功率」等硬指标。
        """
        self._calls = []
        self._memory_stats = self._empty_memory_stats()
        record: dict = {"user_input": user_input[:200], "ok": False, "world_issues": 0,
                        "world_corrected": False, "date_reverted": False}
        started = time.perf_counter()
        try:
            result = self._run_group_turn(user_input, record)
            record["ok"] = True
            self._record_turn(record, started)
            return result
        except Exception:  # noqa: BLE001
            self._record_turn(record, started)
            raise

    def _run_group_turn(self, user_input: str, record: dict) -> dict:
        plan = self._director_plan(user_input)
        narration, location, date, tod, event, raw_participants = self._parse_plan(plan)

        # World Agent 校验：世界状态变化时执行（增量触发，省 token）。
        # world_check_mode：off（关闭）/ advisory（仅记录，默认）/ enforce（校验不通过则反馈导演闭环修正）。
        mode = getattr(self.session.config, "world_check_mode", "advisory")
        max_retries = int(getattr(self.session.config, "world_check_retries", 2) or 0)
        check_issues: list[str] = []
        initial_issues: list[str] = []
        corrected = False
        attempts = 0
        if mode != "off":
            for attempt in range(max_retries + 1):
                changed = (location != self.world.location
                           or date != self.world.date
                           or tod != self.world.time_of_day)
                if not (changed and narration):
                    check_issues = []
                    break
                attempts += 1
                check_issues = self.world_check(
                    event, narration, [str(n) for n in raw_participants])
                if attempts == 1:
                    initial_issues = list(check_issues)
                if not check_issues or mode != "enforce" or attempt >= max_retries:
                    break
                revision = ("世界校验发现问题，请修正本轮规划：\n"
                            + "\n".join(f"- {i}" for i in check_issues)
                            + f"\n（原规划：地点={location}，事件={event}）")
                revised = self._director_plan(user_input, revision=revision)
                narration, location, date, tod, event, raw_participants = self._parse_plan(revised)
                corrected = True

        # 提交世界状态与时间线（年月日格式）；日期只进不退（长程一致性硬约束）
        date_reverted = False
        self.world.location = location
        if date:
            if not self.world.try_set_date(date):
                date_reverted = True
                date = self.world.date
        self.world.time_of_day = tod
        if event:
            self.world.add_event(event, narration)

        # 确保参与者 Agent 存在（V2 Factory + Registry / V3 Lifecycle）
        participants = []
        skipped = []
        for name in raw_participants:
            agent = self.runtime.ensure(str(name))
            if agent is None:
                skipped.append(str(name))
                continue
            if agent.status != "active" or agent.role != "character":
                skipped.append(agent.name)
                continue
            participants.append(agent)
        if not participants:
            participants = self._fallback_participants()

        # 记录用户输入与导演发言（导演以独立身份出现在群聊中），再逐角色发言
        self._append("user", user_input)
        if narration:
            self._append("narrator", narration, speaker="导演")

        lore_block = self._build_lore_block(user_input + " " + narration, top_k=3)
        replies = []
        for agent in participants:
            content = self._reply_as(agent, user_input, narration,
                                     self._history(30), lore_block)
            replies.append({"speaker": agent.name, "content": content})
            self._append("assistant", content, speaker=agent.name)
            self.session.memory.save_agent(agent)

        # 长期记忆抽取（Memory Manager）
        extracted = self.extract_memories(
            [a.name for a in participants], user_input, narration, replies)

        # 剧情梗概（节流更新）
        self.update_synopsis()

        self.session.save()
        record["world_issues"] = len(initial_issues)
        record["world_issues_final"] = len(check_issues)
        record["world_corrected"] = corrected
        record["world_check_attempts"] = attempts
        record["date_reverted"] = date_reverted
        record["participants"] = [a.name for a in participants]
        return {
            "user_input": user_input,
            "narration": narration,
            "location": location,
            "date": self.world.date,
            "time_of_day": self.world.time_of_day,
            "time": self.world.display_time(
                getattr(self.session.config, "time_format", "date"),
                getattr(self.session.config, "time_fallback", "时间未定")),
            "event": event,
            "participants": [a.name for a in participants],
            "skipped": skipped,
            "replies": replies,
            "memories_extracted": extracted,
            "world_check_mode": mode,
            "world_check_issues": check_issues,
            "world_check_initial_issues": initial_issues,
            "world_corrected": corrected,
            "world_check_attempts": attempts,
            "date_reverted": date_reverted,
            "agent_calls": list(self._calls),
            "world": self.world.to_dict(),
        }

    def _fallback_participants(self):
        agents = [a for a in self.session.registry.list()
                  if a.status == "active" and a.role == "character"]
        if agents:
            return agents[:2]
        out = []
        for name in self.kb.character_names()[:2]:
            a = self.runtime.ensure(name)
            if a:
                out.append(a)
        return out

    @staticmethod
    def _normalize_date(raw: str) -> str:
        """把导演输出的日期统一为 ISO YYYY-MM-DD（兼容 2026年8月19日 / 2026-08-19）。"""
        import re  # noqa: PLC0415
        m = re.match(r"\s*(\d{4})\s*[年\-/. ]\s*(\d{1,2})\s*[月\-/. ]\s*(\d{1,2})\s*日?", raw)
        if m:
            y, mo, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return f"{y:04d}-{mo:02d}-{dd:02d}"
        m2 = re.match(r"\s*(\d{4}-\d{2}-\d{2})", raw)
        if m2:
            return m2.group(1)
        return raw

    # ---------- World Agent 校验 ----------
    def world_check(self, event: str, narration: str, participants: list[str]) -> list[str]:
        agent = self.session.registry.get("世界")
        sys_prompt = (agent.system_prompt if agent
                      else prompts.build_world_check_system_prompt(
                          self.world.world_name, self.world.rules))
        try:
            with self._timed("world_check", "世界", "world"):
                data = self.llm.chat_json([
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content":
                     f"本轮事件: {event}\n旁白: {narration}\n参与角色: {', '.join(participants)}"},
                ], max_tokens=400)
        except LLMError:
            return []
        if not isinstance(data, dict):
            return []
        if data.get("ok") is False:
            issues = data.get("issues", [])
            return [str(i) for i in issues] if isinstance(issues, list) else []
        return []

    # ---------- 剧情梗概（Synopsis Agent）----------
    def update_synopsis(self, force: bool = False, threshold: int = 6) -> str:
        """更新剧情梗概。节流：累计 threshold 条新消息后自动更新；force 时强制刷新。"""
        total = len(self.session.transcript)
        if not force and total - self.world.synopsis_base_len < threshold:
            return self.world.synopsis
        lines = []
        for m in self.session.transcript[-40:]:
            role = m.get("role", "assistant")
            if role == "user":
                who = "用户"
            elif role == "narrator":
                who = "导演"
            else:
                who = m.get("speaker", "角色")
            lines.append(f"{who}：{m['content']}")
        recent = "\n".join(lines)
        syn_agent = self.session.registry.get("梗概")
        sys_prompt = (syn_agent.system_prompt if syn_agent
                      else prompts.build_synopsis_system_prompt(self.world.world_name))
        try:
            with self._timed("synopsis", "梗概", "synopsis"):
                new_synopsis = self.llm.chat(
                    [{"role": "system", "content": sys_prompt},
                     {"role": "user", "content":
                      prompts.build_synopsis_user(self.world.synopsis, recent)}],
                    temperature=0.4, max_tokens=600)
        except LLMError:
            return self.world.synopsis
        new_synopsis = (new_synopsis or "").strip()
        if new_synopsis:
            self.world.synopsis = new_synopsis
            self.world.synopsis_base_len = total
            self.session.save()
        return self.world.synopsis


    # ---------- 单Agent对话（场外，不进群聊转录/记忆/梗概）----------
    def run_agent_turn(self, agent_name: str, user_input: str, commit: bool = True) -> dict:
        """与指定 Agent 一对一对话，不写入群聊转录、不抽取记忆、不更新剧情。

        ``commit=False`` 为 dry-run：调用模型但不写入场外对话记录（供调试/自测）。
        """
        agent = (self.session.registry.get(agent_name)
                 or self.runtime.get_or_create_agent(agent_name))
        if not agent:
            return {"error": f"Agent {agent_name} 不存在"}
        if agent.status != "active":
            return {"error": f"Agent {agent_name} 当前状态为 {agent.status}，无法对话"}
        msgs = self.build_agent_messages(agent, user_input)
        try:
            with self._timed("agent_reply", agent.name, agent.role):
                reply = self.llm.chat(msgs, temperature=0.85, max_tokens=600)
        except LLMError as exc:
            reply = f"（{agent_name} 沉默了片刻……）[生成出错: {exc}]"
        system = agent.system_prompt or ""
        requires_json = ("只输出导演规划 JSON" in system) or ("只输出严格 JSON" in system)
        if commit:
            side = self.session.side_chats.get(agent.name, [])
            side.append({"role": "user", "content": user_input})
            side.append({"role": "assistant", "speaker": agent.name, "content": reply})
            self.session.side_chats[agent.name] = side
            self.session.save()
        return {
            "speaker": agent.name,
            "reply": reply,
            "committed": bool(commit),
            "system_prompt_requires_json": requires_json,
            "side_chat_len": len(self.session.side_chats.get(agent.name, [])),
        }

    # ---------- Memory Manager：长期记忆抽取 ----------
    def extract_memories(self, participants: list[str], user_input: str,
                         narration: str, replies: list[dict]) -> dict:
        participants = [p for p in participants if p]
        if not participants:
            return {}
        mem_agent = self.session.registry.get("记忆管理")
        sys_prompt = (mem_agent.system_prompt if mem_agent
                      else prompts.build_memory_extract_system_prompt())
        user_msg = prompts.build_memory_extract_user(
            participants, user_input, narration, replies)
        try:
            with self._timed("memory_extract", "记忆管理", "memory"):
                data = self.llm.chat_json(
                    [{"role": "system", "content": sys_prompt},
                     {"role": "user", "content": user_msg}], max_tokens=800)
        except LLMError:
            return {}
        if not isinstance(data, dict):
            return {}
        # 兼容两种返回格式：
        #   格式1: {"角色名": ["事实", ...]}
        #   格式2: {"memories": [{"role": "角色名", "fact": "事实", ...}, ...]}
        entries: dict[str, list[str]] = {}
        if isinstance(data.get("memories"), list):
            for item in data["memories"]:
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role") or item.get("name") or "").strip()
                fact = str(item.get("fact") or item.get("memory") or item.get("content") or "").strip()
                if role and fact:
                    entries.setdefault(role, []).append(fact)
        else:
            for name, facts in data.items():
                if isinstance(facts, list):
                    entries[str(name)] = [str(f) for f in facts]

        added: dict[str, int] = {}
        for name, facts in entries.items():
            agent = self.session.registry.get(name)
            if not agent:
                # 尝试用知识库解析别名（如 "小甲" → "小甲 / 甲的代号"）
                resolved = self.kb.resolve_character(name)
                if resolved:
                    agent = self.session.registry.get(resolved)
            if not agent:
                continue
            merged, stats = merge_facts(agent.long_memory, facts)
            agent.long_memory = merged
            for key in self._memory_stats:
                self._memory_stats[key] += int(stats.get(key, 0) or 0)
            self.runtime.refresh_system_prompt(agent)
            self.session.memory.save_agent(agent)
            if stats["added"]:
                added[agent.name] = stats["added"]
        return added


