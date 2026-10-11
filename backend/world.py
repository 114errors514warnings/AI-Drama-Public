"""V4: 世界状态（World State）+ 时间线（Timeline）+ 事件流（Event System）。

每个世界会话拥有独立的一份，互不干扰。
"""
from __future__ import annotations

import datetime


def _today_iso() -> str:
    return datetime.date.today().isoformat()


# 时间段的一天内先后顺序（未知时段不参与顺序判定）
TIME_ORDER = {
    "凌晨": 0, "清晨": 1, "上午": 2, "白天": 3, "中午": 4,
    "下午": 5, "傍晚": 6, "晚上": 7, "深夜": 8,
}


class WorldState:
    def __init__(self, world_name: str = "", rules: str = ""):
        self.world_name = world_name
        # 结构化时间（默认年月日格式展示）
        self.start_date: str = _today_iso()   # 故事起始日（ISO），供"相对时间"计算第几天
        self.date: str = ""                   # 故事当前日期（ISO YYYY-MM-DD），空 = 未设定
        self.time_of_day: str = ""            # 可选时间段：白天/傍晚/晚上/深夜
        self.location = "未知地点"
        self.rules = rules
        self.rules_override: str = ""   # V4：用户在 UI 手改的世界背景（覆盖知识库）
        self.events: list[dict] = []
        self.timeline: list[dict] = []
        # 剧情梗概（Synopsis Agent 维护，节流更新）
        self.synopsis: str = ""
        self.synopsis_base_len: int = 0

    @property
    def effective_rules(self) -> str:
        """实际注入提示词的世界背景：用户覆盖优先，否则用知识库装载的内容。"""
        return self.rules_override if self.rules_override.strip() else self.rules

    def add_event(self, event: str, narration: str = "") -> None:
        entry = {
            "date": self.date,
            "time_of_day": self.time_of_day,
            "location": self.location,
            "event": event,
            "narration": narration,
        }
        self.events.append(entry)
        self.timeline.append(entry)
        if len(self.events) > 200:
            self.events = self.events[-200:]
            self.timeline = self.timeline[-200:]

    @staticmethod
    def _is_iso(date: str) -> bool:
        import re  # noqa: PLC0415
        return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", (date or "").strip()))

    def try_set_date(self, new_date: str) -> bool:
        """长程一致性：故事日期只进不退。接受并更新返回 True，回退或非法返回 False。"""
        new_date = (new_date or "").strip()
        if not self._is_iso(new_date):
            return False
        if self.date and new_date < self.date:
            return False
        self.date = new_date
        return True

    def synopsis_coverage(self) -> float:
        """梗概对已发生事件的覆盖度（观察项）：事件关键词被梗概命中的比例。"""
        if not self.events:
            return 1.0
        from .knowledge_base import tokenize  # noqa: PLC0415
        synopsis = (self.synopsis or "").lower()
        if not synopsis:
            return 0.0
        covered = 0
        for entry in self.events:
            tokens = set(tokenize(str(entry.get("event", "")))) - {"", " "}
            if not tokens:
                covered += 1
                continue
            hit = sum(1 for t in tokens if t in synopsis)
            if hit / len(tokens) >= 0.3:
                covered += 1
        return covered / len(self.events)

    def validate_timeline(self) -> list[dict]:
        """因果校验：时间只能前进、事件非空、同一时空不重复。

        返回问题列表 [{index, code, detail}]，硬门禁要求为空。
        code ∈ {missing_date, date_backwards, time_backwards, empty_event, duplicate_event}
        """
        issues: list[dict] = []
        prev_date = ""
        prev_order: int | None = None
        prev_key: tuple[str, str, str] | None = None

        for index, entry in enumerate(self.timeline):
            date = str(entry.get("date") or "").strip()
            tod = str(entry.get("time_of_day") or "").strip()
            event = str(entry.get("event") or "").strip()

            if not date:
                issues.append({"index": index, "code": "missing_date", "detail": "事件缺少日期"})
            elif prev_date and date < prev_date:
                issues.append({"index": index, "code": "date_backwards",
                               "detail": f"{date} 早于上一条 {prev_date}"})
            if not event:
                issues.append({"index": index, "code": "empty_event", "detail": "事件为空"})

            order = TIME_ORDER.get(tod)
            if date == prev_date:
                if order is not None and prev_order is not None and order < prev_order:
                    issues.append({"index": index, "code": "time_backwards",
                                   "detail": f"{tod} 早于同日上一条"})
                if order is not None:
                    prev_order = order
            else:
                prev_order = order

            key = (date, tod, event)
            if event and prev_key is not None and key == prev_key:
                issues.append({"index": index, "code": "duplicate_event", "detail": "与上一条事件完全相同"})
            prev_key = key
            prev_date = date or prev_date

        return issues


    def display_time(self, time_format: str = "date", fallback: str = "时间未定",
                     date: str | None = None, time_of_day: str | None = None) -> str:
        """按格式渲染时间；日期为空时返回 fallback。

        time_format: date(年月日) / datetime(年月日+时间段) / relative(第N天·时段)
        """
        d = (date or self.date or "").strip()
        tod = (self.time_of_day if time_of_day is None else time_of_day or "").strip()
        if not d:
            return fallback
        try:
            y, mo, dd = d.split("-", 2)
            y, mo, dd = int(y), int(mo), int(dd)
        except Exception:  # noqa: BLE001
            return d
        if time_format == "relative":
            try:
                start = datetime.date.fromisoformat(self.start_date)
                cur = datetime.date(y, mo, dd)
                day_num = (cur - start).days + 1
            except Exception:  # noqa: BLE001
                day_num = 1
            return f"第 {day_num} 天 · {tod or '白天'}"
        if time_format == "datetime":
            return f"{y}年{mo}月{dd}日" + (f" {tod}" if tod else "")
        return f"{y}年{mo}月{dd}日"

    def to_dict(self, time_format: str = "date", fallback: str = "时间未定") -> dict:
        def fmt(entry: dict) -> str:
            return self.display_time(
                time_format, fallback,
                date=entry.get("date") or self.date,
                time_of_day=entry.get("time_of_day") or "",
            )

        timeline = []
        for e in self.timeline[-50:]:
            t = dict(e)
            t["time"] = fmt(e)
            timeline.append(t)
        events = []
        for e in self.events[-20:]:
            t = dict(e)
            t["time"] = fmt(e)
            events.append(t)
        return {
            "world_name": self.world_name,
            "start_date": self.start_date,
            "date": self.date,
            "time_of_day": self.time_of_day,
            "time": self.display_time(time_format, fallback),
            "location": self.location,
            "rules": self.rules[:3000],
            "rules_override": self.rules_override,
            "rules_from_kb": bool(self.rules) and not bool(self.rules_override.strip()),
            "effective_rules": self.effective_rules[:3000],
            "events": events,
            "timeline": timeline,
            "synopsis": self.synopsis,
            "synopsis_base_len": self.synopsis_base_len,
        }

    def restore(self, d: dict | None) -> None:
        if not d:
            return
        self.start_date = d.get("start_date", "") or _today_iso()
        self.date = d.get("date", "") or ""
        self.time_of_day = d.get("time_of_day", "") or ""
        if not self.date:
            # 旧版本会话兼容：无结构化日期时回落到起始日
            self.date = self.start_date
        self.location = d.get("location", self.location)
        self.rules_override = str(d.get("rules_override", "") or "")
        self.events = d.get("events", [])
        self.timeline = d.get("timeline", [])
        self.synopsis = d.get("synopsis", "")
        self.synopsis_base_len = int(d.get("synopsis_base_len", 0))

