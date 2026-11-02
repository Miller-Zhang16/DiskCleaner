# -*- coding: utf-8 -*-
"""磁盘占用历史与增长趋势。

每次刷新磁盘信息时记录一条当日快照（同一天只保留最后一次），
基于最近 30 天的数据估算日均增长量，并按当前可用空间预测「还有多少天写满」。

设计取舍：
    - 纯 JSON 持久化，最多保留 120 条，文件始终很小；
    - 使用本地日期而不是时间戳做去重，跨时区 / 夏令时也不会重复记录；
    - 数据不足 2 天或占用没有增长时不做预测，避免给出误导性的结论；
    - 写入采用「临时文件 + 替换」，避免异常退出留下半个 JSON 文件。
"""

import datetime
import json
import os
import tempfile

MAX_SNAPSHOTS = 120
TREND_WINDOW_DAYS = 30


class GrowthStore:
    """磁盘占用快照存储与趋势计算。"""

    def __init__(self, path, max_snapshots=MAX_SNAPSHOTS):
        self.path = path
        self.max_snapshots = max(2, int(max_snapshots))
        self.snapshots = self._load()

    # ---------------- 读写 ----------------

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        out = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                date = datetime.date.fromisoformat(str(item.get("date", "")))
                total = int(item.get("total", 0))
                used = int(item.get("used", 0))
            except (ValueError, TypeError):
                continue
            if total <= 0 or not 0 <= used <= total:
                continue
            out.append({"date": date.isoformat(), "total": total, "used": used})
        return out[-self.max_snapshots:]

    def _save(self):
        directory = os.path.dirname(self.path)
        try:
            if directory:
                os.makedirs(directory, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=directory or None, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.snapshots, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError:
            try:
                os.remove(tmp)
            except (OSError, UnboundLocalError):
                pass

    # ---------------- 记录 ----------------

    def record(self, total, used, now=None):
        """记录一次快照（同一天覆盖），返回最新趋势统计。"""
        if total <= 0 or not 0 <= used <= total:
            return self.stats(now)
        today = (now or datetime.datetime.now()).date().isoformat()
        entry = {"date": today, "total": int(total), "used": int(used)}
        if self.snapshots and self.snapshots[-1]["date"] == today:
            self.snapshots[-1] = entry
        else:
            self.snapshots.append(entry)
        if len(self.snapshots) > self.max_snapshots:
            self.snapshots = self.snapshots[-self.max_snapshots:]
        self._save()
        return self.stats(now)

    # ---------------- 趋势 ----------------

    def stats(self, now=None):
        """返回趋势统计。

        字段：
            days        统计跨度（天，整数）
            daily_delta 日均增长字节数（无数据或不足 2 天时为 None）
            days_left   按当前增速预计多少天写满（未增长时为 None）
            free        最后一次快照的可用空间
        """
        empty = {"days": 0, "daily_delta": None, "days_left": None, "free": None}
        if len(self.snapshots) < 2:
            return empty

        today = (now or datetime.datetime.now()).date()
        recent = []
        for snap in self.snapshots:
            try:
                day = datetime.date.fromisoformat(snap["date"])
            except ValueError:
                continue
            if (today - day).days <= TREND_WINDOW_DAYS:
                recent.append((day, snap))
        if len(recent) < 2:
            return empty

        first_day, first = recent[0]
        last_day, last = recent[-1]
        span = (last_day - first_day).days
        if span < 1:
            return empty

        delta = (last["used"] - first["used"]) / float(span)
        free = max(0, last["total"] - last["used"])
        days_left = None
        if delta > 0:
            days_left = int(free // delta)
        return {"days": span, "daily_delta": delta,
                "days_left": days_left, "free": free}
