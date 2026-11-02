# -*- coding: utf-8 -*-
"""目录迁移：把 C 盘上的大目录搬到其他盘，并在原路径留下目录链接。

用途
    有些目录（缓存、模型、日志）单个体积很大但位置固定，删掉会破坏程序。
    迁移把它们搬到空间充足的盘，并在原路径建立 junction，程序仍然按原路径
    读写，磁盘占用却转移到了别的盘。

三阶段状态机（每阶段幂等，中断后可从记录里继续）
    planned         复制到「目标.part」，校验文件数与体积后用 os.rename 原子改名
    copied          删除源目录内容（此时数据已完整落在目标盘）
    source_deleted  在原路径创建 junction 指向目标目录
    linked          完成

安全约定
    - 拒绝迁移系统关键目录（Windows / Program Files / ProgramData 等），
      以及程序自身目录；
    - 源目录内只要存在重解析点（junction / symlink）就拒绝迁移，避免
      跨链接复制成环或复制到其他盘；
    - 目标必须不存在，且必须与源在**不同的盘**；
    - 先复制、再校验、最后才删源：任何一步失败都不会丢数据；
    - junction 用 ``mklink /J`` 创建，普通用户即可（不需要管理员）；
    - 复制阶段写入 ``<目标>.part``，校验通过才改名，避免半成品被误用。
"""

import json
import os
import shutil
import subprocess
import time

from ..utils.fmt import fmt_size, is_reparse_point, long_path, scandir_robust
from .cleaner import delete_tree_contents
from .runtime import app_root

# 阶段
STAGE_PLANNED = "planned"
STAGE_COPIED = "copied"
STAGE_SOURCE_DELETED = "source_deleted"
STAGE_LINKED = "linked"

# 禁止迁移的系统目录（含其子目录）
_FORBIDDEN_TREES = {
    "c:\\windows",
    "c:\\program files",
    "c:\\program files (x86)",
    "c:\\programdata",
    "c:\\system volume information",
    "c:\\$recycle.bin",
    "c:\\recovery",
    "c:\\perflogs",
    "c:\\boot",
}

# 禁止迁移的顶层目录（仅禁止该目录本身，允许其子目录）
_FORBIDDEN_EXACT = {
    "c:\\",
    "c:\\users",
    "c:\\$windows.~bt",
}

# 目标盘剩余空间的安全余量
_FREE_SPACE_MARGIN = 64 * 1024 * 1024
_CHUNK = 1024 * 1024


def _norm(path):
    """规范化路径用于比较（小写、统一反斜杠、去掉结尾分隔符）。"""
    return os.path.normcase(os.path.abspath(path)).rstrip("\\/")


def _drive(path):
    return os.path.splitdrive(os.path.abspath(path))[0].lower()


def is_protected(path):
    """路径是否为系统关键目录（含其子目录）。"""
    real = _norm(os.path.realpath(path))
    if real in _FORBIDDEN_EXACT:
        return True
    for root in _FORBIDDEN_TREES:
        if real == root or real.startswith(root + "\\"):
            return True
    # 程序自身目录及其子目录
    try:
        own = _norm(os.path.realpath(app_root()))
        if real == own or real.startswith(own + "\\"):
            return True
    except OSError:
        pass
    return False


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------


