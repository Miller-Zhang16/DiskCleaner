# -*- coding: utf-8 -*-
"""重复文件查找。

策略（兼顾速度与准确性，全部使用标准库）：
    1. 大小预筛：只有大小完全相同的文件才可能重复，先按体积分组；
    2. 轻量指纹：对同尺寸文件计算「大小 + 首尾各 4KB」的 BLAKE2b 指纹，
       绝大多数「大小相同但内容不同」的文件在这一步被排除；
    3. 精确确认：对指纹相同的文件计算 SHA-256，最终判定内容一致。

安全约定：
    - 不跟随重解析点（junction / symlink），避免扫描越界与死循环；
    - 跳过系统关键目录（Windows / Program Files / ProgramData 等）与程序自身目录；
    - 硬链接按 (st_dev, st_ino) 去重：删除其中一份并不会真正释放空间；
    - 扫描受「时间 + 条目」双重预算限制，超限返回部分结果并标记 truncated；
    - 本模块只做查找与分组，不执行任何删除。
"""

import hashlib
import os
import time
from dataclasses import dataclass, field

from ..utils.fmt import is_reparse_point, scandir_robust
from .runtime import app_root

DEFAULT_MIN_BYTES = 1024 * 1024
DEFAULT_BUDGET_SECONDS = 60.0
DEFAULT_BUDGET_ENTRIES = 300000
DEFAULT_MAX_GROUPS = 300
PROBE_BYTES = 4096
HASH_CHUNK = 1024 * 1024
PROGRESS_INTERVAL = 0.5

# 永不扫描的顶层关键目录：其中的文件要么不能删，要么（如 WinSxS）大量使用硬链接
PROTECTED_ROOTS = tuple(
    os.path.normcase(p).rstrip("\\") for p in (
        r"c:\windows",
        r"c:\program files",
        r"c:\program files (x86)",
        r"c:\programdata",
        r"c:\system volume information",
        r"c:\$recycle.bin",
        r"c:\recovery",
        r"c:\perflogs",
    )
)


@dataclass
class DuplicateGroup:
    """一组内容完全相同的文件。"""

    size: int
    digest: str
    files: list = field(default_factory=list)

    @property
    def count(self):
        return len(self.files)

    @property
    def reclaimable(self):
        """保留一份后可释放的字节数。"""
        return self.size * (self.count - 1)


def _is_protected(path):
    norm = os.path.normcase(os.path.abspath(path)).rstrip("\\")
    for root in PROTECTED_ROOTS:
        if norm == root or norm.startswith(root + os.sep):
            return True
    return False


def _probe(path, size):
    """计算轻量指纹；读取失败返回 None。"""
    h = hashlib.blake2b(digest_size=16)
    h.update(str(size).encode("ascii"))
    try:
        with open(path, "rb") as f:
            h.update(f.read(PROBE_BYTES))
            if size > PROBE_BYTES * 2:
                f.seek(size - PROBE_BYTES)
                h.update(f.read(PROBE_BYTES))
    except OSError:
        return None
    return h.hexdigest()


def _sha256(path, cancel=None):
    """分块计算 SHA-256；取消或读取失败返回 None。"""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while True:
                if cancel is not None and cancel.is_set():
                    return None
                chunk = f.read(HASH_CHUNK)
                if not chunk:
                    break
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def find_duplicates(root, min_size=DEFAULT_MIN_BYTES,
                    budget_seconds=DEFAULT_BUDGET_SECONDS,
                    budget_entries=DEFAULT_BUDGET_ENTRIES,
                    cancel=None, max_groups=DEFAULT_MAX_GROUPS,
                    progress=None):
    """在 ``root`` 下查找重复文件。

    返回 ``(groups, truncated, entries)``：
        groups      :class:`DuplicateGroup` 列表，按可释放空间降序
        truncated  是否因预算耗尽或取消而返回部分结果
        entries    已遍历的目录项数

    ``progress(entries, candidates)`` 会在遍历过程中被周期性调用
    （约每 0.5 秒一次），``candidates`` 是达到体积阈值的文件数。
    """
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        return [], False, 0

    deadline = time.monotonic() + max(1.0, float(budget_seconds))
    entries = 0
    candidates = 0
    truncated = False
    last_progress = 0.0
    by_size = {}
    seen_inodes = set()
    app_dir = os.path.normcase(os.path.abspath(app_root())).rstrip("\\")
    stack = [root]

    while stack:
        directory = stack.pop()
        norm = os.path.normcase(os.path.abspath(directory)).rstrip("\\")
        if _is_protected(directory):
            continue
        if app_dir and (norm == app_dir or norm.startswith(app_dir + os.sep)):
            continue
        try:
            it = scandir_robust(directory)
        except OSError:
            continue
        with it:
            for entry in it:
                if cancel is not None and cancel.is_set():
                    truncated = True
                    stack.clear()
                    break
                entries += 1
                if entries > budget_entries or time.monotonic() > deadline:
                    truncated = True
                    stack.clear()
                    break
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if is_reparse_point(st):
                    continue
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    is_dir = False
                if is_dir:
                    stack.append(entry.path)
                    continue
                try:
                    is_file = entry.is_file(follow_symlinks=False)
                except OSError:
                    is_file = False
                if not is_file or st.st_size < min_size:
                    continue

                # 硬链接去重：同一 inode 只保留一个路径
                # 注意：Windows 下 DirEntry.stat() 的 st_ino 恒为 0，必须用 entry.inode()
                try:
                    ino = entry.inode()
                except OSError:
                    ino = 0
                if ino:
                    if ino in seen_inodes:
                        continue
                    seen_inodes.add(ino)

                by_size.setdefault(st.st_size, []).append(entry.path)
                candidates += 1

        if progress is not None:
            now = time.monotonic()
            if now - last_progress >= PROGRESS_INTERVAL:
                last_progress = now
                progress(entries, candidates)

    groups = []
    for size, paths in by_size.items():
        if len(paths) < 2:
            continue

        # 第二轮：轻量指纹
        by_probe = {}
        for path in paths:
            if cancel is not None and cancel.is_set():
                truncated = True
                break
            sig = _probe(path, size)
            if sig is None:
                continue
            by_probe.setdefault(sig, []).append(path)
        if truncated and cancel is not None and cancel.is_set():
            break

        # 第三轮：SHA-256 精确确认
        for same in by_probe.values():
            if len(same) < 2:
                continue
            by_digest = {}
            for path in same:
                if cancel is not None and cancel.is_set():
                    truncated = True
                    break
                digest = _sha256(path, cancel)
                if digest is None:
                    continue
                by_digest.setdefault(digest, []).append(path)
            for digest, final in by_digest.items():
                if len(final) >= 2:
                    groups.append(DuplicateGroup(size=size, digest=digest,
                                                 files=final))
            if truncated and cancel is not None and cancel.is_set():
                break
        if truncated and cancel is not None and cancel.is_set():
            break

    groups.sort(key=lambda g: g.reclaimable, reverse=True)
    return groups[:max_groups], truncated, entries


def keep_path(files):
    """从一组重复文件中选出建议保留的副本：最早修改、其次路径最短。"""
    def rank(path):
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = float("inf")
        return (mtime, len(path), path)

    return min(files, key=rank)


def reclaimable_size(groups):
    """所有分组保留一份后可释放的总字节数。"""
    return sum(g.reclaimable for g in groups)
