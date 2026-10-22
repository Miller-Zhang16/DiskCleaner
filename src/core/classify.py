# -*- coding: utf-8 -*-
"""文件/目录分类。

分类仅用于展示与辅导用户判断，不参与删除决策——分类结果绝不会把
桌面、文档、下载等用户数据目录标记为「可清理」。

分类优先级：回收站 → 缓存临时 → 系统文件 → 软件文件 → 数据文件 → 其他。
"""

import os

CATEGORIES = ("系统文件", "软件文件", "数据文件", "缓存临时", "回收站", "其他")

CATEGORY_COLORS = {
    "系统文件": "#e9e9e9",
    "软件文件": "#e7f0fb",
    "数据文件": "#e8f6e8",
    "缓存临时": "#fdf3d8",
    "回收站": "#fbe0e0",
    "其他": "#f6f6f6",
}

# 缓存 / 临时目录的路径片段标记
_CACHE_MARKERS = (
    "\\temp",
    "\\$temp",
    "\\prefetch",
    "\\softwaredistribution\\download",
    "\\deliveryoptimization",
    "\\crashdumps",
    "\\thumbcache",
    "\\iconcache",
    "\\cache",
    "\\code cache",
    "\\gpucache",
    "\\cachestorage",
    "\\localcache",
    "\\tempstate",
    "\\logs\\cbs",
    "\\livekernelreports",
)

# 数据文件目录名（按路径段精确匹配，避免 OneDriveTemp 之类被误判）
_DATA_SEGMENTS = {
    "documents", "pictures", "videos", "music",
    "desktop", "downloads", "onedrive", "3d objects",
}

# 扩展名兜底
_DATA_EXTS = {
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".pdf", ".txt", ".md",
    ".csv", ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".mp3", ".mp4", ".avi",
    ".mkv", ".mov", ".zip", ".rar", ".7z",
}

_SYSTEM_ROOT_FILES = {
    "pagefile.sys", "hiberfil.sys", "swapfile.sys",
    "bootmgr", "bootmgr.efi", "ntldr", "dumpstack.log.tmp", "bootnxt",
}


def classify(path):
    """按路径规则（优先）与扩展名（兜底）对文件/目录分类。"""
    p = path.lower()
    if p.endswith("\\") and len(p) > 3:
        p = p.rstrip("\\")
    base = os.path.basename(p)

    # 1. 回收站
    if "$recycle.bin" in p:
        return "回收站"

    # 2. 缓存 / 临时
    if "\\wer\\" in p or "\\windows\\wer" in p or "\\microsoft\\windows\\wer" in p:
        return "缓存临时"
    if any(m in p for m in _CACHE_MARKERS):
        return "缓存临时"

    # 3. 系统文件
    if p.startswith("c:\\windows") or p.startswith("c:\\system volume information"):
        return "系统文件"
    if base in _SYSTEM_ROOT_FILES:
        return "系统文件"

    # 4. 软件文件
    if p.startswith("c:\\program files") or p.startswith("c:\\program files (x86)"):
        return "软件文件"
    if p.startswith("c:\\programdata"):
        return "软件文件"
    if ("\\appdata\\local\\programs" in p or "\\appdata\\local\\microsoft\\" in p
            or "\\appdata\\roaming\\" in p or "\\appdata\\local\\" in p):
        return "软件文件"

    # 5. 数据文件
    if set(p.split("\\")) & _DATA_SEGMENTS:
        return "数据文件"

    # 6. 扩展名兜底
    if os.path.splitext(base)[1].lower() in _DATA_EXTS:
        return "数据文件"

    return "其他"