def validate(src, dst, size=None):
    """检查迁移参数，返回问题列表（空列表表示可以开始）。

    ``size`` 为源目录总体积（未知时传 None，跳过空间校验）。
    """
    problems = []

    if not src:
        problems.append("请填写源目录。")
    if not dst:
        problems.append("请填写目标目录。")
    if not src or not dst:
        return problems

    src_abs = os.path.abspath(src)
    dst_abs = os.path.abspath(dst)

    if not os.path.isdir(src_abs):
        problems.append("源目录不存在：%s" % src_abs)
    else:
        try:
            st = os.lstat(src_abs)
        except OSError as e:
            problems.append("无法读取源目录：%s" % e)
        else:
            if is_reparse_point(st):
                problems.append("源目录本身是目录链接，不能迁移。")
        if is_protected(src_abs):
            problems.append("源目录属于系统关键目录，禁止迁移：%s" % src_abs)
        if not os.path.dirname(src_abs.rstrip("\\/")):
            problems.append("不能迁移整个盘符根目录。")

    same_drive = _drive(src_abs) == _drive(dst_abs)
    if same_drive:
        problems.append("源目录与目标目录在同一个盘，迁移没有意义（请选其他盘）。")
        # 跨盘时 commonpath 会抛 ValueError，包含关系只在同盘时有意义
        try:
            src_real = os.path.realpath(src_abs)
            dst_real = os.path.realpath(dst_abs)
            if os.path.commonpath([src_real, dst_real]) == dst_real:
                problems.append("目标目录不能位于源目录内部。")
            if os.path.commonpath([src_real, dst_real]) == src_real:
                problems.append("源目录不能位于目标目录内部。")
        except (ValueError, OSError):
            problems.append("路径无效：%s / %s" % (src_abs, dst_abs))

    if os.path.exists(dst_abs):
        problems.append("目标目录已存在，请换一个不存在的路径：%s" % dst_abs)
    parent = os.path.dirname(dst_abs)
    if parent and not os.path.isdir(parent):
        problems.append("目标目录的上级目录不存在：%s" % parent)
    if is_protected(dst_abs):
        problems.append("目标目录位于系统关键目录内，禁止迁移到此处：%s" % dst_abs)

    if size is not None and size > 0:
        try:
            free = shutil.disk_usage(parent or dst_abs).free
        except OSError as e:
            problems.append("无法读取目标盘剩余空间：%s" % e)
        else:
            if free < size + _FREE_SPACE_MARGIN:
                problems.append("目标盘剩余空间不足：需要 %s，可用 %s"
                                % (fmt_size(size + _FREE_SPACE_MARGIN),
                                   fmt_size(free)))

    return problems


def estimate(src, cancel=None):
    """估算目录体积与文件数。

    返回 ``(总字节, 文件数, 条目数, 重解析点列表, 读取失败列表)``。
    """
    total = 0
    files = 0
    entries = 0
    links = []
    errors = []
    stack = [src]
    while stack:
        if cancel is not None and cancel.is_set():
            break
        directory = stack.pop()
        try:
            it = scandir_robust(directory)
        except OSError as e:
            errors.append((directory, str(e)))
            continue
        with it:
            for entry in it:
                if cancel is not None and cancel.is_set():
                    break
                entries += 1
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError as e:
                    errors.append((entry.path, str(e)))
                    continue
                if is_reparse_point(st):
                    links.append(entry.path)
                    continue
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    is_dir = False
                if is_dir:
                    stack.append(entry.path)
                else:
                    total += st.st_size
                    files += 1
    return total, files, entries, links, errors


# ---------------------------------------------------------------------------
# 复制 / 校验
# ---------------------------------------------------------------------------


def _copy_file(src, dst, cancel=None):
    """复制单个文件并保留时间戳。返回 (复制字节数, 错误或 None)。"""
    s = long_path(src)
    d = long_path(dst)
    copied = 0
    try:
        with open(s, "rb") as fsrc, open(d, "wb") as fdst:
            while True:
                if cancel is not None and cancel.is_set():
                    raise InterruptedError("用户取消")
                buf = fsrc.read(_CHUNK)
                if not buf:
                    break
                fdst.write(buf)
                copied += len(buf)
    except InterruptedError:
        raise
    except OSError as e:
        try:
            os.remove(d)
        except OSError:
            pass
        return 0, str(e)
    try:
        stat = os.stat(s)
        os.utime(d, (stat.st_atime, stat.st_mtime))
    except OSError:
        pass
    return copied, None


