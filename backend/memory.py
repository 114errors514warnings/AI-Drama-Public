"""记忆持久化（V4 Memory Manager 的数据层）。

- 记忆保存到"对应角色的记忆库"（data/sessions/<会话>/characters/<角色>.json），不随意删除。
- 短期记忆：会话转录 transcript.json（取最近 N 轮作为 LLM 上下文）。
- 长期记忆：角色文件中的 long_memory 列表。
- 切换会话 / 重启服务都不会清空记忆。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .agents import Agent


def sanitize(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s（）()]+', "_", name).strip("_") or "unnamed"


class MemoryStore:
    def __init__(self, session_dir: str | Path):
        self.session_dir = Path(session_dir)
        self.char_dir = self.session_dir / "characters"
        self.char_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _read_json(p: Path, default):
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return default

    @staticmethod
    def _write_json(p: Path, data) -> None:
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 会话状态 ----
    def save_session_state(self, data: dict) -> None:
        self._write_json(self.session_dir / "session.json", data)

    def load_session_state(self) -> dict | None:
        return self._read_json(self.session_dir / "session.json", None)

    # ---- 转录（短期记忆来源）----
    def save_transcript(self, messages: list) -> None:
        self._write_json(self.session_dir / "transcript.json", messages)

    def load_transcript(self) -> list:
        return self._read_json(self.session_dir / "transcript.json", [])

    # ---- 角色记忆 ----
    def save_agent(self, agent: Agent) -> None:
        p = self.char_dir / f"{sanitize(agent.name)}.json"
        self._write_json(p, agent.to_memory_dict())

    def load_agents(self) -> list[dict]:
        out = []
        for p in self.char_dir.glob("*.json"):
            d = self._read_json(p, None)
            if d:
                out.append(d)
        return out

    # ---- 每轮编排指标（V2 可评测化，JSONL 追加式）----
    @property
    def turns_path(self) -> Path:
        return self.session_dir / "turns.jsonl"

    def append_turn(self, record: dict) -> None:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        with self.turns_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def load_turns(self, limit: int = 100) -> list[dict]:
        if not self.turns_path.exists():
            return []
        lines = self.turns_path.read_text(encoding="utf-8").splitlines()
        out = []
        for line in lines[-max(1, limit):]:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out
