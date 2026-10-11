# AI Drama · 架构说明 · V3-D 工程化与可插拔 LLM

> 报告：`reports/stages/V3D-engineering/report.md`

## 1. 组件与职责
| 组件 | 职责 | 文件 |
|---|---|---|
| llm 工厂 | `create_llm(config, provider) -> LLMClient`；满足 `LLMProtocol` | `backend/llm.py` |
| LLMClient | 按 provider 解析 `(base_url, api_key, model)`，发起 OpenAI 兼容请求，采集 usage | `backend/llm_client.py` |
| Config | 多后端配置 `llm_providers` + 当前 `provider`；`resolve_llm()`；安全持久化 | `backend/config.py` |
| exporter | 会话导出 Markdown / JSON | `backend/exporter.py` |
| 容器 | app 服务 + eval 服务（离线回放） | `Dockerfile`、`compose.yaml` |

## 2. provider 解析数据流
```
config.llm_providers = { "kimi": {base_url, api_key, model}, ... }
请求/会话 provider = "kimi"
        │
        ▼
LLMClient._connection() ── config.resolve_llm("kimi") ──▶ (https://kimi…/v1, key, kimi-8k)
        │
        ▼
httpx.post(base_url + "/chat/completions", model=…, messages=…)
```

## 3. 安全契约
- `/api/config` 返回 `providers:[{name, base_url, model, key_loaded}]`，**永不返回 api_key**。
- 密钥只写本地 `data/config.json`（git 忽略）或容器挂载卷。

## 4. 部署拓扑
```
docker compose up --build
  ├─ app  :8008   ← Web UI  |  volume ./data:/app/data
  └─ eval (profile: eval)   → python -m backend.eval.replay → ./reports
```

## 5. 扩展点
- 新增后端：在 `llm_providers` 增加一项即可，业务代码零改动（依赖 `LLMProtocol`）。
- 替换实现：离线回放注入 `FakeLLM`（同样满足协议）。