def copy_tree(src, dst, total_bytes=None, cancel=None, on_progress=None):
    """把 ``src`` 完整复制到 ``dst``（dst 需已存在且为空）。

    返回 ``(ok, 复制字节数, 文件数, 失败列表, 是否取消)``。
    失败列表为 ``[(源路径, 原因)]``。
    """
    copied = 0
    files = 0
    failures = []
    cancelled = False
    stack = [src]
    while stack:
        if cancel is not None and cancel.is_set():
            cancelled = True
            break
        directory = stack.pop()
        rel = os.path.relpath(directory, src)
        target_dir = dst if rel in (".", "") else os.path.join(dst, rel)
        try:
            os.makedirs(target_dir, exist_ok=True)
        except OSError as e:
            failures.append((directory, "创建目录失败：%s" % e))
            continue
        try:
            it = scandir_robust(directory)
        except OSError as e:
            failures.append((directory, "读取目录失败：%s" % e))
            continue
        with it:
            for entry in it:
                if cancel is not None and cancel.is_set():
                    cancelled = True
                    break
                target = os.path.join(target_dir, entry.name)
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError as e:
                    failures.append((entry.path, "读取失败：%s" % e))
                    continue
                if is_reparse_point(st):
                    failures.append((entry.path, "包含目录链接，已中止（请先处理该链接）"))
                    cancelled = True
                    break
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    is_dir = False
                if is_dir:
                    stack.append(entry.path)
                    continue
                try:
                    size, err = _copy_file(entry.path, target, cancel)
                except InterruptedError:
                    cancelled = True
                    break
                if err is not None:
                    failures.append((entry.path, "复制失败：%s" % err))
                    continue
                copied += size
                files += 1
                if on_progress is not None:
                    on_progress(copied, total_bytes or copied, entry.path)
    return (not failures and not cancelled), copied, files, failures, cancelled


def verify_copy(src, dst):
    """逐文件比对体积，返回不一致项列表（最多 20 条）。"""
    problems = []
    stack = [src]
    while stack:
        directory = stack.pop()
        rel = os.path.relpath(directory, src)
        target_dir = dst if rel in (".", "") else os.path.join(dst, rel)
        try:
            it = scandir_robust(directory)
        except OSError:
            continue
        with it:
            for entry in it:
                if len(problems) >= 20:
                    return problems
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    is_dir = False
                if is_dir:
                    if not os.path.isdir(os.path.join(target_dir, entry.name)):
                        problems.append("缺少目录：%s" % entry.path)
                    stack.append(entry.path)
                    continue
                target = os.path.join(target_dir, entry.name)
                try:
                    target_size = os.stat(long_path(target)).st_size
                except OSError:
                    problems.append("缺少文件：%s" % entry.path)
                    continue
                if target_size != st.st_size:
                    problems.append("体积不一致：%s（%d ≠ %d）"
                                    % (entry.path, st.st_size, target_size))
    return problems


# ---------------------------------------------------------------------------
# 删除源 / 目录链接
# ---------------------------------------------------------------------------


def purge_source(src, cancel=None):
    """删除源目录内容并移除空目录。返回 ``(已删字节, 已删项, 失败列表)``。"""
    freed, deleted, skipped, message = delete_tree_contents(
        src, cancel=cancel, skip_paths=[])
    if message:
        return 0, 0, [(src, message)]
    try:
        os.rmdir(src)
    except OSError as e:
        # 目录内仍有未删除文件时删除失败，交由调用方判定
        if skipped:
            return freed, deleted, skipped
        return freed, deleted, [(src, str(e))]
    return freed, deleted, skipped


