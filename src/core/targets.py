# -*- coding: utf-8 -*-
"""清理目标表。

内置目标遵循「保守且安全」原则：只包含公认可安全清理的临时/缓存/日志类项目。

明确**不**作为可清理项列出（属于系统关键资源）：
    hiberfil.sys、pagefile.sys、swapfile.sys、WinSxS、C:\\Windows\\Installer、
    System32、$Recycle.Bin 目录本身、卷影副本、用户数据目录。

目标字段：
    key          唯一标识，同时作为 settings.ini 中的勾选状态键
    name         界面显示名
    paths        目录 / 文件 / glob 模式列表
    recycle      True 表示该项为「清空回收站」
    category     分类（用于着色）
    risk         风险等级：低 / 中 / 高
    needs_admin  是否需要管理员权限
    default      默认是否勾选（安全项为 True）
    min_age      只清理该时长（秒）之前的项目
    desc / note  说明与额外提示
"""

import glob
import os
import time

from ..utils.fmt import expand_path, is_glob
from .scanner import scan_dir_size

# 浏览器缓存中允许清理的子目录（绝不触碰 User Data 其余部分）
BROWSER_CACHE_SUBDIRS = (
    ("Cache",),
    ("Code Cache",),
    ("GPUCache",),
    ("Service Worker", "CacheStorage"),
)

DEFAULT_TEMP_MIN_AGE = 24 * 3600


def _builtin_targets(config):
    L = expand_path(r"%LOCALAPPDATA%")
    P = expand_path(r"%PROGRAMDATA%")
    U = expand_path(r"%USERPROFILE%")
    W = r"C:\Windows"
    temp_min_age = config.temp_min_age_seconds if config is not None else DEFAULT_TEMP_MIN_AGE

    def browser_cache(sub, vendor_path):
        base = os.path.join(L, *vendor_path)
        return [os.path.join(base, *parts) for parts in BROWSER_CACHE_SUBDIRS]

    return [
        # ---------------- 免管理员 / 免停机 / 默认勾选 ----------------
        dict(key="user_temp", name="用户临时文件",
             paths=[expand_path(r"%TEMP%"), os.path.join(L, "Temp")],
             category="缓存临时", risk="低", needs_admin=False, default=True,
             min_age=temp_min_age,
             desc="用户级临时文件，仅清理超过设定时长的项目"),
        dict(key="wer_user", name="Windows 错误报告（用户）",
             paths=[os.path.join(L, "Microsoft", "Windows", "WER")],
             category="缓存临时", risk="低", needs_admin=False, default=True,
             desc="崩溃与错误报告缓存"),
        dict(key="crash_user", name="应用崩溃转储（用户）",
             paths=[os.path.join(L, "CrashDumps")],
             category="缓存临时", risk="低", needs_admin=False, default=True,
             desc="应用崩溃时生成的转储文件"),
        dict(key="uwp_cache", name="UWP 应用缓存",
             paths=[os.path.join(L, "Packages", "*", "LocalCache"),
                    os.path.join(L, "Packages", "*", "TempState")],
             category="缓存临时", risk="低", needs_admin=False, default=True,
             desc="商店应用的本地缓存与临时状态"),
        dict(key="edge_cache", name="Edge 浏览器缓存",
             paths=browser_cache("edge", ("Microsoft", "Edge", "User Data", "Default")),
             category="缓存临时", risk="低", needs_admin=False, default=True,
             desc="仅清理缓存子目录，不影响书签、密码、历史",
             note="建议先关闭 Edge 浏览器"),
        dict(key="chrome_cache", name="Chrome 浏览器缓存",
             paths=browser_cache("chrome", ("Google", "Chrome", "User Data", "Default")),
             category="缓存临时", risk="低", needs_admin=False, default=True,
             desc="仅清理缓存子目录，不影响书签、密码、历史",
             note="建议先关闭 Chrome 浏览器"),

        # ---------------- 需管理员 / 默认勾选 ----------------
        dict(key="win_temp", name="系统临时文件",
             paths=[os.path.join(W, "Temp")],
             category="缓存临时", risk="低", needs_admin=True, default=True,
             desc="Windows 系统级临时目录"),
        dict(key="win_update_dl", name="Windows 更新下载缓存",
             paths=[os.path.join(W, "SoftwareDistribution", "Download")],
             category="缓存临时", risk="低", needs_admin=True, default=True,
             desc="已下载的更新安装包缓存",
             note="删除后系统需要时会重新下载更新"),
        dict(key="wer_system", name="Windows 错误报告（系统）",
             paths=[os.path.join(P, "Microsoft", "Windows", "WER", "ReportQueue"),
                    os.path.join(P, "Microsoft", "Windows", "WER", "ReportArchive"),
                    os.path.join(P, "Microsoft", "Windows", "WER", "Temp")],
             category="缓存临时", risk="低", needs_admin=True, default=True,
             desc="系统级错误报告队列与归档"),
        dict(key="dump_system", name="内核转储与内存转储",
             paths=[os.path.join(W, "Minidump"), os.path.join(W, "MEMORY.DMP")],
             category="缓存临时", risk="中", needs_admin=True, default=True,
             desc="蓝屏小型转储与完整内存转储，可能较大",
             note="如需保留蓝屏分析资料，可取消勾选"),
        dict(key="cbs_log", name="CBS 组件安装日志",
             paths=[os.path.join(W, "Logs", "CBS")],
             category="缓存临时", risk="低", needs_admin=True, default=True,
             desc="组件服务安装日志，通常可达数百 MB"),
        dict(key="live_kernel", name="实时内核报告",
             paths=[os.path.join(W, "LiveKernelReports")],
             category="缓存临时", risk="低", needs_admin=True, default=True,
             desc="系统实时内核事件报告"),

        # ---------------- 可选 / 默认不勾 ----------------
        dict(key="recycle", name="清空回收站",
             paths=[], recycle=True,
             category="回收站", risk="中", needs_admin=False, default=False,
             desc="清空 C 盘回收站，删除后不可恢复"),
        dict(key="delivery_opt", name="传递优化缓存",
             paths=[os.path.join(W, "SoftwareDistribution", "DeliveryOptimization"),
                    os.path.join(W, "ServiceProfiles", "NetworkService", "AppData",
                                 "Local", "Microsoft", "Windows", "DeliveryOptimization")],
             category="缓存临时", risk="低", needs_admin=True, default=False,
             desc="Windows 更新与应用的 P2P 分发缓存",
             note="建议先停止 DoSvc（传递优化）服务后再清理"),
        dict(key="prefetch", name="预读取 Prefetch 数据",
             paths=[os.path.join(W, "Prefetch")],
             category="缓存临时", risk="中", needs_admin=True, default=False,
             desc="开机预读取缓存",
             note="SSD 上收益极低，删除后前几次开机反而变慢，不建议清理"),
        dict(key="thumb_cache", name="缩略图 / 图标缓存",
             paths=[os.path.join(L, "Microsoft", "Windows", "Explorer", "thumbcache_*.db"),
                    os.path.join(L, "Microsoft", "Windows", "Explorer", "iconcache_*.db")],
             category="缓存临时", risk="中", needs_admin=False, default=False,
             desc="资源管理器缩略图与图标缓存",
             note="需重启资源管理器(explorer.exe)生效，任务栏会短暂闪烁"),
        dict(key="windows_old", name="旧版 Windows（Windows.old）",
             paths=[r"C:\Windows.old"],
             category="系统文件", risk="高", needs_admin=True, default=False,
             desc="系统升级备份，通常数 GB 至数十 GB",
             note="删除后将无法回滚到旧版系统"),
        dict(key="downloads", name="下载文件夹",
             paths=[os.path.join(U, "Downloads")],
             category="数据文件", risk="高", needs_admin=False, default=False,
             desc="你的下载文件，可能包含重要内容",
             note="请自行确认后再清理"),
    ]


