# -*- coding: utf-8 -*-
"""检测占用清理目标的程序是否正在运行。

浏览器运行时，其缓存目录会被独占或频繁写入，直接删除往往只成功一部分，
用户会看到「跳过 N 项」却不知道为什么。清理前先检测进程，可以明确提示
用户关闭浏览器，或者干脆跳过相关目标。
"""

import subprocess
import sys

_CREATE_NO_WINDOW = 0x08000000


def running_processes(names):
    """返回 ``names`` 中正在运行的进程名（小写，不含 .exe）。

    使用 ``tasklist`` 而不是 psutil，保持运行时零第三方依赖。
    任何异常都返回空集合：检测失败不应阻止用户清理。
    """
    if not names or sys.platform != "win32":
        return set()
    try:
        out = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=8,
            creationflags=_CREATE_NO_WINDOW,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return set()

    wanted = {n.lower().removesuffix(".exe") for n in names}
    running = set()
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith('"'):
            continue
        exe = line.split('","', 1)[0].strip('"').lower()
        if exe.endswith(".exe"):
            exe = exe[:-4]
        if exe in wanted:
            running.add(exe)
    return running


def busy_targets(targets):
    """返回 ``[(target, [进程名...])]``，只包含有程序正在占用的清理目标。"""
    wanted = set()
    for t in targets:
        wanted.update(t.get("busy_processes", ()))
    running = running_processes(wanted)
    out = []
    for t in targets:
        hits = [p for p in t.get("busy_processes", ()) if p.lower() in running]
        if hits:
            out.append((t, hits))
    return out
