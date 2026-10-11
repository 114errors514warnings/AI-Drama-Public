"""世界状态：日期只进不退、梗概覆盖度。"""
from __future__ import annotations

from backend.world import WorldState


def test_try_set_date_accepts_forward_and_equal() -> None:
    world = WorldState()
    assert world.try_set_date("2026-09-01") is True
    assert world.date == "2026-09-01"
    assert world.try_set_date("2026-09-10") is True
    assert world.date == "2026-09-10"
    assert world.try_set_date("2026-09-10") is True


def test_try_set_date_rejects_backwards() -> None:
    world = WorldState()
    world.try_set_date("2026-09-10")
    assert world.try_set_date("2026-08-01") is False
    assert world.date == "2026-09-10"


def test_try_set_date_rejects_non_iso() -> None:
    world = WorldState()
    assert world.try_set_date("明天") is False
    assert world.try_set_date("") is False
    assert world.date == ""


def test_synopsis_coverage_zero_without_synopsis() -> None:
    world = WorldState()
    world.add_event("开学第一天", "旁白")
    assert world.synopsis_coverage() == 0.0


def test_synopsis_coverage_positive_when_covered() -> None:
    world = WorldState()
    world.add_event("开学第一天", "旁白")
    world.synopsis = "开学第一天，大家回到校园。"
    assert world.synopsis_coverage() > 0.5


def test_to_dict_includes_synopsis_base_len() -> None:
    world = WorldState()
    world.synopsis_base_len = 42
    assert world.to_dict()["synopsis_base_len"] == 42


def test_validate_timeline_clean() -> None:
    world = WorldState()
    world.try_set_date("2026-09-01")
    world.time_of_day = "白天"
    world.add_event("开学第一天", "旁白")
    world.date = "2026-09-01"
    world.time_of_day = "傍晚"
    world.add_event("放学后", "旁白")
    assert world.validate_timeline() == []


def test_validate_timeline_flags_backwards_date() -> None:
    world = WorldState()
    world.timeline = [
        {"date": "2026-09-10", "time_of_day": "白天", "event": "A"},
        {"date": "2026-09-01", "time_of_day": "白天", "event": "B"},
    ]
    codes = {i["code"] for i in world.validate_timeline()}
    assert "date_backwards" in codes


def test_validate_timeline_flags_time_backwards_same_day() -> None:
    world = WorldState()
    world.timeline = [
        {"date": "2026-09-01", "time_of_day": "晚上", "event": "A"},
        {"date": "2026-09-01", "time_of_day": "白天", "event": "B"},
    ]
    codes = {i["code"] for i in world.validate_timeline()}
    assert "time_backwards" in codes


def test_validate_timeline_flags_empty_and_duplicate() -> None:
    world = WorldState()
    world.timeline = [
        {"date": "2026-09-01", "time_of_day": "白天", "event": "A"},
        {"date": "2026-09-01", "time_of_day": "白天", "event": "A"},
        {"date": "", "time_of_day": "", "event": ""},
    ]
    codes = {i["code"] for i in world.validate_timeline()}
    assert "duplicate_event" in codes
    assert "missing_date" in codes
    assert "empty_event" in codes
