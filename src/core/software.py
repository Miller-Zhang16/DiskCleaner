# -*- coding: utf-8 -*-
"""C 盘已安装软件扫描。

通过注册表 ``Uninstall`` 键列出系统里登记过的软件安装项，
过滤出落在 C 盘、体积可观且不属于系统关键组件的候选，
交给迁移流程搬去其他盘。

注册表来源
    - ``HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall``（64 位安装）
    - ``HKLM\\SOFTWARE\\WOW6432Node\\...Uninstall``（32 位安装）
    - ``HKCU\\SOFTWARE\\...Uninstall``（当前用户级安装）

可迁移判定
    - 安装目录必须在 C 盘且真实存在；
    - EstimatedSize（注册表自带，KB）或实测体积 ≥ 阈值；
    - 排除 Windows Update、Security Update、系统驱动等无 InstallLocation 的条目；
    - 排除 Microsoft Corporation 的核心系统组件（Office / VS / Windows Defender
      等），但保留发行商为 Microsoft 但属于开发工具类的条目可让用户自行决定。
"""

import os
import winreg
from dataclasses import dataclass
from typing import Optional

from ..utils.fmt import scandir_robust

# ---------- 注册表路径 ----------
_REG_KEYS = [
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
]

# ---------- 风险等级 ----------
RISK_FORBID = "forbid"    # 禁止迁移（系统组件）
RISK_WARN = "warn"        # 迁移需谨慎（Microsoft 发行商但非系统核心）
RISK_SAFE = "safe"        # 可安全迁移（第三方）

# 必须排除的发行商关键词（小写匹配）
_FORBIDDEN_PUBLISHER_HINTS = (
    "trend micro",
    "sangfor",
    "microsoft security",
    "microsoft corporation",   # 核心系统组件走名称黑名单，其余走 warn
    "windows update",
    "malicious software",
    "defender",
    "sql server",
    "internet explorer",
)

# 必须排除的 DisplayName 关键词（小写）
_FORBIDDEN_NAME_HINTS = (
    "security update",
    "update for",
    "hotfix",
    "microsoft visual c++ redistributable",   # 运行库，多软件共用
    "microsoft visual c++ runtime",
    "microsoft edge webview",
    "microsoft 365",
    "antivirus",
    "security agent",
    "endpoint security",
    "antimalware",
)

# 可选让用户自行判断但不自动过滤的
_WARN_PUBLISHER_HINTS = (
    "intel",       # 驱动类
    "amd",
    "realtek",
)

# 扫描阈值：EstimatedSize < 这个值（KB）的忽略
_MIN_EST_KB = 50 * 1024   # 50 MB


@dataclass
class SoftwareItem:
    """一个可候选的安装项。"""
    name: str
    publisher: str
    version: str
    install_dir: str           # 安装目录（原始）
    install_dir_norm: str = "" # 规范化后的绝对路径
    estimated_size: int = 0    # 注册表自带（KB），0 表示缺失
    actual_size: int = 0       # 实测目录体积（字节），0 表示未实测
    install_date: str = ""
    uninstall_cmd: str = ""
    risk: str = RISK_SAFE
    reason_key: str = ""      # 风险说明的 i18n key（由界面层翻译）
    reason_hint: str = ""     # 说明中的可变片段（发行商 / 组件名）
    source: str = ""          # 来源：HKLM/32bit/HKCU
    checked: bool = True      # UI 默认是否勾选

    @property
    def effective_size(self) -> int:
        return self.actual_size or (self.estimated_size * 1024)


# ---------------------------------------------------------------------------
# 注册表枚举
# ---------------------------------------------------------------------------


def _open_subkey(parent_hive, subpath) -> Optional[winreg.HKEY_TYPE]:
    try:
        return winreg.OpenKey(parent_hive, subpath, 0, winreg.KEY_READ)
    except OSError:
        return None


def _iter_installation_items() -> list[tuple[str, str, dict]]:
    """遍历全部注册表来源，返回 (source_label, item_name, values) 列表。"""
    results = []
    for hive, subpath in _REG_KEYS:
        label = {
            winreg.HKEY_LOCAL_MACHINE: "HKLM",
            winreg.HKEY_CURRENT_USER: "HKCU",
        }.get(hive, "REG")
        key = _open_subkey(hive, subpath)
        if key is None:
            continue
        try:
            idx = 0
            while True:
                try:
                    sub_name = winreg.EnumKey(key, idx)
                except OSError:
                    break   # No more data
                idx += 1
                sub = _open_subkey(key, sub_name)
                if sub is None:
                    continue
                values = {}
                try:
                    vidx = 0
                    while True:
                        try:
                            vname, vdata, vtype = winreg.EnumValue(sub, vidx)
                        except OSError:
                            break
                        vidx += 1
                        values[vname] = vdata
                finally:
                    try:
                        winreg.CloseKey(sub)
                    except OSError:
                        pass
                results.append((label, sub_name, values))
        finally:
            try:
                winreg.CloseKey(key)
            except OSError:
                pass
    return results


# ---------------------------------------------------------------------------
# 过滤与风险判定
# ---------------------------------------------------------------------------


def _norm_drive(path: str) -> str:
    """路径所在盘符的小写形式。"""
    return os.path.splitdrive(os.path.abspath(path))[0].lower()


