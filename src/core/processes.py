# -*- coding: utf-8 -*-
"""检测占用清理目标的程序是否正在运行。

浏览器运行时，其缓存目录会被独占或频繁写入，直接删除往往只成功一部分，
用户会看到「跳过 N 项」却不知道为什么。清理前先检测进程，可以明确提示
用户关闭浏览器，或者干脆跳过相关目标。
"""

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes

_CREATE_NO_WINDOW = 0x08000000
_TH32CS_SNAPPROCESS = 0x00000002
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


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


def running_executables():
    """返回正在运行的进程可执行文件完整路径列表（小写）。

    通过 Toolhelp 快照 + ``QueryFullProcessImageNameW`` 实现，不需要管理员
    权限（提权进程读不到路径时会跳过），也不依赖 ``wmic`` 或 PowerShell。
    """
    if sys.platform != "win32":
        return []
    k32 = ctypes.windll.kernel32
    snap = k32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not snap or snap == _INVALID_HANDLE_VALUE:
        return []

    entry = _PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
    paths = []
    try:
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            handle = k32.OpenProcess(
                _PROCESS_QUERY_LIMITED_INFORMATION, False, entry.th32ProcessID)
            if handle:
                buf = ctypes.create_unicode_buffer(1024)
                size = wintypes.DWORD(1024)
                if k32.QueryFullProcessImageNameW(
                        handle, 0, buf, ctypes.byref(size)):
                    paths.append(os.path.normcase(buf.value))
                k32.CloseHandle(handle)
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return paths


def executables_under(root, exes=None):
    """返回运行中且可执行文件位于 ``root`` 目录内的路径。"""
    if not root:
        return []
    if exes is None:
        exes = running_executables()
    prefix = os.path.normcase(os.path.abspath(root)).rstrip("\\/") + "\\"
    return [p for p in exes if p.startswith(prefix)]
