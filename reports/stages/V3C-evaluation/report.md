# AI Drama · 阶段报告 · V3-C 可评测化

- 阶段：V3-C（覆盖 V3 迭代 5–5b）
- 状态：✅ 已完成
- 日期：2026-10-11
- 架构说明：`reports/stages/V3C-evaluation/architecture.md`

## 1. 目标
把"剧情质量"里**可硬断言**的部分变成可自动判定的指标与门禁；并给主观指标留**观察项**通道。

## 2. 交付物
| 子项 | 内容 | 文件 |
|---|---|---|
| 会话硬指标 | 编排成功率 / 场外泄漏 / 世界违规率 / 修正率 / 因果 / token / 延迟 | `backend/metrics.py` |
| 硬门禁 | `GATES`：`agent_orchestration_success_rate`、`offscreen_leak_count`、`world_violation_rate`、`timeline_issues` | 同文件 |
| 观察项 | `synopsis_coverage`、`memory_usage_rate`、`p95_turn_latency_ms`、`avg_tokens_per_turn` | 同文件 |
| 离线回放 | 确定性 FakeLLM 固定剧本回放 20 轮，产出报告 + 退出码 | `backend/eval/{fake_llm.py,replay.py}` |

## 3. 测试方法
- L2：`python -m backend.eval.replay`（8 项硬门禁，退出码即 CI）。
- L1：`test_metrics.py`（口径/门禁）、`test_memory_ops.py`、`test_api.py`。

## 4. 结果
| 门禁 | 实测 | 目标 | 判定 |
|---|---|---|---|
| agent_orchestration_success_rate | 1.0 | ≥0.98 | PASS |
| offscreen_leak_count | 0 | =0 | PASS |
| world_violation_rate | 0.05 | ≤0.05 | PASS |
| world_correction_rate | 1.0 | =1.0 | PASS |
| memory_deduped / conflicts_resolved | 1 / 1 | ≥1 | PASS |
| date_monotonic / timeline_issues | true / 0 | =true / =0 | PASS |

**测试轮次**：均在一次内通过（因果门禁的失败已记于 V3-B）。

## 5. 边界
- LLM 裁判不进硬门禁（见 V3-E）。
- 回放用 FakeLLM，验证**机制**；真实一致性数值为观察项。
