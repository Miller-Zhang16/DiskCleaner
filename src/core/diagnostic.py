# -*- coding: utf-8 -*-
"""导出诊断包。

用户反馈「删不掉」「界面异常」时，仅凭一句描述很难定位。诊断包把版本、
系统信息、配置、最近日志与历史记录打成一个 zip，用户可以直接发回，
避免反复索取环境信息。
"""

import os
import platform
import sys
import time
import zipfile

from ..version import VERSION
from .runtime import app_root, data_dir, is_admin


def _safe_mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0


def _read_text(path, limit=200_000):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""


def build_diagnostics(dest_zip, data_root=None):
    """生成诊断包，返回写入的文件数量。"""
    root = app_root()
    data = data_root or data_dir()
    info = [
        "DiskCleaner v%s" % VERSION,
        "generated: %s" % time.strftime("%Y-%m-%d %H:%M:%S"),
        "python: %s" % sys.version.replace("\n", " "),
        "platform: %s" % platform.platform(),
        "admin: %s" % is_admin(),
        "app_root: %s" % root,
        "data_dir: %s" % data,
    ]

    count = 0
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("version.txt", "\n".join(info) + "\n")
        count += 1

        for name in ("settings.ini", "custom_targets.txt"):
            p = os.path.join(data, name)
            if os.path.isfile(p):
                zf.write(p, "config/" + name)
                count += 1

        log_dir = os.path.join(data, "logs")
        if os.path.isdir(log_dir):
            try:
                names = [os.path.join(log_dir, n) for n in os.listdir(log_dir)]
            except OSError:
                names = []
            names = [p for p in names if os.path.isfile(p)]
            # 只带最近 3 个日志文件，避免诊断包过大
            for p in sorted(names, key=_safe_mtime, reverse=True)[:3]:
                zf.write(p, "logs/" + os.path.basename(p))
                count += 1

        history = os.path.join(data, "history.jsonl")
        if os.path.isfile(history):
            tail = _read_text(history).splitlines()[-200:]
            zf.writestr("history/recent.jsonl", "\n".join(tail) + "\n")
            count += 1

        growth = os.path.join(data, "growth.json")
        if os.path.isfile(growth):
            zf.write(growth, "growth.json")
            count += 1

    return count
