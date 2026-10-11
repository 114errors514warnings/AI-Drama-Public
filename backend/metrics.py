"""会话级评测指标（V2 可评测化）。

把「群聊剧情质量」中**可硬断言**的部分抽成指标（隔离 / 编排成功率 / 世界违规率等），
LLM 裁判类指标（人设一致率）只作观察项，不进入硬门禁。
"""
from __future__ import annotations

from statistics import median

from .style import ai_flavor_hit_rate, ai_flavor_hits

# 转录中允许出现的角色类型；出现其它类型即视为「场外内容写入转录」的泄漏
ALLOWED_TRANSCRIPT_ROLES = {"user", "narrator", "assistant"}

# 场外提示词特征片段：若出现在转录文本中，说明场外内容被污染
OFFSCREEN_MARKERS = (
    "调度备忘",
    "只输出导演规划 JSON",
    "只输出严格 JSON",
    "Memory Manager",
    "World Agent",
    "梗概整理者",
    "场外参考",
    "【相关世界常识",
    "需提取记忆的角色",
)

# 被排除目录（写作辅助/评判标准/风格分析…）的特征片段：
# 若出现在世界背景里，说明它们仍漏进了提示词（硬门禁应为 0）。
EXCLUDED_LORE_MARKERS = (
    "质量门禁", "quality-gate", "Pipeline", "修复技法", "陷阱卡",
    "评判标准", "视角统一", "文风分析",
)

# 门禁阈值（与《AI 项目完整版执行方案与测试指标》4.4 对齐）
GATES = {
    "offscreen_leak_count": {"op": "<=", "value": 0},
    "agent_orchestration_success_rate": {"op": ">=", "value": 0.98},
    "world_violation_rate": {"op": "<=", "value": 0.05},
    "timeline_issues": {"op": "<=", "value": 0},
    # V4：排除目录内容不得漏进世界背景
    "world_leak_from_excluded": {"op": "<=", "value": 0},
}


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = max(0, min(int(round((len(ordered) - 1) * p)), len(ordered) - 1))
    return float(ordered[idx])


def count_offscreen_leaks(transcript: list[dict]) -> int:
    """统计转录中被场外内容污染的条数（硬断言应为 0）。"""
    leaks = 0
    for entry in transcript:
        role = str(entry.get("role", "assistant"))
        content = str(entry.get("content", ""))
        if role not in ALLOWED_TRANSCRIPT_ROLES:
            leaks += 1
            continue
        if any(marker in content for marker in OFFSCREEN_MARKERS):
            leaks += 1
    return leaks


def memory_usage_rate(session) -> float | None:
    """记忆召回率的离线代理指标（观察项）。

    统计「有长期记忆的角色」的发言中，有多少条与其长期记忆存在关键词重叠
    （bigram 命中）。它不是严格的召回率，只用于观察趋势，不进入硬门禁。
    """
    from .knowledge_base import tokenize  # noqa: PLC0415

    memories: dict[str, set[str]] = {}
    for agent in session.registry.list():
        if agent.role == "character" and agent.long_memory:
            tokens: set[str] = set()
            for fact in agent.long_memory:
                tokens |= set(tokenize(str(fact)))
            if tokens:
                memories[agent.name] = tokens

    total = 0
    hits = 0
    for message in session.transcript:
        if message.get("role") != "assistant":
            continue
        speaker = message.get("speaker")
        if speaker not in memories:
            continue
        total += 1
        speech = set(tokenize(str(message.get("content", ""))))
        if speech & memories[speaker]:
            hits += 1
    return (hits / total) if total else None


def count_excluded_lore_leaks(world_rules: str) -> int:
    """统计世界背景里残留的"排除目录"特征（硬门禁应为 0）。"""
    text = world_rules or ""
    return sum(1 for marker in EXCLUDED_LORE_MARKERS if marker in text)


