"""离线回放验收：用 FakeLLM 固定剧本回放 N 轮群聊，统计硬指标并判定门禁。

产出：
- reports/replay_<timestamp>.json / .md

不触网、不消耗 token，可作为 CI 门禁。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from backend.eval.fake_llm import FakeLLM  # noqa: E402
from backend.metrics import session_metrics  # noqa: E402
from backend.session import WorldSession  # noqa: E402

KB_FILES = {
    "Character/阿明.md": "# 阿明\n\n沉默寡言但热心的理科生，擅长拆解问题。\n",
    "Character/小红.md": "# 小红\n\n外向活泼的班长，喜欢张罗活动。\n",
    "Character/老王.md": "# 老王\n\n经验丰富的社团指导老师。\n",
    "World/世界观.md": "# 世界观\n\n故事发生在青岚中学，一切以现实校园生活为准。\n",
    "Memory/阿明.md": "# 阿明记忆\n\n- 阿明与小红是同班同学\n",
}


def _make_kb(root: Path) -> Path:
    kb = root / "kb"
    for rel, text in KB_FILES.items():
        path = kb / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return kb


def _config(mode: str = "enforce") -> SimpleNamespace:
    return SimpleNamespace(
        time_format="date", time_fallback="时间未定",
        world_check_mode=mode, world_check_retries=2,
        model="fake", temperature=0.7, api_key="", base_url="",
    )


def run_replay(workdir: Path, turns: int = 20) -> dict:
    workdir.mkdir(parents=True, exist_ok=True)
    kb_path = _make_kb(workdir)
    sessions_root = workdir / "sessions"

    llm = FakeLLM(
        world_issue_script=[["地点不合理：深夜的教室不应有阳光"], []],
        memories_script=[[
            {"role": "阿明", "fact": "阿明认识小红"},
            {"role": "阿明", "fact": "阿明认识小红"},           # 完全重复 → 去重
            {"role": "阿明", "fact": "阿明的生日是3月5日"},
            {"role": "阿明", "fact": "阿明的生日是4月1日"},      # 同句不同值 → 冲突消解（保留较新）
        ]],
    )
    session = WorldSession("replay-1", "回放测试", str(kb_path), llm, sessions_root, _config())

    turn_summaries = []
    for i in range(turns):
        result = session.director.run_group_turn(f"第{i + 1}轮：大家继续聊聊最近的校园生活。")
        turn_summaries.append({
            "turn": i + 1,
            "participants": result["participants"],
            "world_corrected": result.get("world_corrected", False),
            "date_reverted": result.get("date_reverted", False),
            "llm_calls": len(result.get("agent_calls", [])),
        })

    metrics = session_metrics(session)
    records = session.memory.load_turns(500)
    memory_stats = {"added": 0, "deduped": 0, "conflicts_resolved": 0, "truncated": 0}
    for record in records:
        for key in memory_stats:
            memory_stats[key] += int((record.get("memory_stats") or {}).get(key, 0) or 0)

    timeline_dates = [e.get("date", "") for e in session.world.timeline if e.get("date")]
    date_monotonic = all(timeline_dates[i] <= timeline_dates[i + 1] for i in range(len(timeline_dates) - 1))

    gates = []
    gates.append({
        "id": "agent_orchestration_success_rate", "value": metrics["agent_orchestration_success_rate"],
        "target": ">= 0.98",
        "status": "PASS" if (metrics["agent_orchestration_success_rate"] or 0) >= 0.98 else "FAIL",
    })
    gates.append({
        "id": "offscreen_leak_count", "value": metrics["offscreen_leak_count"], "target": "== 0",
        "status": "PASS" if metrics["offscreen_leak_count"] == 0 else "FAIL",
    })
    gates.append({
        "id": "world_violation_rate", "value": metrics["world_violation_rate"], "target": "<= 0.05",
        "status": "PASS" if metrics["world_violation_rate"] <= 0.05 else "FAIL",
    })
    correction_rate = metrics["world_correction_rate"]
    gates.append({
        "id": "world_correction_rate", "value": correction_rate, "target": "== 1.0（有违规时）",
        "status": "PASS" if (correction_rate is None or correction_rate >= 1.0) else "FAIL",
    })
    gates.append({
        "id": "memory_deduped", "value": memory_stats["deduped"], "target": ">= 1",
        "status": "PASS" if memory_stats["deduped"] >= 1 else "FAIL",
    })
    gates.append({
        "id": "memory_conflicts_resolved", "value": memory_stats["conflicts_resolved"], "target": ">= 1",
        "status": "PASS" if memory_stats["conflicts_resolved"] >= 1 else "FAIL",
    })
    gates.append({
        "id": "date_monotonic", "value": date_monotonic, "target": "== true（时间线日期不回退）",
        "status": "PASS" if date_monotonic else "FAIL",
    })
    gates.append({
        "id": "timeline_issues", "value": metrics["timeline_issues"], "target": "== 0（因果校验）",
        "status": "PASS" if metrics["timeline_issues"] == 0 else "FAIL",
    })
    gates.append({
        "id": "world_leak_from_excluded", "value": metrics["world_leak_from_excluded"],
        "target": "== 0（排除目录不注入）",
        "status": "PASS" if metrics["world_leak_from_excluded"] == 0 else "FAIL",
    })

    failed = [g for g in gates if g["status"] == "FAIL"]
    return {
        "project": "模拟群聊对话（AI Drama）",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "turns": turns,
        "metrics": metrics,
        "memory_stats": memory_stats,
        "gates": gates,
        "turn_summaries": turn_summaries,
        "conclusion": "FAIL" if failed else "PASS",
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# AI Drama 群聊回放验收报告",
        "",
        f"- 生成时间：{report['generated_at']}",
        f"- 回放轮次：{report['turns']}",
        f"- 结论：**{report['conclusion']}**",
        "",
        "| 门禁 | 实测 | 目标 | 判定 |",
        "|---|---|---|---|",
    ]
    for gate in report["gates"]:
        lines.append(f"| {gate['id']} | {gate['value']} | {gate['target']} | {gate['status']} |")
    lines += ["", "## 观测指标", ""]
    for key, value in report["metrics"].items():
        if key == "gates":
            continue
        lines.append(f"- `{key}` = {value}")
    lines += ["", "## 每轮摘要", "",
              "| 轮次 | 参与角色 | 世界已修正 | 日期回退 | LLM 调用数 |", "|---|---|---|---|---|"]
    for turn in report["turn_summaries"]:
        lines.append(f"| {turn['turn']} | {'、'.join(turn['participants'])} | "
                     f"{turn['world_corrected']} | {turn['date_reverted']} | {turn['llm_calls']} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    import tempfile

    stamp = time.strftime("%Y%m%d-%H%M%S")
    workdir = Path(tempfile.mkdtemp(prefix="ai-drama-replay-"))
    report = run_replay(workdir)
    report_dir = BACKEND_ROOT / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / f"replay_{stamp}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = render_markdown(report)
    (report_dir / f"replay_{stamp}.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"[report] {report_dir / f'replay_{stamp}.md'}")
    print(f"[exit] {0 if report['conclusion'] == 'PASS' else 1}")
    return 0 if report["conclusion"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
