# AI Drama · 阶段报告 · V3-E 观测面板与 LLM 裁判

- 阶段：V3-E（覆盖 V3 迭代 8–9）
- 状态：✅ 已完成
- 日期：2026-10-11
- 架构说明：`reports/stages/V3E-observability/architecture.md`

## 1. 目标
把硬指标与调用图**呈现给用户**（多 Agent 可观测），并提供**主观质量**的观察通道（LLM 裁判），
同时严格保证裁判**不进入硬门禁**。

## 2. 交付物
| 子项 | 内容 | 文件 |
|---|---|---|
| LLM 裁判 | `judge_persona_consistency` / `judge_session`：多采样取均值 + 标准差，`in_gates=false` | `backend/judge.py` |
| 裁判接口 | `POST /judge?samples=N` | `backend/main.py` |
| 裁判提示词 | 评分裁判 system/user 提示词 | `backend/prompts.py` |
| 观测 UI | 右栏「观测」页签：指标卡片（PASS/FAIL 徽标）+ 调用图 + 导出 + 裁判按钮 | `frontend/{index.html,app.js,style.css}` |

## 3. 测试方法
- L1：`test_judge.py`（均值/非法输出降级/不进门禁）、`test_api.py`（观测页签存在、裁判接口 200）。
- L2：回放门禁不受裁判影响（`GATES` 不含裁判指标）。

## 4. 结果
| 检查 | 结果 |
|---|---|
| 多采样均值 + stdev | PASS |
| 非法/失败输出降级为 None | PASS |
| `persona_consistency` 不在 `GATES` | PASS |
| 观测页签元素存在 | PASS |
| 前端语法 | `node --check app.js` 通过 |
| 全量 pytest | 47 passed |

**测试轮次**：`test_api.py` 中一次编辑误删了记忆测试的函数头，导致解析失败 → 立即修正（1 次修复）。

## 5. 边界
- 裁判需真实模型；离线回放用 FakeLLM 只验证**机制**。
- 观测面板数据来自 `/metrics` 与 `/turns`，不额外调用 LLM（裁判除外，按需触发）。
