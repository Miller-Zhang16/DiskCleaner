# -*- coding: utf-8 -*-
"""清理历史记录。

每次清理任务结束后追加一条记录到 ``data/history.jsonl``，便于用户事后
回溯「什么时候清了什么、释放多少、哪些项失败」。按 ``max_records``
上限自动淘汰最旧记录。

为什么用 JSONL 而不是单个 JSON 数组：
    - 追加写入开销恒定，不必每次读改写整个文件；
    - 单行损坏只影响该条记录，逐行容错解析不会整体失败；
    - 用户可用记事本直接查看最后几行。
"""

import json
import os
import time

DEFAULT_MAX_RECORDS = 200


class History:
    """清理历史读写封装（仅追加 + 按上限淘汰）。"""

    def __init__(self, path, max_records=DEFAULT_MAX_RECORDS):
        self.path = path
        self.max_records = max(1, max_records)

    def append(self, entry):
        """追加一条记录；写入后若超出上限则裁剪最旧记录。

        返回是否写入成功。失败不抛异常——历史记录属于辅助功能，
        不能因为它写不进去而影响清理结果展示。
        """
        record = dict(entry)
        record.setdefault("ts", time.time())
        record.setdefault("time", time.strftime("%Y-%m-%d %H:%M:%S",
                                                time.localtime(record["ts"])))
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._trim()
            return True
        except (OSError, TypeError, ValueError):
            return False

    def load(self, limit=None):
        """读取记录，按时间从新到旧返回。"""
        if not os.path.isfile(self.path):
            return []
        records = []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except ValueError:
                        continue
        except OSError:
            return []
        records.reverse()
        if limit is not None:
            records = records[:limit]
        return records

    def clear(self):
        try:
            if os.path.isfile(self.path):
                os.remove(self.path)
            return True
        except OSError:
            return False

    def _trim(self):
        """仅保留最近 max_records 条（重写文件）。"""
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                lines = [ln for ln in f.read().splitlines() if ln.strip()]
        except OSError:
            return
        if len(lines) <= self.max_records:
            return
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines[-self.max_records:]) + "\n")
        except OSError:
            pass
