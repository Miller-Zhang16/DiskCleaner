# -*- coding: utf-8 -*-
"""测试磁盘占用趋势：同日覆盖、增长预测与持久化。"""

import datetime
import json
from pathlib import Path

from src.core.growth import GrowthStore


def _at(day):
    return datetime.datetime(2026, 1, day, 12, 0, 0)


def test_record_and_forecast(tmp_path):
    store = GrowthStore(str(tmp_path / "growth.json"))
    stats = store.record(1000, 100, now=_at(1))
    assert stats["daily_delta"] is None
    assert stats["days_left"] is None

    stats = store.record(1000, 200, now=_at(2))
    assert stats["days"] == 1
    assert stats["daily_delta"] == 100
    assert stats["free"] == 800
    assert stats["days_left"] == 8


def test_same_day_replaces_snapshot(tmp_path):
    store = GrowthStore(str(tmp_path / "growth.json"))
    store.record(1000, 100, now=_at(1))
    store.record(1000, 150, now=_at(1))
    assert len(store.snapshots) == 1
    assert store.snapshots[0]["used"] == 150


def test_stable_usage_has_no_forecast(tmp_path):
    store = GrowthStore(str(tmp_path / "growth.json"))
    store.record(1000, 300, now=_at(1))
    stats = store.record(1000, 250, now=_at(2))
    assert stats["daily_delta"] == -50
    assert stats["days_left"] is None


def test_persistence_roundtrip(tmp_path):
    path = str(tmp_path / "growth.json")
    GrowthStore(path).record(1000, 100, now=_at(1))
    GrowthStore(path).record(1000, 200, now=_at(2))
    again = GrowthStore(path)
    assert len(again.snapshots) == 2
    assert again.stats(now=_at(2))["daily_delta"] == 100


def test_invalid_file_is_ignored(tmp_path):
    path = tmp_path / "growth.json"
    path.write_text("{not json", encoding="utf-8")
    store = GrowthStore(str(path))
    assert store.snapshots == []


def test_caps_snapshot_count(tmp_path):
    path = str(tmp_path / "growth.json")
    store = GrowthStore(path, max_snapshots=3)
    for day in range(1, 6):
        store.record(1000, 100 + day, now=_at(day))
    assert len(store.snapshots) == 3
    assert store.snapshots[-1]["used"] == 105
    json.loads(Path(path).read_text(encoding="utf-8"))
