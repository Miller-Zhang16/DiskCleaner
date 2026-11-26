# -*- coding: utf-8 -*-
"""把文件或目录移入 Windows 回收站。

缓存类目标可以直接永久删除，但重复文件、下载目录、浏览页手动删除的
项目属于用户数据，误删后无法恢复，因此这些场景统一走系统回收站，
用户可以随时还原。实现使用 Shell API，不引入第三方依赖。
"""

import ctypes
import os
import sys
from ctypes import wintypes

FO_DELETE = 3
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400
FOF_NOCONFIRMMKDIR = 0x0200
FOF_WANTNUKEWARNING = 0x4000


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", ctypes.c_void_p),
        ("pTo", ctypes.c_void_p),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.c_void_p),
    ]


def supported():
    """当前系统是否支持移入回收站。"""
    return sys.platform == "win32"


def send_to_trash(paths):
    """逐个移入回收站，返回 ``(moved_paths, failures[(path, reason)])``。

    逐个处理而不是一次批量提交，因为 SHFileOperation 的返回值无法定位
    具体是哪一项失败；逐项失败可以准确记入清理结果。
    """
    moved, failed = [], []
    for p in paths or []:
        if not supported():
            failed.append((p, "当前系统不支持回收站"))
            continue
        if not os.path.exists(p):
            failed.append((p, "路径不存在"))
            continue
        ok, err = _send_one(p)
        if ok:
            moved.append(p)
        else:
            failed.append((p, err))
    return moved, failed


def _send_one(path):
    ole32 = ctypes.windll.ole32
    # 后台线程调用 Shell API 前需要初始化 COM
    ole32.CoInitialize(None)
    try:
        # pFrom 必须是「以双 NUL 结尾」的路径列表
        buf = ctypes.create_unicode_buffer(os.path.abspath(path) + "\0")
        op = _SHFILEOPSTRUCTW()
        op.wFunc = FO_DELETE
        op.pFrom = ctypes.addressof(buf)
        op.fFlags = (FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
                     | FOF_NOERRORUI | FOF_NOCONFIRMMKDIR | FOF_WANTNUKEWARNING)
        fn = ctypes.windll.shell32.SHFileOperationW
        fn.argtypes = (ctypes.POINTER(_SHFILEOPSTRUCTW),)
        fn.restype = ctypes.c_int
        code = fn(ctypes.byref(op))
        if code != 0:
            return False, "回收站操作失败（代码 %d）" % code
        if op.fAnyOperationsAborted:
            return False, "操作被取消"
        if os.path.exists(path):
            return False, "文件仍存在，可能被占用"
        return True, None
    except Exception as e:  # noqa: BLE001
        return False, str(e)
    finally:
        ole32.CoUninitialize()
