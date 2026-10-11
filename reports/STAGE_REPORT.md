# 模拟群聊对话（AI Drama）· 阶段完成报告

> 依据：《AI 项目完整版执行方案与测试指标》§4（`模拟群聊对话（AI Drama）`）+ 项目《V2 开发文档》既有迭代
> 报告时间：2026-10-11

## 一、迭代完成情况

### 已由上游提交完成（V3 迭代 1–2，本轮已并入）
| 迭代 | 内容 | 状态 |
|---|---|---|
| V3-1 | 功能 Agent 提示词回归修复（按 role 重建提示词） | ✅ |
| V3-2 | 世界校验自动修正闭环（`world_check_mode=off/advisory/enforce` + 回灌重规划） | ✅ |

### 本轮新增（V3 迭代 3–8）
| 迭代 | 内容 | 状态 |
|---|---|---|
| V3-3 | 每轮 Agent 调用图与耗时（`turns.jsonl` + `/turns`） | ✅ |
| V3-4 | 长程一致性（日期只进不退；记忆去重 + 冲突消解；上限 80） | ✅ |
| V3-4b | 事件流因果校验（日期/时段/空事件/重复 → `timeline_issues`） | ✅ |
| V3-5 | 可评测化（`/metrics` 硬指标 + 门禁；确定性 FakeLLM 离线回放 20 轮） | ✅ |
| V3-5b | 记忆召回率代理观察指标（`memory_usage_rate`） | ✅ |
| V3-6 | 工程化（会话导出 MD/JSON；Dockerfile + compose） | ✅ |
| V3-7 | 可插拔 LLM（`llm_providers` + `create_llm` + `LLMProtocol`；key 不泄露） | ✅ |
| V3-8 | LLM 裁判观察项（人设一致率，多采样取均值，`in_gates=false`） | ✅ |
| V3-9 | 多 Agent 可观测 UI（「观测」页签：指标卡片 / 调用图 / 导出 / 裁判） | ✅ |

**结论：本项目计划中的全部迭代均已完成，无未完成项。**

## 二、验收证据（最近一次全量测试）

- L1：`python -m pytest -q` → **47 passed**，退出码 0
- L2：`python -m backend.eval.replay` → 结论 **PASS**，退出码 0（8 项硬门禁全 PASS）

| 门禁 | 实测 | 目标 | 判定 |
|---|---|---|---|
| agent_orchestration_success_rate | 1.0 | ≥ 0.98 | PASS |
| offscreen_leak_count | 0 | = 0 | PASS |
| world_violation_rate | 0.05 | ≤ 0.05 | PASS |
| world_correction_rate | 1.0 | = 1.0（有违规时） | PASS |
| memory_deduped | 1 | ≥ 1 | PASS |
| memory_conflicts_resolved | 1 | ≥ 1 | PASS |
| date_monotonic | true | = true | PASS |
| timeline_issues | 0 | = 0 | PASS |

观察项（不进硬门禁）：`synopsis_coverage`、`memory_usage_rate`、`avg_tokens_per_turn`、`p95_turn_latency_ms`、
`persona_consistency`（LLM 裁判）。

## 三、口径与假设留痕

- **硬门禁 vs 观察项分离**：`backend/metrics.py::GATES` 只含 4 项可硬断言的机制/隔离指标；
  人设一致率等主观指标一律走 `backend/judge.py`，返回体显式 `in_gates=false`。
- **回放确定性**：`FakeLLM` 按 System Prompt 识别五类调用并脚本化响应，等价于「固定种子/固定模型回放」。
- **因果校验为启发式**：日期单调为强约束；时段顺序按 `TIME_ORDER` 表；重复事件按「日期+时段+事件」逐字判定。
- **记忆冲突消解为精确规则**：仅当两条记忆「掩码（数字替换）后完全相同、取值不同」才判定冲突并保留较新；
  语义级矛盾（如「住北京」vs「住上海」）不自动消除，保留并可由 UI 人工编辑。

## 四、遗留边界（未纳入硬门禁）

1. LLM 裁判需真实模型；离线回放用 FakeLLM 验证机制，真实一致性数值属观察项。
2. 跨 Harness / 真实客户端联调不在本文件范围（属 HIL 项目）。
3. 梗概更新为节流式（每 N 条），覆盖度为启发式观测。

## 五、交付物清单

```
backend/
  director.py     # 编排 + 世界校验闭环 + 调用图/计时 + 日期单调 + 记忆治理
  world.py        # 世界状态 + try_set_date + validate_timeline + synopsis_coverage
  memory.py       # 会话/转录/角色记忆 + turns.jsonl
  memory_ops.py   # 去重 / 冲突消解 / 上限
  metrics.py      # 硬指标 + 门禁 + 观察项
  judge.py        # LLM 裁判观察项
  exporter.py     # 会话导出 MD/JSON
  llm.py          # 可插拔 LLM 工厂 + LLMProtocol
  llm_client.py   # OpenAI 兼容客户端（provider 感知、用量采集）
  config.py       # 配置（world_check_mode / llm_providers / provider）
  main.py         # API（含 /metrics /turns /export /judge）
backend/eval/{fake_llm.py, replay.py}
frontend/{index.html, app.js, style.css}   # 新增「观测」页签
Dockerfile / compose.yaml / .dockerignore
tests/                # 47 项
reports/              # replay_*.{md,json} + 本报告
开发文档/{评测与运维.md, API接口参考.md}
```