def _classify_risk(publisher: str, name: str) -> tuple[str, str, str]:
    """根据发行商和名称判定风险等级。

    返回 (risk, reason_key, reason_hint)。reason_key 是界面层用来翻译说明的键，
    核心层不依赖 i18n 模块。

    判定顺序：
      1) 名称黑名单（运行库、安全软件、Edge 等）→ FORBID
      2) Microsoft Corporation：仅 Edge / Defender / 365 → FORBID；其余 → WARN
      3) 发行商黑名单（安全厂商等）→ FORBID
      4) 发行商警告（驱动厂商）→ WARN
      5) 其他 → SAFE
    """
    pub_low = (publisher or "").lower()
    name_low = (name or "").lower()

    # (1) 名称黑名单（最高优先级）
    for hint in _FORBIDDEN_NAME_HINTS:
        if hint in name_low:
            return RISK_FORBID, "sw.reason.name_forbid", hint

    # (2) Microsoft Corporation 特殊处理
    if pub_low == "microsoft corporation":
        _ms_forbid = (
            "microsoft edge", "edge webview", "microsoft 365",
            "microsoft defender", "windows security",
        )
        for hint in _ms_forbid:
            if hint in name_low:
                return RISK_FORBID, "sw.reason.ms_forbid", hint
        return RISK_WARN, "sw.reason.ms_warn", ""

    # (3) 发行商黑名单
    for hint in _FORBIDDEN_PUBLISHER_HINTS:
        if hint in pub_low:
            return RISK_FORBID, "sw.reason.publisher_forbid", hint

    # (4) 警告发行商
    for hint in _WARN_PUBLISHER_HINTS:
        if hint in pub_low:
            return RISK_WARN, "sw.reason.publisher_warn", hint

    return RISK_SAFE, "", ""


def is_c_drive(path: str) -> bool:
    """判断路径是否在 C 盘。"""
    return _norm_drive(path) == "c:"


# ---------------------------------------------------------------------------
# 目录体积实测
# ---------------------------------------------------------------------------


def measure_dir_size(path: str, cancel=None) -> int:
    """递归统计目录体积（字节）。取消时返回当前已统计值。"""
    total = 0
    stack = [path]
    while stack:
        if cancel is not None and cancel.is_set():
            return total
        d = stack.pop()
        try:
            it = scandir_robust(d)
        except OSError:
            continue
        with it:
            for entry in it:
                if cancel is not None and cancel.is_set():
                    return total
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    is_dir = False
                if is_dir:
                    stack.append(entry.path)
                else:
                    total += st.st_size
    return total


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def scan_candidates(
    cancel=None,
    min_est_kb: int = _MIN_EST_KB,
    measure_actual: bool = True,
    on_progress=None,
) -> list[SoftwareItem]:
    """扫描注册表，返回落在 C 盘的可候选安装项列表。

    ``measure_actual=True`` 时会对每项安装目录递归计算真实体积，
    对大目录耗时较长；若只需注册表自带的 EstimatedSize，传 False。
    """
    raw = _iter_installation_items()
    items: list[SoftwareItem] = []
    seen_dirs: set[str] = set()
    total = len(raw)

    for idx, (source, sub_name, values) in enumerate(raw):
        if cancel is not None and cancel.is_set():
            break
        if on_progress is not None:
            on_progress(idx, total, values.get("DisplayName", sub_name))

        name = (values.get("DisplayName") or "").strip()
        install_dir = (values.get("InstallLocation") or "").strip().rstrip("\\/").strip('"')
        if not install_dir or not os.path.isdir(install_dir):
            continue

        # 必须在 C 盘
        if not is_c_drive(install_dir):
            continue

        norm_dir = os.path.normcase(os.path.abspath(install_dir)).rstrip("\\/")
        if norm_dir in seen_dirs:
            continue
        seen_dirs.add(norm_dir)

        estimated_kb = int(values.get("EstimatedSize", 0) or 0)
        if estimated_kb < min_est_kb:
            continue

        publisher = (values.get("Publisher") or "").strip()
        version = (values.get("DisplayVersion") or "").strip()
        install_date = (values.get("InstallDate") or "").strip()
        uninstall_cmd = (values.get("UninstallString") or "").strip()

        risk, reason_key, reason_hint = _classify_risk(publisher, name)

        item = SoftwareItem(
            name=name or sub_name,
            publisher=publisher,
            version=version,
            install_dir=install_dir,
            install_dir_norm=norm_dir,
            estimated_size=estimated_kb,
            install_date=install_date,
            uninstall_cmd=uninstall_cmd,
            risk=risk,
            reason_key=reason_key,
            reason_hint=reason_hint,
            source=source,
            checked=(risk != RISK_FORBID),
        )

        if measure_actual and risk != RISK_FORBID:
            item.actual_size = measure_dir_size(install_dir, cancel=cancel)

        items.append(item)

    # 按体积降序
    items.sort(key=lambda x: x.effective_size, reverse=True)
    return items


# ---------------------------------------------------------------------------
# 辅助：风险判定的 UI 展示标签
# ---------------------------------------------------------------------------


RISK_LABELS = {
    RISK_FORBID: ("sw.risk.forbid", "SW_RISK_FORBID"),
    RISK_WARN:   ("sw.risk.warn",   "SW_RISK_WARN"),
    RISK_SAFE:   ("sw.risk.safe",   "SW_RISK_SAFE"),
}
