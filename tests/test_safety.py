# -*- coding: utf-8 -*-
"""清理安全边界：浏览器多配置路径与进程占用检测。"""

from src.core import processes
from src.core.pathguard import protected_segment
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


def test_protected_segments():
    assert protected_segment(r"C:\Users\me\Documents\a") == "documents"
    assert protected_segment(r"C:\work\.git\objects") == ".git"
    assert protected_segment(r"C:\Windows\Temp") is None
    assert protected_segment(r"D:\Scratch") is None


class _Cfg:
    temp_min_age_seconds = 86400

    def ensure_target(self, key, default):
        pass

    def target_default(self, key, default):
        return default

    def custom_targets(self):
        return [r"C:\Users\me\Documents", r"D:\Scratch"]


def test_custom_targets_are_blocked_by_segment():
    targets = build_targets(_Cfg())
    custom = {t["name"].split("：")[-1]: t for t in targets if t.get("custom")}
    assert custom["Documents"]["blocked"] == "documents"
    assert custom["Scratch"]["blocked"] is None
