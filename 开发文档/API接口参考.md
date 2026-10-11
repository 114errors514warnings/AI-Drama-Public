# AI Drama 群聊剧情模拟系统 — API 接口参考

> 服务地址：`http://127.0.0.1:8008`
> 请求/响应均为 JSON（除前端静态文件）。`{sid}` 为会话 ID。

## 一、配置

### GET /api/config — 读取配置
返回：model / temperature / world_check / world_check_mode / world_check_retries /
time_format / time_fallback / base_url / masked_key（掩码）/ key_loaded / key_file / config_error

### POST /api/config — 更新配置
请求体（均为可选）：
```json
{
  "model": "deepseek-chat",
  "temperature": 0.7,
  "world_check_mode": "advisory",
  "world_check_retries": 2,
  "time_format": "date",
  "time_fallback": "时间未定",
  "base_url": "https://api.deepseek.com",
  "api_key": "sk-****（非空时更新，空串忽略）"
}
```
`world_check_mode` ∈ `off`（关闭）/ `advisory`（仅记录问题，默认）/ `enforce`（校验不通过则反馈导演闭环修正，最多 `world_check_retries` 次）。
返回：同 GET /api/config。安全：完整 Key 仅单向提交，接口只回掩码。

### POST /api/config/test — 测试连接
用当前 Key 发送一次极小请求（`max_tokens=10`）。
返回：`{"ok": true, "reply": "…"}`；失败返回 502。

### GET /api/kb/browse — 浏览文件夹（预览并选择知识库路径）
- `?path=` 为空 → 返回“此电脑”各盘符；`?path=D:\kb` → 返回该目录下的子文件夹。
- 返回：`{"root": bool, "path": 当前目录, "parent": 上级目录, "items": [{name, path, is_dir}]}`

### GET /api/kb/validate — 校验知识库目录
- `?path=<根目录绝对路径>`；返回：
  `{"path", "exists", "is_dir", "missing_dirs": ["Character"|"Memory"|"World", …], "valid"}`
- 三目录缺失可在新建会话时自动补建。

### POST /api/kb/native-pick — 弹系统「资源管理器风格」选择文件夹对话框
- 由**同机后端**用系统自带 `powershell.exe`（5.1）+ `Add-Type` 封装 COM `IFileOpenDialog`
  （`FOS_PICKFOLDERS`）弹出**资源管理器风格**文件夹选择窗口（顶部地址栏/可编辑路径输入框），
  返回所选**绝对路径** `{"path": "<绝对路径>"}`。
- 浏览器无法提供磁盘绝对路径，故走后端弹出。弹不出/用户取消 → 500（前端 tips 报错）。

## 二、会话管理

### GET /api/sessions — 会话列表
返回：`{"active_id": "...", "sessions": [{id, name, kb_path, world_name, characters, transcript_len, time, location}]}`

### POST /api/sessions — 新建会话
请求体：`{"name": "会话名", "kb_path": "知识库目录"}`（kb_path 必填）
返回：新会话 info；知识库不存在返回 400。

### POST /api/sessions/{sid}/activate — 切换活跃会话
切换只改视图与活跃指针，**不销毁任何数据**。

### DELETE /api/sessions/{sid} — 删除会话
连带删除该世界全部角色记忆与对话记录（前端二次确认）。

### GET /api/sessions/{sid}/info — 会话详情
返回：id / name / kb_path / world_name / characters / transcript_len / time（按当前时间格式）/ location

### PATCH /api/sessions/{sid} — 重命名
请求体：`{"name": "新名称"}`；返回最新 info。

### POST /api/sessions/{sid}/clear — 清空对话
清空转录并重置世界时间线/日期，**保留角色长期记忆**；返回最新 info。

## 三、角色

### GET /api/sessions/{sid}/characters — 角色列表
返回：`{"characters": [{name, status, profile_preview}], "world": {world_name, root, characters, lore_topics}}`

### GET /api/sessions/{sid}/character?name=角色名 — Agent / 人物详情
- 名字通过**查询参数**传递（可为任意字符，含 `/`、空格等均安全）
- 返回：`name / role / status / profile(全文) / emotion_state / relationships / long_memory / skills / system_prompt / world_name`
- 角色以**文档文件名**为规范名，支持标题别名解析（如"代号B"→"B（代号B）"、"C"→"C（代号C）"）
- **功能 Agent（导演）同样可查**：`?name=导演` 从 Registry 返回其真实状态/资料/记忆（profile 回退到 agent.profile）

