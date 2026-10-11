# AI Drama · 阶段报告 · V3-A 编排与闭环

- 阶段：V3-A（覆盖上游提交 V3 迭代 1–2）
- 状态：✅ 已完成
- 日期：2026-10-11
- 架构说明：`reports/stages/V3A-orchestration/architecture.md`

## 1. 目标
修复功能 Agent 提示词回归；把「世界校验」从"只看不改"升级为**自动修正闭环**，
让导演在收到 World Agent 反馈后重新规划再出轮。

## 2. 交付物
| 项 | 内容 | 文件 |
|---|---|---|
| 提示词回归修复 | `restore_agents` 按 `role` 统一重建提示词（导演/世界/记忆/梗概不再被角色 Prompt 覆盖） | `backend/runtime.py` |
| 导演提示词单源化 | 群聊调度版提示词为唯一来源，`run_group_turn` 读导演 Agent 的 `system_prompt` | `backend/runtime.py`、`backend/director.py`、`backend/prompts.py` |
| 校验闭环 | `world_check_mode=off/advisory/enforce` + `world_check_retries`；enforce 下问题回灌导演重规划 | `backend/director.py`、`backend/config.py`、`backend/main.py`、`frontend/` |
| 统计修正 | `to_info.characters` 只计角色；`clear_transcript` 一并重置梗概 | `backend/session.py` |

## 3. 测试方法
- L1：提示词按 role 重建、校验闭环行为。
- L2：见 `V3B/C` 的硬门禁（`world_violation_rate` / `world_correction_rate`）。
- 回归：`pytest`；`python -m backend.eval.replay`。

## 4. 结果
| 检查 | 结果 |
|---|---|
| 重启后功能 Agent 提示词正确 | PASS |
| enforce 下违规被闭环修正 | PASS（`world_correction_rate=1.0`） |
| 全量回归 | PASS |

## 5. 边界
- advisory = 仅记录；enforce = 回灌修正（默认最多 2 轮）。
- 校验反馈全程场外隔离，不写转录/记忆。
