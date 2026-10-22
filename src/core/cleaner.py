# -*- coding: utf-8 -*-
"""删除执行器。

安全约定：
    - 删除前用 ``realpath`` + ``commonpath`` 校验目标落在白名单根目录内，
      防止 ``C:\\Windows\\Temp2`` 这类前缀绕过；
    - 遇到重解析点（junction / symlink）只删除链接本身，绝不深入链接目标
      —— 这是误删的最大来源；
    - 逐个文件容错：只读文件先尝试去掉只读属性，被占用（winerror 32）短重试，
      无权限直接跳过并记录，不中断整体流程；
    - 释放空间按「成功删除文件的 st_size 之和」统计（不用磁盘前后差值，
      避免被后台写入污染）。
"""

import os
import stat
import time

from ..utils.fmt import fmt_size, is_reparse_point, scandir_robust
from .recycle import empty_recycle_bin, recycle_bin_size
from .runtime import app_root
from .targets import resolve_target_paths


def default_skip_paths():
    """永不清理的路径：程序自身所在目录。"""
    return [app_root()]


# 禁止直接删除的顶层关键路径（浏览页右键删除时的保护名单）
PROTECTED_PATHS = {
    "c:\\",
    "c:\\windows",
    "c:\\program files",
    "c:\\program files (x86)",
    "c:\\programdata",
    "c:\\users",
    "c:\\system volume information",
    "c:\\$recycle.bin",
    "c:\\recovery",
    "c:\\perflogs",
}


def is_within(root_real, candidate):
    """校验候选路径是否落在指定根目录内。"""
    try:
        cand_real = os.path.realpath(candidate)
        common = os.path.commonpath([root_real, cand_real])
        return os.path.normcase(common) == os.path.normcase(root_real)
    except (ValueError, OSError):
        return False


def unlink_file(path):
    """删除单个文件。返回 ``(size_or_None, error_or_None)``。"""
    try:
        size = os.lstat(path).st_size
    except OSError:
        size = 0

    last_err = None
    for _ in range(3):
        try:
            os.remove(path)
            return size, None
        except FileNotFoundError:
            return 0, None
        except PermissionError as e:
            last_err = e
            try:
                os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            except OSError:
                pass
            time.sleep(0.15)
        except OSError as e:
            last_err = e
            if getattr(e, "winerror", None) == 32:  # 文件被占用
                time.sleep(0.2)
                continue
            break
    return None, str(last_err)


def _collect(root, min_age, now, cancel, skip_norm, root_real):
    """收集待删文件与目录（不深入重解析点）。"""
    files_to_delete = []
    dirs = []
    stack = [root]
    while stack:
        directory = stack.pop()
        if cancel is not None and cancel.is_set():
            break
        try:
            it = scandir_robust(directory)
        except OSError:
            continue
        with it:
            for entry in it:
                if cancel is not None and cancel.is_set():
                    break
                if not is_within(root_real, entry.path):
                    continue
                try:
                    real = os.path.normcase(os.path.realpath(entry.path))
                except OSError:
                    real = None
                if real is not None and real in skip_norm:
                    continue
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    is_dir = False

                if is_reparse_point(st):
                    files_to_delete.append(entry.path)  # 只删链接本身
                    continue
                if is_dir:
                    dirs.append(entry.path)
                    stack.append(entry.path)
                else:
                    if min_age is not None and now is not None:
                        if (now - st.st_mtime) < min_age:
                            continue
                    files_to_delete.append(entry.path)
    return files_to_delete, dirs


def delete_tree_contents(root, min_age=None, now=None, cancel=None, skip_paths=None):
    """删除目录 ``root`` 下的所有内容（保留 root 本身）。

    返回 ``(freed_bytes, deleted_files, skipped, message)``。
    """
    if not os.path.isdir(root):
        return 0, 0, [], "目录不存在：%s" % root

    root_real = os.path.realpath(root)
    skip_norm = set()
    for sp in (skip_paths if skip_paths is not None else default_skip_paths()):
        try:
            skip_norm.add(os.path.normcase(os.path.realpath(sp)))
        except OSError:
            pass

    # 若目标目录本身位于受保护路径内（例如程序自身目录），整体放弃
    for sp in skip_norm:
        if is_within(sp, root):
            return 0, 0, [], "目录位于受保护路径内，已跳过：%s" % root

    files_to_delete, dirs = _collect(root, min_age, now, cancel, skip_norm, root_real)
    freed = 0
    deleted = 0
    skipped = []
    for p in files_to_delete:
        if cancel is not None and cancel.is_set():
            break
        size, err = unlink_file(p)
        if err is None:
            freed += size or 0
            deleted += 1
        else:
            skipped.append((p, err))

    # 自深至浅删除空目录（非空或占用则忽略）
    dirs.sort(key=lambda x: x.count(os.sep), reverse=True)
    for d in dirs:
        if cancel is not None and cancel.is_set():
            break
        try:
            if os.path.normcase(os.path.realpath(d)) in skip_norm:
                continue
        except OSError:
            continue
        try:
            os.rmdir(d)
        except OSError:
            pass

    return freed, deleted, skipped, None


def execute_target(target, cancel=None, log=None, skip_paths=None,
                   budget_seconds=None, budget_entries=None):
    """执行单个清理目标。返回 ``(freed_bytes, deleted_items, skipped, message)``。"""
    name = target["name"]
    min_age = target.get("min_age")
    now = time.time() if min_age else None

    if target.get("recycle"):
        before = recycle_bin_size()
        ok, msg = empty_recycle_bin()
        if log:
            log("[%s] %s" % (name, msg))
        if ok:
            return (before or 0), 1, [], None
        return 0, 0, [], msg

    dirs, files = resolve_target_paths(target)
    total_freed = 0
    total_deleted = 0
    all_skipped = []

    for d in dirs:
        freed, deleted, skipped, _ = delete_tree_contents(
            d, min_age=min_age, now=now, cancel=cancel, skip_paths=skip_paths)
        total_freed += freed
        total_deleted += deleted
        all_skipped.extend(skipped)
        if log:
            log("[%s] 清理 %s：释放 %s，删除 %d 项" % (name, d, fmt_size(freed), deleted))

    for f in files:
        if cancel is not None and cancel.is_set():
            break
        if min_age is not None:
            try:
                if (now - os.lstat(f).st_mtime) < min_age:
                    continue
            except OSError:
                continue
        size, err = unlink_file(f)
        if err is None:
            total_freed += size or 0
            total_deleted += 1
        else:
            all_skipped.append((f, err))

    return total_freed, total_deleted, all_skipped, None