def transcript_ai_flavor(session) -> dict:
    """角色发言的"AI 腔"规则通道统计（观察项）：词表命中数 / 千字。"""
    hits = 0
    chars = 0
    for message in session.transcript:
        if message.get("role") != "assistant":
            continue
        content = str(message.get("content", ""))
        chars += len(content)
        hits += ai_flavor_hits(content)
    return {
        "ai_flavor_hits": hits,
        "ai_flavor_rate": round(hits / (chars / 1000.0), 3) if chars else 0.0,
        "ai_flavor_chars": chars,
    }


def example_injected_ratio(session) -> float | None:
    """角色 Agent 中已注入"对话示例"的比例（观察项）。"""
    agents = [a for a in session.registry.list() if a.role == "character"]
    if not agents:
        return None
    injected = sum(1 for a in agents if "你说话的示例" in (a.system_prompt or ""))
    return round(injected / len(agents), 3)


def session_metrics(session, turns: list[dict] | None = None) -> dict:
    """汇总一个会话的硬指标 + 观察项。"""
    turns = turns if turns is not None else session.memory.load_turns(500)

    total = len(turns)
    completed = sum(1 for t in turns if t.get("ok"))
    violations = sum(1 for t in turns if int(t.get("world_issues", 0) or 0) > 0)
    corrected = sum(1 for t in turns if t.get("world_corrected"))
    latencies = [float(t.get("latency_ms", 0) or 0) for t in turns if t.get("latency_ms") is not None]
    tokens = [int(t.get("prompt_tokens", 0) or 0) + int(t.get("completion_tokens", 0) or 0) for t in turns]

    transcript = list(session.transcript)
    leak_count = count_offscreen_leaks(transcript)
    timeline_issues = session.world.validate_timeline()

    registry = session.registry.list()
    memories_total = sum(len(a.long_memory) for a in registry)
    characters_active = sum(1 for a in registry if a.role == "character" and a.status == "active")

    metrics = {
        "turns_total": total,
        "turns_completed": completed,
        "agent_orchestration_success_rate": (completed / total) if total else None,
        "world_violation_rate": (violations / total) if total else 0.0,
        "world_correction_rate": (corrected / violations) if violations else None,
        "offscreen_leak_count": leak_count,
        "timeline_issues": len(timeline_issues),
        "timeline_issue_detail": timeline_issues[:10],
        "transcript_len": len(transcript),
        "avg_tokens_per_turn": (sum(tokens) / total) if total else None,
        "total_tokens": sum(tokens),
        "p50_turn_latency_ms": _percentile(latencies, 0.50),
        "p95_turn_latency_ms": _percentile(latencies, 0.95),
        "median_turn_latency_ms": median(latencies) if latencies else None,
        "synopsis_coverage": session.world.synopsis_coverage(),
        "memory_usage_rate": memory_usage_rate(session),
        "memories_total": memories_total,
        "characters_active": characters_active,
        "events": len(session.world.events),
    }
    # V4：去 AI 腔 + 排除目录泄漏 + 示例注入（观察项 + 1 项硬门禁）
    metrics.update(transcript_ai_flavor(session))
    metrics["example_injected_ratio"] = example_injected_ratio(session)
    metrics["world_leak_from_excluded"] = count_excluded_lore_leaks(session.world.rules)
    metrics["gates"] = evaluate_session_gates(metrics)
    return metrics


def evaluate_session_gates(metrics: dict) -> dict[str, str]:
    """按门禁阈值判定；返回 {指标: PASS/FAIL/BASELINE}。"""
    out: dict[str, str] = {}
    for key, rule in GATES.items():
        value = metrics.get(key)
        if value is None:
            out[key] = "BASELINE"
            continue
        if rule["op"] == ">=":
            out[key] = "PASS" if value >= rule["value"] else "FAIL"
        else:
            out[key] = "PASS" if value <= rule["value"] else "FAIL"
    return out
