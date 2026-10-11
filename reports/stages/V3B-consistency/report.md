# AI Drama · 阶段报告 · V3-B 观测与长程一致性

- 阶段：V3-B（覆盖 V3 迭代 3–4b）
- 状态：✅ 已完成
- 日期：2026-10-11
- 架构说明：`reports/stages/V3B-consistency/architecture.md`

## 1. 目标
让每一轮可观测（谁被调用、多久、花多少 token），并让长程叙事**不自我矛盾**（时间不回退、事件因果成立、记忆不重复不打架）。

## 2. 交付物
| 子项 | 内容 | 文件 |
|---|---|---|
| 每轮调用图与耗时 | 每次 LLM 调用记录 `kind/agent/role/duration_ms/ok/tokens`；落盘 `turns.jsonl` | `backend/director.py`、`backend/memory.py` |
| 日期只进不退 | `WorldState.try_set_date`；回退/非法日期被拒并记 `date_reverted` | `backend/world.py`、`backend/director.py` |
| 事件流因果校验 | `validate_timeline`：日期回退 / 同日内时段倒流 / 空事件 / 逐字重复 | `backend/world.py` |
| 记忆治理 | 去重（近重复合并）+ 冲突消解（同句不同值保留较新）+ 上限 80 | `backend/memory_ops.py` |
| 查询接口 | `GET /turns`、`GET /metrics`（含 `timeline_issues`） | `backend/main.py`、`backend/metrics.py` |

## 3. 测试方法
- L1：`test_director.py`（调用图/日期单调/场外隔离）、`test_world.py`（因果校验）、`test_memory_ops.py`、`test_metrics.py`。
- L2：`python -m backend.eval.replay` 硬门禁 `date_monotonic`、`timeline_issues`、`memory_deduped`、`memory_conflicts_resolved`。

## 4. 结果
| 门禁 | 实测 | 目标 | 判定 |
|---|---|---|---|
| date_monotonic | true | = true | PASS |
| timeline_issues | 0 | = 0 | PASS |
| memory_deduped | ≥1 | ≥1 | PASS |
| memory_conflicts_resolved | ≥1 | ≥1 | PASS |
| 全量 pytest | 47 passed | exit 0 | PASS |

**测试轮次**：首次 `timeline_issues=18`（复现了 FakeLLM 逐字重复事件的真实问题）→ 改为"导演随用户输入变化事件"后 PASS（1 次修复）。

## 5. 边界
- 冲突消解是**精确规则**（掩码后完全相同、取值不同才判冲突）；语义级矛盾（住北京/上海）保留并可人工编辑。
- 事件重复按"日期+时段+事件"逐字判定。