def create_junction(link, target):
    """在原路径创建指向 ``target`` 的目录链接。返回 ``(ok, 消息)``。"""
    if os.path.exists(link) or os.path.islink(link):
        return False, "路径已存在，无法创建链接：%s" % link
    if not os.path.isdir(target):
        return False, "链接目标不存在：%s" % target
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", link, target],
            capture_output=True, creationflags=flags)
    except OSError as e:
        return False, "无法执行 mklink：%s" % e
    if proc.returncode != 0:
        # cmd 输出是系统 ANSI 编码（中文系统为 GBK），统一按字节解码避免乱码
        raw = proc.stderr or proc.stdout or b""
        try:
            detail = raw.decode("mbcs")
        except (UnicodeDecodeError, LookupError):
            detail = raw.decode("utf-8", "replace")
        return False, "创建目录链接失败（返回码 %d）%s" % (
            proc.returncode, detail.strip())
    return True, "已创建目录链接"


def remove_junction(link):
    """删除目录链接本身（不触碰链接目标）。返回 ``(ok, 消息)``。"""
    try:
        st = os.lstat(link)
    except OSError as e:
        return False, "路径不存在：%s" % e
    if not is_reparse_point(st):
        return False, "该路径不是目录链接，已拒绝删除：%s" % link
    try:
        # junction 用 os.rmdir 删除时只移除链接本身
        os.rmdir(link)
    except OSError as e:
        return False, "删除目录链接失败：%s" % e
    return True, "已删除目录链接"


# ---------------------------------------------------------------------------
# 迁移记录
# ---------------------------------------------------------------------------


