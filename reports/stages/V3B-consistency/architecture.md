# AI Drama · 架构说明 · V3-B 观测与长程一致性

> 报告：`reports/stages/V3B-consistency/report.md`

## 1. 组件与职责
| 组件 | 职责 | 文件 |
|---|---|---|
| Director | 用 `_timed` 上下文管理器包裹每次 LLM 调用，累积调用图 | `backend/director.py` |
| WorldState | 世界状态 + 日期单调 + 时间线因果校验 + 梗概覆盖 | `backend/world.py` |
| memory_ops | 归一化 / 相似度 / 去重 / 冲突消解 / 上限 | `backend/memory_ops.py` |
| MemoryStore | 转录、角色记忆、`turns.jsonl` 追加与读取 | `backend/memory.py` |
| metrics | 会话级硬指标 + 门禁 + 观察项 | `backend/metrics.py` |

## 2. 观测数据流
```
一轮群聊
 ├─ director_plan  ─┐
 ├─ world_check     ├─▶ self._calls[]  ──▶ turns.jsonl ──▶ GET /turns
 ├─ character_reply │                    └─▶ session_metrics() ──▶ GET /metrics
 └─ memory_extract ─┘
```

## 3. 一致性规则（硬）
1. **日期单调**：`try_set_date(iso)` 仅接受 ISO 且不早于当前；否则返回 False 并记 `date_reverted`。
2. **因果校验**：`validate_timeline()` → `{missing_date, date_backwards, time_backwards, empty_event, duplicate_event}`；
   `TIME_ORDER` 定义同日内时段先后（凌晨<清晨<上午<白天<中午<下午<傍晚<晚上<深夜）。
3. **记忆治理**：`merge_facts(existing, incoming)`：
   - 相似度 ≥ 0.9 → 去重丢弃；
   - `mask_values(a)==mask_values(b)` 且不相等 → 冲突，保留较新；
   - 否则追加；超 80 条截断。

## 4. 关键契约
- `turns.jsonl` 每条 = `{ok, latency_ms, calls[], prompt_tokens, completion_tokens, world_issues, world_corrected, date_reverted, participants, memory_stats, timestamp}`。
- `session_metrics(session) -> {硬指标…, gates:{指标: PASS|FAIL|BASELINE}}`。

## 5. 边界与演进
- 观测只记录元数据（无正文），避免体积膨胀。
- 后续（V3-C/D/E）在同一 metrics 上扩观察项与裁判，不改硬门禁集合。
