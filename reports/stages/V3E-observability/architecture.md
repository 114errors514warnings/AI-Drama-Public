# AI Drama · 架构说明 · V3-E 观测面板与 LLM 裁判

> 报告：`reports/stages/V3E-observability/report.md`；整机架构图：`.archify/architecture-ai-drama-v3-20261011-031500/ai-drama-v3-architecture.html`

## 1. 组件与职责
| 组件 | 职责 | 文件 |
|---|---|---|
| judge | 人设一致率多采样评分，降级安全，永进门禁 | `backend/judge.py` |
| metrics | 硬指标 + 门禁 + 观察项 | `backend/metrics.py` |
| 前端观测页签 | 渲染指标卡片 / 调用图 / 导出 / 裁判 | `frontend/app.js`、`frontend/index.html`、`frontend/style.css` |

## 2. 观测前端数据流
```
「观测」页签点击
   ├─ GET /metrics ──▶ 指标卡片(带 gates 徽标)
   ├─ GET /turns?limit=30 ──▶ 最近轮次 + Agent 调用图/耗时
   ├─ GET /export?format=md|json ──▶ 下载
   └─ POST /judge?samples=3 ──▶ 裁判观察项(标注 in_gates=false)
```

## 3. 裁判边界（架构级约束）
```
硬门禁 GATES = {编排成功率, 场外泄漏, 世界违规率, 时间线因果}
观察项/裁判  = {梗概覆盖, 记忆召回代理, 延迟, token, 人设一致率}
       ▲
       └─ 二者物理隔离：judge 模块不 import metrics.GATES，报告显式 in_gates=false
```

## 4. 关键契约
- `judge_session(session, samples, max_characters) -> {observation:true, in_gates:false, value, samples, stdev, model, characters[], note}`。
- 观测 UI 只读接口，不写会话状态。

## 5. 测试与质量
- 前端 `node --check app.js` 通过；观测页签元素由 `test_frontend_exposes_observability_tab` 守护。