class MigrationStore:
    """迁移记录（JSON 文件，原子写入）。"""

    def __init__(self, path):
        self.path = path
        self._records = self._load()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        return [r for r in data if isinstance(r, dict) and r.get("src")]

    def load(self):
        return [dict(r) for r in self._records]

    def get(self, src):
        key = _norm(src)
        for r in self._records:
            if _norm(r["src"]) == key:
                return dict(r)
        return None

    def upsert(self, record):
        key = _norm(record["src"])
        record["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        for i, r in enumerate(self._records):
            if _norm(r["src"]) == key:
                self._records[i] = dict(record)
                break
        else:
            record.setdefault("created", record["updated"])
            self._records.append(dict(record))
        self._save()
        return dict(record)

    def remove(self, src):
        key = _norm(src)
        before = len(self._records)
        self._records = [r for r in self._records if _norm(r["src"]) != key]
        if len(self._records) != before:
            self._save()
            return True
        return False

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._records, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def _wipe(path):
    """删除本程序自己产生的目录（.part 或已复制目标）。"""
    if not os.path.isdir(path):
        return True
    try:
        st = os.lstat(path)
    except OSError:
        return True
    if is_reparse_point(st):
        # 残留的链接只删链接本身，绝不深入目标
        ok, _ = remove_junction(path)
        return ok
    try:
        delete_tree_contents(path, skip_paths=[])
        os.rmdir(path)
        return True
    except OSError:
        return False


def _do_copy(record, cancel, on_progress, log, store):
    src = record["src"]
    dst = record["dst"]
    part = dst + ".part"
    remove_junction(part)  # 万一 .part 残留为链接
    if not _wipe(part):
        return False, "无法清空上次残留的临时目录：%s" % part
    total = record.get("size") or None
    if log:
        log("开始复制：%s → %s.part" % (src, dst))
    ok, copied, files, failures, cancelled = copy_tree(
        src, part, total, cancel, on_progress)
    if cancelled:
        return False, "复制已取消，源目录未改动。"
    if failures:
        first = failures[0]
        return False, "复制失败（共 %d 项）：%s → %s" % (
            len(failures), first[0], first[1])
    problems = verify_copy(src, part)
    if problems:
        return False, "复制校验未通过：%s" % problems[0]

    # 校验通过后再改名，避免半成品出现在用户指定的目标路径
    if os.path.exists(dst):
        return False, "目标目录已存在，请移走后重试：%s" % dst
    try:
        os.rename(part, dst)
    except OSError as e:
        return False, "无法把临时目录改名为目标目录：%s" % e

    record["size"] = copied
    record["files"] = files
    record["stage"] = STAGE_COPIED
    store.upsert(record)
    if log:
        log("复制完成并校验通过：%d 个文件，%s" % (files, fmt_size(copied)))
    return True, "复制完成"


def _do_delete_source(record, cancel, log, store):
    src = record["src"]
    if log:
        log("开始删除源目录内容：%s" % src)
    freed, deleted, skipped = purge_source(src, cancel)
    if skipped:
        first = skipped[0]
        return False, "源目录仍有 %d 项未能删除：%s → %s（可关闭占用后重试）" % (
            len(skipped), first[0], first[1])
    record["stage"] = STAGE_SOURCE_DELETED
    store.upsert(record)
    if log:
        log("源目录已清空：删除 %d 项" % deleted)
    return True, "源目录已清空"


def _do_link(record, cancel, log, store):
    src = record["src"]
    dst = record["dst"]
    if log:
        log("开始创建目录链接：%s → %s" % (src, dst))
    ok, msg = create_junction(src, dst)
    if not ok:
        return False, msg
    record["stage"] = STAGE_LINKED
    store.upsert(record)
    if log:
        log(msg)
    return True, msg


def migrate(record, cancel=None, on_progress=None, log=None, store=None):
    """推进迁移记录到下一阶段，返回 ``(record, ok, message)``。

    已完成的阶段会被跳过，因此中断后重复调用即可续跑。
    """
    if store is None:
        raise ValueError("migrate 需要 store 以持久化阶段")
    stage = record.get("stage", STAGE_PLANNED)
    if stage == STAGE_LINKED:
        return record, True, "该迁移已完成"

    if stage == STAGE_PLANNED:
        ok, msg = _do_copy(record, cancel, on_progress, log, store)
        if not ok:
            return record, False, msg
        stage = record["stage"]

    if stage == STAGE_COPIED:
        if cancel is not None and cancel.is_set():
            return record, False, "已取消，源目录保持原样。"
        ok, msg = _do_delete_source(record, cancel, log, store)
        if not ok:
            return record, False, msg
        stage = record["stage"]

    if stage == STAGE_SOURCE_DELETED:
        if cancel is not None and cancel.is_set():
            return record, False, "已取消：源目录已删除，数据完整保存在目标目录。"
        ok, msg = _do_link(record, cancel, log, store)
        if not ok:
            return record, False, msg

    return record, True, "迁移完成"


def undo(record, cancel=None, log=None, store=None):
    """撤销迁移（仅限「待复制 / 已复制」阶段，源数据仍完整）。

    - planned：删除残留的 .part 临时目录；
    - copied：删除目标副本，源目录未动，可安全恢复；
    - 之后阶段源数据已删除，返回 False 并提示改用「继续迁移」。
    """
    stage = record.get("stage", STAGE_PLANNED)
    src = record["src"]
    dst = record["dst"]

    if stage in (STAGE_SOURCE_DELETED, STAGE_LINKED):
        return False, "源目录已删除，数据只存在于目标目录，不能直接撤销。\n" \
                      "请继续完成迁移，或手动把目标目录内容复制回原路径。"

    part = dst + ".part"
    if os.path.isdir(part) and not _wipe(part):
        return False, "无法删除临时目录：%s" % part
    if stage == STAGE_COPIED and os.path.isdir(dst):
        ok, msg = _remove_copied(dst)
        if not ok:
            return False, msg
    if store is not None:
        store.remove(src)
    if log:
        log("已撤销迁移并清理目标副本：%s" % src)
    return True, "已撤销"


def _remove_copied(dst):
    """删除本程序复制出来的目标目录（必须先确认是普通目录）。"""
    try:
        st = os.lstat(dst)
    except OSError as e:
        return True, "目标目录已不存在：%s" % e
    if is_reparse_point(st):
        return False, "目标目录是链接，已拒绝删除：%s" % dst
    if not _wipe(dst):
        return False, "无法删除目标副本：%s" % dst
    return True, "已删除目标副本"
