# -*- coding: utf-8 -*-
"""路径、体积、Windows 文件属性的通用工具函数。"""

import os

# Windows 文件属性：重解析点（junction / symlink / 挂载点）
FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def fmt_size(n):
    """把字节数格式化成人类可读字符串。"""
    if n is None:
        return "—"
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "—"
    sign = "-" if n < 0 else ""
    n = abs(n)
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    f = float(n)
    i = 0
    while f >= 1024.0 and i < len(units) - 1:
        f /= 1024.0
        i += 1
    if i == 0:
        return "%s%d B" % (sign, n)
    return "%s%.1f %s" % (sign, f, units[i])


def is_reparse_point(st):
    """判断 stat 结果是否为重解析点（junction / symlink 等）。"""
    return bool(getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT)


def long_path(path):
    """为超长路径添加 \\\\?\\ 前缀。"""
    if os.name != "nt":
        return path
    ap = os.path.abspath(path)
    if ap.startswith("\\\\?\\"):
        return ap
    if ap.startswith("\\\\"):
        return "\\\\?\\UNC\\" + ap[2:]
    return "\\\\?\\" + ap


def scandir_robust(path):
    """scandir 的健壮版本：普通路径失败时回退到长路径形式。"""
    try:
        return os.scandir(path)
    except OSError:
        return os.scandir(long_path(path))


def expand_path(raw):
    """展开环境变量与 ~，兼容 %VAR% 写法。"""
    return os.path.expandvars(os.path.expanduser(raw))


def is_glob(p):
    """判断是否为 glob 模式。"""
    return any(ch in p for ch in "*?[")


def dir_of(path):
    """返回路径所在目录（用于资源管理器定位）。"""
    return path if os.path.isdir(path) else os.path.dirname(path)
