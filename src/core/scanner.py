# -*- coding: utf-8 -*-
"""目录大小扫描（懒加载）。

性能与稳定性要点：
    - 使用显式栈而非递归，避免深层目录触发 RecursionError；
    - 遇到重解析点（junction / symlink）不深入、不计入，防止死循环与误删；
    - 每个目录单独 ``try/except OSError``，权限不足或文件被删不会中断整次扫描；
    - 单次扫描有「时间 + 条目数」双重预算，超限即返回下界并标记 truncated；
    - 硬链接按 ``(st_dev, st_ino)`` 去重，但仅在 inode 有效（非 0）时去重。
"""

import time

from ..utils.fmt import is_reparse_point, scandir_robust

DEFAULT_BUDGET_SECONDS = 6.0
DEFAULT_BUDGET_ENTRIES = 200000


def scan_dir_size(path, budget_seconds=DEFAULT_BUDGET_SECONDS,
                  budget_entries=DEFAULT_BUDGET_ENTRIES,
                  cancel=None, min_age=None, now=None):
    """统计目录下所有文件占用的字节数。

    返回 ``(bytes, truncated, entries)``：
        bytes      统计到的字节数（truncated 为 True 时是估算下界）
        truncated  是否因预算耗尽或取消而提前结束
        entries    已遍历的目录项数

    ``min_age`` / ``now`` 同时给出时，只统计修改时间早于 ``now - min_age`` 的文件。
    """
    total = 0
    entries = 0
    start = time.monotonic()
    seen = set()
    stack = [path]

    while stack:
        directory = stack.pop()
        try:
            it = scandir_robust(directory)
        except OSError:
            continue
        with it:
            for entry in it:
                if cancel is not None and cancel.is_set():
                    return total, True, entries
                entries += 1
                if entries > budget_entries or (time.monotonic() - start) > budget_seconds:
                    return total, True, entries
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    is_dir = False

                if is_reparse_point(st):
                    continue  # 不深入链接目标，链接本身体积可忽略
                if is_dir:
                    stack.append(entry.path)
                    continue

                # 普通文件
                if min_age is not None and now is not None:
                    if (now - st.st_mtime) < min_age:
                        continue
                if st.st_ino:  # 仅在 inode 有效时做硬链接去重（部分卷恒为 0）
                    key = (st.st_dev, st.st_ino)
                    if key in seen:
                        continue
                    seen.add(key)
                total += st.st_size

    return total, False, entries


def list_dir_children(path):
    """列出目录的直接子项。返回 ``(dirs, files)``。

    dirs  : ``[(name, full_path, None, is_link)]``   —— 大小待异步计算
    files : ``[(name, full_path, size, is_link)]``   —— 文件大小可直接取得

    重解析点单独标注 ``is_link=True``，界面只展示不深入。
    """
    dirs = []
    files = []
    try:
        it = scandir_robust(path)
    except OSError:
        return dirs, files

    with it:
        for entry in it:
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                is_dir = False

            link = is_reparse_point(st)
            if is_dir:
                dirs.append((entry.name, entry.path, None, link))
            else:
                size = 0 if link else st.st_size
                files.append((entry.name, entry.path, size, link))

    dirs.sort(key=lambda x: x[0].lower())
    files.sort(key=lambda x: x[0].lower())
    return dirs, files
