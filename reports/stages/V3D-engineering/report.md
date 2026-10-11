# AI Drama · 阶段报告 · V3-D 工程化与可插拔 LLM

- 阶段：V3-D（覆盖 V3 迭代 6–7）
- 状态：✅ 已完成
- 日期：2026-10-11
- 架构说明：`reports/stages/V3D-engineering/architecture.md`

## 1. 目标
让项目可交付（容器化 + 导出）、可换模型后端（不锁死 DeepSeek）。

## 2. 交付物
| 子项 | 内容 | 文件 |
|---|---|---|
| 会话导出 | `GET /export?format=md\|json`（世界/梗概/时间线/角色记忆/转录） | `backend/exporter.py`、`backend/main.py` |
| 容器化 | `Dockerfile` + `compose.yaml`（app + eval 两个服务） | 根目录 |
| 可插拔 LLM | `llm_providers`（name→base_url/api_key/model）+ `provider`；`create_llm` + `LLMProtocol` | `backend/llm.py`、`backend/llm_client.py`、`backend/config.py` |
| 配置安全 | `/api/config` 只暴露 provider 名/base_url/model/`key_loaded`，**不返回原始 key** | `backend/main.py` |

## 3. 测试方法
- L1：`test_llm.py`（provider 解析/工厂/请求路由/不泄露 key）、`test_api.py`（导出接口）。
- 手动：`docker compose up --build`（需 Docker，未在本机执行）。

## ## 4. 结果
| 检查 | 结果 |
|---|---|
| provider 覆盖主配置 | PASS |
| 请求打到 provider 端点与模型 | PASS |
| `/api/config` 无原始 key | PASS |
| 导出 md/json | PASS |
| 全量 pytest | 47 passed |

**测试轮次**：`test_update_cleans_providers_and_resets_provider` 首跑失败（provider 校验早于 provider 表写入）→ 调整 `Config.update` 处理顺序后通过（1 次修复）。

## 5. 边界
- 未在本机执行 `docker compose`（环境无 Docker 守护）；镜像构建命令已文档化。
- provider 密钥持久化到 `data/config.json`（本地，`.gitignore` 排除）。