### PUT /api/sessions/{sid}/character/memory?name=Agent名 — 更新长期记忆
- 查询参数传名；请求体：`{"long_memory": ["条目1", "条目2", …]}`（整表替换）
- 自动去空/去重/上限 80 条，按 Agent 类型重建 System Prompt 并落盘；返回 `{"ok": true, "long_memory": [...]}`
- **功能 Agent（导演）同样可写**（走 `get_or_create_agent` + `refresh_prompt`）

## 四、对话

### POST /api/sessions/{sid}/chat — 群聊模式（导演调度）
请求体：`{"message": "用户输入"}`（session_id 可空，默认活跃会话）
返回：
```json
{
  "user_input": "...",
  "narration": "导演场景描述",
  "location": "地点",
  "date": "2026-08-30",
  "time_of_day": "白天",
  "time": "2026年8月30日",
  "event": "事件摘要",
  "participants": ["角色名"],
  "skipped": [],
  "replies": [{"speaker": "角色名", "content": "..."}],
  "memories_extracted": {"角色名": 条数},
  "world_check_mode": "advisory|enforce|off",
  "world_check_issues": [],
  "world": {…世界状态…}
}
```

### POST /api/sessions/{sid}/chat/agent — 单Agent对话（场外）
请求体：`{"message": "...", "agent_name": "Agent 名"}`（可为角色或功能 Agent，如「导演」）；
返回 `{"speaker": "Agent 名", "reply": "..."}`。**不写入群聊转录、不抽取记忆、不更新梗概。**

### GET /api/sessions/{sid}/side_chat/{agent} — 某 Agent 的场外对话记录
返回：`{"side_chat": [{"role": "user|assistant", "speaker": "...", "content": "..."}]}`（最近 200 条）

## 五、Agent Registry / Runtime（V2/V3）

### GET /api/sessions/{sid}/agents — Agent 列表
返回：`{"agents": [{name, status, emotion, relationships, long_memory_count}], "characters_in_kb": [...]}`

### POST /api/sessions/{sid}/agents/create — 创建 Agent
请求体：`{"name": "角色名"}`；返回 `{"ok": true, "agent": {name, status}}`；知识库无此角色返回 404。

### POST /api/sessions/{sid}/agents/{action} — 生命周期操作
`action` ∈ `pause / resume / destroy`；请求体：`{"name": "角色名"}`。
destroy 前保存记忆并标记 destroyed；resume 可重建（恢复历史记忆）。

## 六、世界 / 梗概 / 转录

### GET /api/sessions/{sid}/world — 世界状态
返回：world_name / start_date / date / time_of_day / time（按当前格式）/
location / rules / events / timeline / synopsis

### POST /api/sessions/{sid}/synopsis — 手动刷新剧情梗概
返回：`{"synopsis": "..."}`；未设置 Key 等失败返回 502。

### GET /api/sessions/{sid}/transcript — 群聊记录
返回：`{"transcript": [{"role": "user|narrator|assistant", "speaker": "...", "content": "..."}]}`（最近 300 条）

## 八、可观测 / 评测 / 导出（V3 迭代 3–6 新增）

### GET /api/sessions/{sid}/metrics — 会话硬指标 + 门禁
返回：
- 硬指标：`agent_orchestration_success_rate`、`offscreen_leak_count`、`world_violation_rate`、
  `world_correction_rate`、`timeline_issues`
- 观察项：`synopsis_coverage`、`memory_usage_rate`、`avg_tokens_per_turn`、`p50/p95_turn_latency_ms`、
  `memories_total`、`characters_active`、`events`
- `gates`：`{指标: PASS | FAIL | BASELINE}`

### GET /api/sessions/{sid}/turns?limit=N — 每轮编排明细
返回 `{"turns": [...]}`；每条含 `calls`（Agent 调用图：agent / role / kind / duration_ms / ok / tokens）、
`latency_ms`、`world_issues`、`world_corrected`、`date_reverted`、`participants`、`memory_stats`。

### GET /api/sessions/{sid}/export?format=md|json — 会话导出
- `md` → `text/markdown`（含世界、梗概、时间线、角色记忆、转录）
- `json` → 结构化对象

### POST /api/sessions/{sid}/judge?samples=N — LLM 裁判（观察项）
对人设一致率多采样评分；返回 `observation=true`、`in_gates=false`、`value`、`samples`、`stdev`、`characters`，
以及 `ai_flavor`（文风裁判：1=像真人闲聊，0=明显 AI 腔）。
**仅观察，不进入硬门禁。**

