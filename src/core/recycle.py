# -*- coding: utf-8 -*-
"""回收站操作（Shell API 封装）。

使用 ``SHEmptyRecycleBinW`` 清空回收站，``SHQueryRecycleBinW`` 预估体积。

返回码约定：
    S_OK(0) / S_FALSE(1) / E_UNEXPECTED(0x8000FFFF) 均视为「已清空」；
    不以 ``GetLastError`` 判断成败。
"""

import ctypes
import ctypes.wintypes as wintypes
import os

# HE 空回收站标志：NOCONFIRMATION | NOPROGRESSUI | NOSOUND
SHRB_FLAGS = 0x1 | 0x2 | 0x4

S_OK = 0
S_FALSE = 1
E_UNEXPECTED = -2147418113  # 0x8000FFFF（按有符号 32 位解释）


class SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("i64Size", ctypes.c_int64),
        ("i64NumItems", ctypes.c_int64),
    ]


def recycle_bin_size(root=r"C:\\"):
    """查询回收站占用字节数；失败返回 None。"""
    info = SHQUERYRBINFO()
    info.cbSize = ctypes.sizeof(SHQUERYRBINFO)
    try:
        fn = ctypes.windll.shell32.SHQueryRecycleBinW
        fn.argtypes = (ctypes.c_wchar_p, ctypes.POINTER(SHQUERYRBINFO))
        fn.restype = ctypes.c_long
        res = fn(root, ctypes.byref(info))
        if res == S_OK:
            return int(info.i64Size)
    except Exception:  # noqa: BLE001
        pass
    return None


def empty_recycle_bin(root=r"C:\\", flags=SHRB_FLAGS):
    """清空指定盘符的回收站。返回 ``(ok, message)``。"""
    try:
        fn = ctypes.windll.shell32.SHEmptyRecycleBinW
        fn.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32)
        fn.restype = ctypes.c_long
        res = fn(None, root, flags)
        if res in (S_OK, S_FALSE, E_UNEXPECTED):
            return True, "回收站已清空"
        return False, "清空回收站返回码 %d" % res
    except Exception as e:  # noqa: BLE001
        return False, "清空回收站失败：%s" % e


def fixed_drives():
    """返回本机存在的固定盘根路径列表，如 ``["C:\\\\", "D:\\\\"]``。"""
    drives = []
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        root = letter + ":\\"
        if os.path.isdir(root):
            drives.append(root)
    return drives


def recycle_bin_size_all():
    """汇总所有盘回收站的占用；全部读取失败或为空时返回 None/0。"""
    total = 0
    found = False
    for root in fixed_drives():
        size = recycle_bin_size(root)
        if size is not None:
            found = True
            total += size
    return total if found else None


def empty_recycle_bin_all(flags=SHRB_FLAGS):
    """清空所有盘的回收站。返回 ``(ok, freed_bytes, message)``。"""
    freed = 0
    failures = []
    for root in fixed_drives():
        before = recycle_bin_size(root) or 0
        ok, msg = empty_recycle_bin(root, flags)
        if ok:
            freed += before
        else:
            failures.append("%s %s" % (root, msg))
    if failures:
        return False, freed, "；".join(failures)
    return True, freed, "已清空所有盘的回收站"
