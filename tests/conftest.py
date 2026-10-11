"""AI Drama 测试夹具：隔离的临时知识库 + 确定性 FakeLLM。"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.eval.replay import _make_kb  # noqa: E402
from backend.session import WorldSession  # noqa: E402


def make_config(mode: str = "advisory", retries: int = 2) -> SimpleNamespace:
    return SimpleNamespace(
        time_format="date", time_fallback="时间未定",
        world_check_mode=mode, world_check_retries=retries,
        model="fake", temperature=0.7, api_key="", base_url="",
        chat_url=lambda: "http://localhost/chat/completions",
    )


def make_session(tmp_path, llm, mode: str = "advisory", retries: int = 2) -> WorldSession:
    kb = _make_kb(Path(tmp_path))
    return WorldSession("s1", "测试会话", str(kb), llm,
                        Path(tmp_path) / "sessions", make_config(mode, retries))
