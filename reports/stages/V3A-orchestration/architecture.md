# AI Drama · 架构说明 · V3-A 编排与闭环

> 报告：`reports/stages/V3A-orchestration/report.md`；整机架构图：`.archify/architecture-ai-drama-v3-20261011-031500/ai-drama-v3-architecture.html`

## 1. 组件与职责
| 组件 | 职责 | 文件 |
|---|---|---|
| Director Agent | 本轮规划（旁白/角色/时间/地点/事件）、编排、闭环修正 | `backend/director.py` |
| World Agent | 校验本轮剧情是否符合世界规则，返回 issues | 同文件 `world_check` |
| RuntimeManager | Agent 创建/暂停/恢复/销毁 + 按 role 重建提示词 | `backend/runtime.py` |
| Registry | 角色/导演/功能 Agent 实例表 | `backend/registry.py` |

## 2. 一轮群聊数据流
```
用户输入
  │
  ▼
导演 Agent(_director_plan) ── chat_json ──▶ 规划 JSON
  │                                    ▲
  ▼                                    │ 反馈重规划
世界校验(world_check, 仅状态变化触发) ──┘  (enforce)
  │  ok
  ▼
写用户 + 导演旁白 → 逐角色发言 → 记忆抽取 → 梗概节流 → 落盘
```

## 3. 校验闭环伪代码
```
issues = world_check(plan)
for attempt in 0..max_retries:
    if not issues or mode != "enforce": break
    revised = director_plan(revision="修正: " + issues)
    plan = parse(revised); issues = world_check(plan)
```
- `world_check_mode`：off / advisory / enforce；`world_check_retries` 上限 2。
- 校验反馈只进入模型消息，**不写入转录、不写入记忆**。

## 4. 关键契约
- `world_check(event, narration, participants) -> list[str]`（空 = 合规）。
- 修正结果随返回体 `world_corrected` / `world_check_initial_issues` / `world_check_issues` 暴露。

## 5. 边界
- 闭环只做"重规划"，不做无限重试；超出 retries 即以当前结果出轮并记录。
- 提示词单源化：编辑 Agent 提示词即影响群聊（可直接在详情界面查看）。