def _custom_targets(config):
    """把 data/custom_targets.txt 中的目录包装成清理目标。"""
    if config is None:
        return []
    out = []
    for i, raw_path in enumerate(config.custom_targets()):
        p = expand_path(raw_path)
        base = os.path.basename(p.rstrip("\\")) or p
        out.append(dict(
            key="custom_%d" % i, name="自定义：%s" % base,
            paths=[p], category="其他", risk="中", needs_admin=False,
            default=False, custom=True,
            desc="来自 data/custom_targets.txt 的自定义清理目录"))
    return out


def build_targets(config=None):
    """构造清理目标列表，并同步勾选状态到配置。

    config 为 None 时使用内置默认勾选状态（便于单元测试）。
    """
    targets = _builtin_targets(config) + _custom_targets(config)
    for t in targets:
        default = bool(t.get("default", False))
        if config is not None:
            config.ensure_target(t["key"], default)
            default = config.target_default(t["key"], default)
        t["_checked"] = default
        t["_size"] = None
        t["_trunc"] = False
    return targets


def resolve_target_paths(target):
    """把目标的 ``paths`` 展开为实际存在的 ``(目录列表, 文件列表)``。"""
    dirs, files = [], []
    seen = set()
    for raw in target.get("paths", []):
        p = expand_path(raw)
        candidates = glob.glob(p) if is_glob(p) else [p]
        for m in candidates:
            try:
                key = os.path.normcase(os.path.abspath(m))
            except OSError:
                continue
            if key in seen:
                continue
            if os.path.isdir(m):
                seen.add(key)
                dirs.append(m)
            elif os.path.isfile(m):
                seen.add(key)
                files.append(m)
    return dirs, files


def estimate_target_size(target, cancel=None, budget_seconds=None, budget_entries=None):
    """估算某清理项可释放的空间。返回 ``(bytes_or_None, truncated)``。"""
    if target.get("recycle"):
        from .recycle import recycle_bin_size
        return recycle_bin_size(), False

    dirs, files = resolve_target_paths(target)
    if not dirs and not files:
        return 0, False

    min_age = target.get("min_age")
    now = time.time() if min_age else None
    total = 0
    truncated = False

    kwargs = {"cancel": cancel, "min_age": min_age, "now": now}
    if budget_seconds is not None:
        kwargs["budget_seconds"] = budget_seconds
    if budget_entries is not None:
        kwargs["budget_entries"] = budget_entries

    for d in dirs:
        b, trunc, _ = scan_dir_size(d, **kwargs)
        total += b
        truncated = truncated or trunc

    for f in files:
        try:
            st = os.lstat(f)
        except OSError:
            continue
        if min_age is not None and (now - st.st_mtime) < min_age:
            continue
        total += st.st_size

    return total, truncated
