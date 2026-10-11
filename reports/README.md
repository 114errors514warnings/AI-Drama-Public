# AI Drama · 报告索引

> 约定：每个已完成阶段产出**两份独立文档** —— `report.md`（阶段报告）与 `architecture.md`（架构说明）。
> 架构图由本地 Archify 生成。

## 项目级
- `STAGE_REPORT.md` —— 全项目阶段完成总报告

## 阶段文档
| 阶段 | 覆盖迭代 | 报告 | 架构说明 |
|---|---|---|---|
| V3-A 编排与闭环 | V3-1, V3-2 | [report](stages/V3A-orchestration/report.md) | [architecture](stages/V3A-orchestration/architecture.md) |
| V3-B 观测与长程一致性 | V3-3, V3-4, V3-4b | [report](stages/V3B-consistency/report.md) | [architecture](stages/V3B-consistency/architecture.md) |
| V3-C 可评测化 | V3-5, V3-5b | [report](stages/V3C-evaluation/report.md) | [architecture](stages/V3C-evaluation/architecture.md) |
| V3-D 工程化与可插拔 LLM | V3-6, V3-7 | [report](stages/V3D-engineering/report.md) | [architecture](stages/V3D-engineering/architecture.md) |
| V3-E 观测面板与 LLM 裁判 | V3-8, V3-9 | [report](stages/V3E-observability/report.md) | [architecture](stages/V3E-observability/architecture.md) |

## 验收产物
- `replay_*.md` / `replay_*.json` —— 每次 `python -m backend.eval.replay` 的离线回放报告
- 门禁：编排成功率 / 场外泄漏 / 世界违规率 / 修正率 / 记忆去重与冲突 / 时间线因果

## 架构图（Archify）
- `..\.archify\architecture-ai-drama-v3-20261011-031500\ai-drama-v3-architecture.html`
  （Archify `finalize` 全部闸门通过：validate / deliver / check / browser-check）