## 九、提示词查看 / 编辑（V4 新增）

### PUT /api/sessions/{sid}/agents/prompt — 手动设置 Agent 提示词
请求：`{"name": "A", "system_prompt": "...", "lock": true}`
- 保存后 `prompt_locked=true`，该 Agent 的提示词不再被自动重建覆盖（记忆编辑/重启均保留）；
- `lock=false` 仅临时写入，下次自动重建即恢复。
返回：`{"ok": true, "name": "...", "prompt_locked": true}`

### DELETE /api/sessions/{sid}/agents/prompt?name=A — 恢复自动生成
解除手动覆盖并按角色卡/世界观重建。返回重建后的 `system_prompt` 与 `prompt_locked=false`。

### PUT /api/sessions/{sid}/world/rules — 覆盖世界背景（注入提示词）
请求：`{"rules": "..."}`；保存后立即对未锁定的 Agent 重建提示词。
返回：`{"ok": true, "rules_override": "..."}`

### DELETE /api/sessions/{sid}/world/rules — 清除世界背景覆盖
回退为知识库装载内容。返回：`{"ok": true, "rules": "...", "rules_override": ""}`

> `GET /api/sessions/{sid}/character` 新增 `prompt_locked`；
> `GET /api/sessions/{sid}/world` 新增 `rules_override` / `rules_from_kb` / `effective_rules`。

## 十一、调试 / 自检接口（TODO-4：群聊 + 单 Agent）

> 用途：复现「导演单聊返回规划 JSON」「场外讨论未被群聊规划继承」等问题。
> **默认只读或 dry-run，不写入转录 / 世界 / 场外记录**。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/sessions/{sid}/debug/group/preview?message=` | **群聊**：构建导演规划消息**但不调 LLM**；返回完整 `messages`、`system_prompt`、`system_prompt_requires_json`、`history_len`、`side_chat_included`(=false)、导演记忆、世界背景来源 |
| POST | `/api/sessions/{sid}/debug/group/plan` | **群聊**：真调用一次导演规划，返回 `raw` / `plan` / `output_is_json`；**不写任何状态** |
| GET | `/api/sessions/{sid}/debug/agent/messages?agent_name=&message=` | **单 Agent**：构建对话消息但不调 LLM；返回 `messages`、`system_prompt`、`system_prompt_requires_json`、`side_chat_len`（支持 导演/世界/记忆管理/梗概/角色） |
| POST | `/api/sessions/{sid}/debug/agent/turn` | **单 Agent**：真调用一次对话；body `{agent_name, message, commit}`，`commit=false`（默认）为 dry-run，**不写入场外记录** |
| GET | `/api/sessions/{sid}/debug/context?agent_name=` | 上下文自检：`side_chats` 各 Agent 条数、`side_chats_used_in_group_plan`(=false)、世界背景来源、导演/指定 Agent 提示词与单聊长度 |
| DELETE | `/api/sessions/{sid}/debug/side-chats?agent_name=` | 清空场外单聊（留空=清全部；便于测试隔离，不影响转录/记忆） |

**常用测试姿势**
```bash
# 1) 看导演单聊到底带了什么提示词（验证"回复是 JSON"的根因）
curl "http://127.0.0.1:8008/api/sessions/<sid>/debug/agent/messages?agent_name=%E5%AF%BC%E6%BC%94&message=hello"
# 2) 真跑一次单聊但不想留下记录
curl -X POST "http://127.0.0.1:8008/api/sessions/<sid>/debug/agent/turn" \
     -H "Content-Type: application/json" -d '{"agent_name":"导演","message":"聊聊剧情结构","commit":false}'
# 3) 看群聊规划是否引用了之前的场外讨论（应为 false）
curl "http://127.0.0.1:8008/api/sessions/<sid>/debug/context?agent_name=%E5%AF%BC%E6%BC%94"
```

> 既有的 `POST /api/sessions/{sid}/chat`（群聊整轮）与 `POST /api/sessions/{sid}/chat/agent`（单 Agent 对话）
> 仍是对应的"真实执行"入口，可与之配合对比。

## 十二、前端静态资源

- `GET /` → `frontend/index.html`（Web UI，含「观测」页签、提示词/轮次详情弹窗）
- `GET /app.js`、`GET /style.css` → 前端脚本与样式
