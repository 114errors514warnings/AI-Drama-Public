# AI Drama · 群聊剧情模拟系统（V1–V4）

基于 DeepSeek 的多 Agent 群聊剧情模拟系统。实现了需求文档《群聊剧情模拟说明文档.md》中
V1（动态角色 Agent）→ V2（Agent Registry）→ V3（Agent Runtime Manager）→ V4（世界模拟系统）
的全部功能，并提供 Web UI 交互。

## 功能概览

| 版本 | 功能 | 本系统中的实现 |
|---|---|---|
| V1 | 动态角色 Agent | Character Selector → 知识库检索 → Prompt Builder → LLM 回复（单角色模式） |
| V2 | Agent Registry | 每个角色 = 独立 Agent 实例（独立资料/记忆/状态/关系/情感），Character Factory 按需实例化 |
| V3 | Runtime Manager | create / destroy / pause / resume 完整生命周期，UI 面板可操作 |
| V4 | 世界模拟 | Director Agent（导演）+ World Agent（世界校验）+ Timeline（时间线）+ Event System（事件流）+ Memory Manager（长/短期记忆） |

## 核心设计

### 多群聊并行 · 世界观彻底隔离（从根源解决记忆混淆）
- 允许多个群聊会话**同时运行**，每个会话 = 一个知识库 = **一套完全独立的 Agent 集合**
  （各自的 Director、Registry、World、Timeline、Memory）。
- 切换会话只切换 UI 视图，**不销毁任何数据**；不同世界的 System Prompt、检索索引、
  对话历史、记忆文件互不混用，LLM 不可能串世界观。
- 会话按知识库路径创建，一个知识库即一个世界；可在 UI 中随意新建/切换/显式删除。

### 记忆持久化到"对应角色的记忆库"
```
data/sessions/<会话ID>/
├── session.json           # 会话元信息 + 世界状态 + 时间线 + 事件流
├── transcript.json        # 群聊完整记录（短期记忆来源，取最近 N 轮）
└── characters/<角色名>.json   # 该角色专属记忆库：
                              # 角色资料快照 + 情感状态 + 人际关系 + 长期记忆
```
- 每轮对话后自动保存；暂停/销毁 Agent 前也会保存。
- **切换会话 / 重启服务都不清空、不删除记忆**。
- 唯一删除记忆的途径是用户在 UI 中显式删除整个会话（二次确认）。

### API Key 安全
- Key 只保存在**内存**与本地 `data/config.json`（UI 保存时），接口只返回掩码（`sk-****…****`）。
- 也支持**环境变量**：`AIDRAMA_API_KEY` / `AIDRAMA_BASE_URL` / `AIDRAMA_MODEL`（优先级高于配置文件，适合容器部署，不必落盘）。
- 不写入代码、不打日志、不写入任何数据文件（除非你在 UI 中主动保存）。

## 快速开始

### 方式一：直接体验示例（推荐先跑这个）

仓库自带一个**校园生活示例知识库**（合成角色 A / B / C），无需自备素材：

```bash
python -m pip install -r requirements.txt
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8008
```

打开 `http://127.0.0.1:8008` → 左侧「＋ 新建群聊」→ **知识库路径**填 `examples/demo-kb` 的绝对路径
→ 在「模型配置」里填入你自己的 API Key → 回群聊发一句话即可。

> 目录约定与角色卡模板见 [`examples/README.md`](examples/README.md)；做一个自己的角色卡见
> [`examples/character-template.md`](examples/character-template.md)。

### 方式二：源码运行

```bash
# 1. 安装依赖
python -m pip install -r requirements.txt

# 2. 启动服务（默认端口 8008）
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8008

# 3. 打开浏览器
#    http://127.0.0.1:8008

# 4. 停止服务：在启动窗口按 Ctrl+C
```

新建会话时需**手动选择**知识库目录（无默认路径），可在路径框右侧点「📂 浏览」预览并选择。
知识库按 **Character / Memory / World** 三个文件夹读取：
- `Character/`：角色档案，严格按 md、按文件名归档为对应角色；
- `Memory/`：角色长期记忆，按文件名归到对应角色，创建角色时作为其初始长期记忆；
- `World/`：世界观背景与规则；建立 `背景/`、`词条/`、`文风/` 子目录后自动启用「常驻 + 关键词词条」机制；
三目录缺失时，新建会话会自动创建。

## 使用说明

1. **新建群聊**：左侧「＋ 新建群聊」，填会话名 + 知识库路径（一个知识库 = 一个世界，完全隔离）。
2. **聊天**：群聊模式由导演自动调度 1~4 个角色依次发言（含旁白）；单角色模式可指定角色一对一。
3. **Agent 生命周期**：右侧「角色 / Agent」面板可对每个角色执行 暂停 / 恢复 / 销毁。
4. **世界面板**：查看当前时间、地点、事件时间线、世界规则摘要。
5. **模型配置**：模型名、temperature、世界校验（World Agent，开启后每轮多一次一致性校验）。

