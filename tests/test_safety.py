# -*- coding: utf-8 -*-
"""清理安全边界：浏览器多配置路径与进程占用检测。"""

from src.core import processes
from src.core.targets import build_targets


def _paths(targets, key):
    return next(t for t in targets if t["key"] == key)["paths"]


def test_browser_cache_covers_default_profile():
    paths = _paths(build_targets(None), "chrome_cache")
    assert any(p.endswith("Cache") and "Default" in p for p in paths)


def test_browser_cache_covers_extra_profiles():
    paths = _paths(build_targets(None), "edge_cache")
    assert any("Profile *" in p for p in paths)


def test_busy_targets_reports_running_browser(monkeypatch):
    monkeypatch.setattr(processes, "running_processes", lambda _names: {"chrome"})
    targets = [
        {"key": "chrome_cache", "name": "Chrome 缓存",
         "busy_processes": ("chrome", "chromium")},
        {"key": "user_temp", "name": "临时文件"},
    ]
    busy = processes.busy_targets(targets)
    assert [t["key"] for t, _ in busy] == ["chrome_cache"]
    assert busy[0][1] == ["chrome"]


def test_busy_targets_empty_when_nothing_running(monkeypatch):
    monkeypatch.setattr(processes, "running_processes", lambda _names: set())
    targets = [{"key": "edge_cache", "name": "Edge",
                "busy_processes": ("msedge",)}]
    assert processes.busy_targets(targets) == []
