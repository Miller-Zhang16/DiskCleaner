# -*- coding: utf-8 -*-
"""运行时环境：应用根目录、数据目录，以及管理员权限判定与自我提权。"""

import ctypes
import os
import sys
from ctypes import wintypes

SENTINEL_ELEVATED = "--elevated"


# ---------------------------------------------------------------------------
# 路径解析（兼容源码运行与 PyInstaller 打包运行）
# ---------------------------------------------------------------------------


def app_root():
    """应用根目录。

    - PyInstaller 打包后：可执行文件所在目录
    - 源码运行：项目根目录（本文件位于 src/core/ 下，向上两级）
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    # 本文件位于 <root>/src/core/runtime.py，故向上两级即为项目根目录
    here = os.path.dirname(os.path.abspath(__file__))          # <root>/src/core
    src = os.path.dirname(here)                                # <root>/src
    return os.path.dirname(src)                                # <root>


def data_dir():
    return os.path.join(app_root(), "data")


def log_dir():
    return os.path.join(data_dir(), "logs")


def config_path():
    return os.path.join(data_dir(), "settings.ini")


def custom_targets_path():
    return os.path.join(data_dir(), "custom_targets.txt")


def icon_path():
    """应用图标路径（.ico），不存在时返回 None。"""
    p = os.path.join(app_root(), "assets", "icon.ico")
    return p if os.path.isfile(p) else None


def ensure_data_dir():
    """确保数据目录存在，返回其路径。"""
    d = data_dir()
    os.makedirs(d, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# 权限
# ---------------------------------------------------------------------------


def is_admin():
    """当前进程是否以管理员权限运行。"""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin():
    """以管理员身份重新启动自身。

    返回 (ok, code)：
        ok 为 True 时调用方应退出当前进程；
        code 取值 "ok" / "cancelled" / "already" / "error:<n>"。
    """
    if SENTINEL_ELEVATED in sys.argv:
        return False, "already"

    def quote(a):
        return '"%s"' % a if (" " in a or "\t" in a) else a

    if getattr(sys, "frozen", False):
        lp_file = sys.executable
        args = [a for a in sys.argv[1:] if a != SENTINEL_ELEVATED]
        params = " ".join(quote(a) for a in args + [SENTINEL_ELEVATED])
        work_dir = os.path.dirname(os.path.abspath(sys.executable))
    else:
        script = os.path.abspath(sys.argv[0])
        lp_file = sys.executable
        args = [a for a in sys.argv[1:] if a != SENTINEL_ELEVATED]
        params = " ".join([quote(script)] + [quote(a) for a in args] + [SENTINEL_ELEVATED])
        work_dir = os.path.dirname(script)

    try:
        fn = ctypes.windll.shell32.ShellExecuteW
        # HINSTANCE 需按指针宽度解析，否则 64 位下返回值会被截断
        fn.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
                       ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_int)
        fn.restype = ctypes.c_void_p
        ret = fn(None, "runas", lp_file, params, work_dir, 1)
        if ret is None:
            ret = 0
        if ret > 32:
            return True, "ok"
        if ret == 1223:
            return False, "cancelled"  # 用户在 UAC 对话框点了「否」
        return False, "error:%s" % ret
    except Exception as e:  # noqa: BLE001
        return False, "error:%s" % e


def enable_dpi_awareness():
    """开启高 DPI 感知，避免界面发虚。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def set_app_user_model_id(app_id="Trae.DiskCleaner.App.1"):
    """为当前进程设置独立的 AppUserModelID。

    Windows 依据 AppUserModelID 决定任务栏图标与窗口分组。运行时宿主是
    pythonw.exe，不设置的话任务栏会沿用解释器自带的 Python 图标，
    即使 root.iconbitmap() 已生效。
    必须在创建任何窗口之前调用。
    """
    try:
        fn = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        fn.argtypes = (ctypes.c_wchar_p,)
        fn.restype = ctypes.c_long
        fn(app_id)
    except Exception:
        pass


# wintypes 在部分调用方会用到（保持导入可见性，便于扩展其他 Win32 调用）
_ = wintypes