## API 摘要

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/sessions` | 列出所有会话 |
| POST | `/api/sessions` | 新建会话（name + kb_path） |
| POST | `/api/sessions/{id}/activate` | 切换活跃会话（不销毁数据） |
| DELETE | `/api/sessions/{id}` | 显式删除会话（连同记忆） |
| POST | `/api/sessions/{id}/chat` | 群聊模式（导演调度） |
| POST | `/api/sessions/{id}/chat/single` | 单角色模式（V1） |
| GET | `/api/sessions/{id}/agents` | Agent Registry 状态 |
| POST | `/api/sessions/{id}/agents/{action}` | create / destroy / pause / resume |
| GET | `/api/sessions/{id}/world` | 世界状态 + 时间线 + 事件 |
| GET | `/api/sessions/{id}/transcript` | 群聊记录 |
| GET/POST | `/api/config` | 模型配置（key 仅返回掩码） |
| GET | `/api/sessions/{id}/metrics` | 会话硬指标 + 门禁判定（V2 新增） |
| GET | `/api/sessions/{id}/turns` | 每轮编排明细（Agent 调用图 / 耗时）（V2 新增） |
| GET | `/api/sessions/{id}/export?format=md\|json` | 导出会话（V2 新增） |

---

## V3 迭代（本轮新增）

### 1. 世界校验自动修正闭环（`world_check_mode`）
- `off`（关闭）/ `advisory`（仅记录，默认）/ `enforce`（校验不通过 → 问题回灌导演重规划，闭环修正）。
- `world_check_retries` 控制最大修正轮数（默认 2）。
- 校验反馈全程**场外隔离**，绝不写入群聊转录 / 角色记忆。

### 2. 每轮 Agent 调用图与耗时
- 每一轮的每次 LLM 调用（导演规划 / 世界校验 / 角色发言 / 记忆抽取 / 梗概）都记录
  `kind / agent / role / duration_ms / ok / prompt_tokens / completion_tokens`；
- 落盘 `data/sessions/<会话>/turns.jsonl`（追加式），经 `/turns` 查看。

### 3. 长程一致性
- **时间只进不退**：导演给出的故事日期若早于当前日期将被拒绝（`date_reverted`），时间线严格单调。
- **记忆治理**：抽取到的长期记忆自动**去重**（近重复合并）与**冲突消解**（同一句不同取值保留较新），
  上限 80 条；人工编辑记忆（`PUT /character/memory`）走同一套治理逻辑。

### 4. 可评测化
- `/metrics` 输出硬指标：`agent_orchestration_success_rate`、`world_violation_rate`、
  `world_correction_rate`、`offscreen_leak_count`、`avg_tokens_per_turn`、`p50/p95_turn_latency_ms`、
  `synopsis_coverage` 等，并给出门禁判定（PASS/FAIL/BASELINE）。
- **离线回放评测**：`python -m backend.eval.replay` 用确定性 FakeLLM 固定剧本回放 20 轮，
  不触网、不消耗 token，产出 `reports/replay_*.md/.json`，退出码即 CI 门禁。

### 5. 工程化
- `Dockerfile` + `compose.yaml`：`docker compose up --build` 一键启动；`docker compose run --rm app python -m backend.eval.replay` 一键评测。
- 会话导出 Markdown / JSON。

### 6. 可插拔 LLM（OpenAI 兼容 provider）
- 配置支持多后端 `llm_providers`（`name → {base_url, api_key, model}`）与当前 `provider`；
- 统一由 `backend/llm.py::create_llm` 构造（实现 `LLMProtocol`），换后端不改业务代码；
- `/api/config` 只暴露 provider 名、`base_url`、`model` 与「是否已配置 key」，**绝不返回原始 key**。

### 7. LLM 裁判观察项（人设一致率）
- `POST /api/sessions/{id}/judge` 对最近发言的角色做人设一致率评分；
- 多采样取均值 + 标准差；返回体显式 `observation=true / in_gates=false`，**不进入硬门禁**；
- 裁判失败/输出非法时降级为 `None`（BASELINE），不影响主流程。

### 8. 多 Agent 可观测 UI
- 右栏新增「观测」页签：硬指标卡片（带 PASS/FAIL 徽标）、最近轮次的 Agent 调用图与耗时、
  导出（MD/JSON）与「人设裁判」按钮。

## 测试与验收

```powershell
python -m pytest -q                      # L1：47 项功能/单元测试
python -m backend.eval.replay           # L2：离线回放 + 硬门禁，产出 reports/replay_*.md/.json
```

门禁（任一 FAIL → 退出码 1）：

| 门禁 | 目标 | 说明 |
|---|---|---|
| `agent_orchestration_success_rate` | ≥ 0.98 | 一轮群聊完整跑通的比例 |
| `offscreen_leak_count` | = 0 | 场外内容写入转录/记忆的次数（硬断言） |
| `world_violation_rate` | ≤ 0.05 | 世界规则违规轮次比例 |
| `world_correction_rate` | = 1.0（有违规时） | 违规被自动修正的比例 |
| `memory_deduped` / `memory_conflicts_resolved` | ≥ 1 | 记忆去重 / 冲突消解生效 |
| `date_monotonic` | = true | 时间线日期不回退 |
| `timeline_issues` | = 0 | 事件流因果校验（日期/时段/空事件/重复） |

观察项（不进硬门禁）：`synopsis_coverage`、`memory_usage_rate`（记忆召回率代理）、`p95_turn_latency_ms`、
`avg_tokens_per_turn`、以及 LLM 裁判的 `persona_consistency`。

> Docker 部署时，API Key 用环境变量传入即可：`AIDRAMA_API_KEY`（或挂载 `data/config.json` 的 `api_key` 字段）。
> 详见 `开发文档/公共化改造方案.md`。

