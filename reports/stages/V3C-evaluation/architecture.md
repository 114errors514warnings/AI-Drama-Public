# AI Drama · 架构说明 · V3-C 可评测化

> 报告：`reports/stages/V3C-evaluation/report.md`

## 1. 组件与职责
| 组件 | 职责 | 文件 |
|---|---|---|
| metrics | 从 `turns.jsonl` + `transcript` + `world` + `registry` 汇总硬指标与观察项，并给门禁判定 | `backend/metrics.py` |
| FakeLLM | 按 System Prompt 识别五类调用并脚本化响应（导演/世界/记忆/梗概/裁判） | `backend/eval/fake_llm.py` |
| replay | 造隔离 KB + 会话，回放 N 轮，统计门禁并产出 `reports/replay_*.{md,json}` | `backend/eval/replay.py` |

## 2. 回放数据流
```
临时 KB(Character/Memory/World) ─┐
                                 ▼
WorldSession(FakeLLM) ──run_group_turn × 20──▶ turns.jsonl ──▶ session_metrics()
                                                                     │
                                                                     ▼
                                            硬门禁判定 + reports/replay_*.md/json + exit code
```

## 3. 指标分层
- **硬门禁（GATES）**：机制/隔离/一致性四类，均可离线硬断言。
- **观察项**：主观/启发式（梗概覆盖、记忆召回代理、延迟、token），只报告不判定。
- **裁判观察项**：见 V3-E。

## 4. 关键契约
- `session_metrics(session, turns=None) -> dict`：`{指标…, gates:{…}}`。
- `run_replay(workdir, turns=20) -> report`；`main()` 退出码 = 是否全 PASS。
- 门禁阈值全部集中在 `metrics.GATES`，报告与测试同源。
