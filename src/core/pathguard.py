# -*- coding: utf-8 -*-
"""路径分段保护。

内置目标都是明确的缓存/临时目录，但 ``custom_targets.txt`` 由用户自由填写，
可能指向用户资料或敏感配置目录。这里按路径「每一段」匹配保护名单，
避免 ``C:\\Users\\me\\Documents`` 这类路径被当成普通清理目录。

注意只保护用户数据与敏感配置，不包含 ``Windows``、``Program Files`` 等
系统目录——内置清理目标本身就在这些目录下，由 ``PROTECTED_PATHS`` 的
顶层白名单负责。
"""

import os

PROTECTED_SEGMENTS = {
    # 用户资料
    "desktop", "documents", "downloads", "pictures", "videos", "music",
    "onedrive", "dropbox",
    # 敏感配置
    ".ssh", ".gnupg", ".aws", ".azure", ".kube", ".config",
    ".git", ".svn", ".hg",
    # 开发工具配置
    ".vscode", ".idea", ".android", ".gradle", ".m2",
    # 系统关键目录
    "system volume information", "$recycle.bin",
}


def protected_segment(path):
    """返回路径中命中的保护段名（小写），未命中返回 None。"""
    if not path:
        return None
    try:
        normalized = os.path.normpath(os.path.abspath(path))
    except OSError:
        return None
    for seg in normalized.split(os.sep):
        low = seg.strip().lower()
        if low in PROTECTED_SEGMENTS:
            return low
    return None
