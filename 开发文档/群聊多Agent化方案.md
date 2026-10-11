# 群聊多 Agent 化方案（规划）

> 参考：《剧情模拟工作流/群聊剧情模拟说明文档.md》（V1–V4 Agent 架构实现指南）。
> 该文档明确：群聊不止存在一个导演 Agent，而是由**多个 Agent 共同维护**，
> 剧情发展受**世界观（World）**与**人设（Character）**双重约束。

---

## 一、背景

当前实现中，群聊实际由“导演 + 各角色”维持，但**世界校验 / 时间线 / 记忆抽取 / 梗概**
这些职责都内联在 `DirectorAgent` 里，并未各自成为独立 Agent，偏离了文档的多 Agent 架构。

目标：把导演“包揽”的职责拆成**独立、一等注册、各有 System Prompt 的功能 Agent**，
多 Agent 共同维护群聊；同时 Agent 面板透明展示完整构成，且每个 Agent 可查看其提示词与记忆。

## 二、现状 vs 文档

| 文档概念 | 当前实现 | 差异 |
|---|---|---|
| Director Agent（导演：规划/调度/旁白） | ✅ 已有（role=director） | — |
| **World Agent**（维护时间/地点/规则/事件/限制，校验） | ⚠️ `world_check` 为导演内联方法，且默认关闭 | 需抽成独立 Agent |
| **Timeline Manager**（过去/当前/未来事件） | ⚠️ 仅为 `WorldState.timeline` 数据 | 需抽成独立 Agent |
| **Memory Manager**（短记忆+长记忆抽取） | ⚠️ `extract_memories` 内联 | 需抽成独立 Agent |
| **Synopsis Agent**（剧情梗概维护） | ⚠️ `update_synopsis` 内联 | 需抽成独立 Agent |
| Character Agents（人设约束发言） | ✅ 已有（role=character） | — |

## 三、目标构成（每轮群聊编排）

```
用户输入
 → Director 规划（旁白 / 参与者 / 时间 / 地点 / 事件）
 → World Agent   校验是否符合世界规则 / 时间 / 角色行为（反馈问题；场外隔离不入转录）
 → Timeline Manager  记录事件 → 写入时间线
 → Character Agents 依次发言（受世界观 + 人设约束）
 → Memory Manager  抽取长记忆（短记忆 = 转录本身）
 → Synopsis Agent  节流更新梗概
```

职责划分（对齐文档）：
- **Director**：剧情规划、调度角色、生成事件/旁白；**不能代替角色说话**。
- **World Agent**：维护时间/地点/世界规则/事件/限制；校验“事件是否符合世界规则、时间是否合理、
  角色行为是否符合环境”，发现错误返回修正建议。
- **Timeline Manager**：管理过去/当前/未来事件，写入并截断时间线。
- **Memory Manager**：短记忆（当前对话）+ 长记忆（永久事件/关系/承诺）抽取与落盘。
- **Synopsis Agent**：梗概节流更新。
- **Character Agents**：人设约束下自然发言。

## 四、分阶段实施

### 阶段1：抽出独立功能 Agent（本次建议，风险可控）
- 新增四个功能 Agent，各注册进 Registry、落盘、在 Agent 面板透明展示（含 role 徽标 + 提示词）：
  - `role="world"`：World Agent（世界校验，常驻）
  - `role="timeline"`：Timeline Manager（时间线/事件维护）
  - `role="memory"`：Memory Manager（长记忆抽取）
  - `role="synopsis"`：Synopsis Agent（梗概维护）
- 逻辑从 `director.py` 内联方法迁移到各自模块：
  - `backend/world_agent.py`、`backend/timeline.py`、`backend/memory_manager.py`、`backend/synopsis.py`
- `director.py` 瘦身为“规划 + 调度 + 旁白”，按顺序调用上述 Agent。
- 世界校验仍**场外隔离**（结果不写转录/记忆），保持现有行为不变。
- 世界观约束：World Agent 每轮以 `World rules` + 角色行为校验；人设约束：角色 System Prompt 不变。

### 阶段2（后续可选）：校验自动修正闭环
- 世界校验改为**默认启用**；
- 支持“导演按 World Agent 校验反馈**自动修正后再出轮**”，形成闭环。

## 五、涉及文件
- 新增：`backend/world_agent.py`、`backend/timeline.py`、`backend/memory_manager.py`、`backend/synopsis.py`
- 修改：`backend/director.py`（瘦身）、`backend/runtime.py`、`backend/session.py`、`backend/main.py`
- 前端：Agent 面板（功能性 Agent 徽标 + 提示词展示，衔接“详情展示提示词”）
- 文档：`开发文档/API接口参考.md`、`开发文档/V2开发文档.md`

## 六、取舍 / 注意
- 纯“把已有内联逻辑抽成独立 Agent + 面板透明”，不改变剧情结果；风险主要在**多文件编排一致性**，需回归测试群聊轮次。
- 多 Agent 会使单轮群聊的 LLM 调用数增加（导演 + 世界校验 + 记忆抽取 + 梗概），更耗 token，可接受。

## 七、验证
| 项 | 预期 |
|---|---|
| Agent 面板 | 展示 角色 + 导演 + 世界 + 时间线 + 记忆管理 + 梗概，带 role 徽标与提示词 |
| 群聊一轮 | 导演规划 → 世界校验（场外）→ 时间线记录 → 角色发言 → 记忆抽取 → 梗概节流，全流程跑通 |
| 场外隔离 | World 校验结果不写入转录 / 角色记忆 |
| 行为不变 | 原有群聊剧情结果与单角色/场外对话不受影响 |

---

# 实施记录（已完成 · 对应 V2 迭代9）

推荐方案（分层式「导演编排 + 关键功能 Agent 独立 + 数据组件轻量化」）已落地：

1. **新增功能 Agent**：`世界`(world)、`记忆管理`(memory)、`梗概`(synopsis) 注册进 Registry 并落盘，
   与 `导演`(director) 一起在 Agent 面板“功能 Agent”区展示；提示词与记忆可在详情界面查看/编辑。
2. **导演瘦身为编排核心**：规划/调度/旁白；按序调用 世界校验 → 角色发言 → 记忆抽取 → 梗概。
3. **世界校验默认开启 + 增量触发**：仅当 时间/地点/时段 变化时才调用（省 token），结果**场外隔离**不写转录/记忆。
4. **世界/记忆/梗概的调用使用各自功能 Agent 的 system_prompt**（可在详情界面编辑，改提示词即改行为）。
5. **时间线用数据组件**（`WorldState`），不新增 LLM Agent（纯记账）。
6. **参与者约束**：群聊只允许 `role=="character"` 参与；功能 Agent 不发言。
7. **Token 控制**：世界校验小上下文 + `max_tokens` 收紧 + 增量触发；记忆抽取有上限；梗概节流。

### 落地文件
`backend/runtime.py`、`backend/session.py`、`backend/director.py`（见 V2 迭代9）。

### 状态
- 阶段1（独立功能 Agent + 面板透明 + 默认开启校验）✅ 已完成。
- 阶段2（世界校验“自动修正闭环”：导演按校验反馈自动修正后再出轮）⏳ 未实施，可选后续迭代。

