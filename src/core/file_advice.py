# -*- coding: utf-8 -*-
"""大文件可删性评估。

大文件页常扫出 pagefile.sys、hiberfil.sys、MEMORY.DMP 这类由系统独占或
与系统状态强绑定的文件。它们「体积巨大但绝不能直接删」，直接删除要么
必然失败（被内核锁定），要么导致蓝屏、无法休眠、无法卸载补丁等后果。

本模块为单个路径给出评估结论，回答用户真正关心的三个问题：
    1. 能不能删？            → verdict
    2. 为什么？              → reason
    3. 怎样安全释放空间？     → action（含可选命令行 command，由用户自行执行）

安全约定：本模块只做判断与建议，不执行任何操作。命令文本仅供展示与复制，
绝不由程序自动运行——评判权与执行权始终在用户手中。

评估结论：
    禁止删除   系统独占或删除即致故障，仅提供安全释放路径
    高风险     可删但有明确副作用，需用户二次确认
    可清理     可安全删除，本程序可直接清理
    建议保留   用户个人数据或无法判定，交由用户决定
"""

import os
from dataclasses import dataclass

VERDICT_FORBID = "禁止删除"
VERDICT_RISKY = "高风险"
VERDICT_SAFE = "可清理"
VERDICT_KEEP = "建议保留"

VERDICTS = (VERDICT_FORBID, VERDICT_RISKY, VERDICT_SAFE, VERDICT_KEEP)


@dataclass(frozen=True)
class Advice:
    """单个文件的评估结果。"""

    verdict: str
    reason: str
    action: str
    command: str = ""

    @property
    def deletable(self):
        """是否允许通过本程序直接删除（仅「禁止删除」会被拦下）。"""
        return self.verdict != VERDICT_FORBID


def assess(path, size=0):
    """评估一个文件的可删性，返回 :class:`Advice`。"""
    p = os.path.normcase(os.path.normpath(path))
    base = os.path.basename(p)

    # ---- 一、按文件名精确匹配的系统根文件 / 引导文件 ----
    if base == "pagefile.sys":
        return Advice(
            VERDICT_FORBID,
            "虚拟内存页面文件，由内存管理器独占访问。运行中必然被锁定，"
            "强行删除会导致程序崩溃或蓝屏。",
            "到「系统属性 → 高级 → 性能设置 → 高级 → 更改虚拟内存」："
            "可将该文件移到非系统盘，或按实际内存大小调小上限，"
            "保存重启后体积才会变化。",
        )
    if base == "hiberfil.sys":
        return Advice(
            VERDICT_FORBID,
            "休眠镜像文件，由电源管理驱动独占。系统启用休眠或快速启动时无法删除，"
            "强删会导致休眠功能失效甚至启动异常。",
            "以管理员身份运行下方命令可关闭休眠并立即释放全部空间；"
            "若想保留快速启动，改用第二行命令只压缩体积（约减半）。",
            "powercfg /h off",
        )
    if base == "swapfile.sys":
        return Advice(
            VERDICT_FORBID,
            "UWP 应用使用的交换文件，与页面文件同属内存管理子系统，无法单独删除。",
            "只能随虚拟内存设置一同管理："
            "「系统属性 → 高级 → 性能设置 → 高级 → 更改虚拟内存」调整后重启生效。",
        )
    if base in ("bootmgr", "bootmgr.efi", "bootnxt", "ntldr"):
        return Advice(
            VERDICT_FORBID,
            "系统引导文件，删除后电脑将无法开机。",
            "不可删除。若它在扫描结果中体积异常，请检查磁盘是否受损。",
        )

    # ---- 二、内存转储与崩溃日志 ----
    if base == "memory.dmp" or "\\windows\\memory.dmp" in p:
        return Advice(
            VERDICT_SAFE,
            "蓝屏时的完整内存转储，仅用于事后排查，日常无用途，可安全删除。",
            "可直接删除释放空间。若不再需要蓝屏分析，"
            "可在「系统属性 → 高级 → 启动和故障恢复」把"
            "「写入调试信息」设为「（无）」，避免再次生成。",
            "wmic recoveros set DebugInfoType=0",
        )
    if "\\windows\\minidump\\" in p or (base.endswith(".dmp") and "\\minidump\\" in p):
        return Advice(
            VERDICT_SAFE,
            "小型内存转储文件，属崩溃排查残留，可安全删除。",
            "可直接删除。",
        )
    if "\\windows\\livekernelreports\\" in p or "\\livekernelreports\\" in p:
        return Advice(
            VERDICT_SAFE,
            "内核实时故障报告，属诊断残留，可安全删除。",
            "可直接删除。",
        )
    if "\\windows\\logs\\cbs\\" in p or base == "cbs.log":
        return Advice(
            VERDICT_SAFE,
            "组件安装服务（CBS）日志，仅记录补丁安装过程，可安全删除。",
            "可直接删除；系统在下次需要时会自动重建。",
        )

    # ---- 三、Windows.old 与 WinSxS ----
    if "\\windows.old" in p:
        return Advice(
            VERDICT_SAFE,
            "旧版本 Windows 的备份（系统升级后保留），超过 10 天即自动可删，"
            "用于回退到上一版本。确认不需要回退时可安全清理。",
            "推荐用系统自带方式清理（会同时清掉权限与残留）："
            "「设置 → 系统 → 存储 → 临时文件」勾选「以前的 Windows 安装」，"
            "或运行下方命令。",
            "cleanmgr /sageset:1",
        )
    if "\\windows\\winsxs" in p:
        return Advice(
            VERDICT_FORBID,
            "组件存储（WinSxS），存放系统组件与补丁的硬链接备份。"
            "目录体积是被大量硬链接重复统计的结果，手动删除会破坏系统更新与修复能力。",
            "绝不可手动删除。正确做法是用 DISM 清理被取代的旧组件，"
            "以管理员身份运行下方命令（耗时较长，通常可释放数 GB）。",
            "dism /online /cleanup-image /startcomponentcleanup /resetbase",
        )
    if "\\windows\\installer" in p:
        return Advice(
            VERDICT_RISKY,
            "Windows Installer 的补丁与安装缓存（.msi/.msp）。"
            "删除后已安装程序将无法卸载、修复或升级。",
            "不要手动删除。如确需回收，请使用专门的孤立补丁清理工具核对后再处理。",
        )

    # ---- 四、可安全清理的系统缓存 ----
    if "\\windows\\temp" in p:
        return Advice(
            VERDICT_SAFE,
            "系统临时目录，安装与运行过程的残留，可安全删除。",
            "可直接删除；被占用的文件会自动跳过。",
        )
    if "\\windows\\softwaredistribution\\download" in p:
        return Advice(
            VERDICT_SAFE,
            "Windows 更新下载缓存，补丁安装完成后即无用，可安全删除。",
            "可直接删除；系统会在下次更新时重新下载。",
        )
    if "\\windows\\prefetch" in p:
        return Advice(
            VERDICT_SAFE,
            "预读取缓存，用于加速程序启动。删除安全，但短期内程序启动会略慢。",
            "可直接删除，系统会逐步重建。",
        )
    if "\\system volume information" in p:
        return Advice(
            VERDICT_FORBID,
            "系统还原点与卷影副本的存储区，受系统保护，普通权限无法删除。",
            "不要手动删除。需要回收时打开「系统属性 → 系统保护」，"
            "选中 C 盘点「配置」，调小「最大使用量」或删除旧还原点。",
        )
    if "$recycle.bin" in p:
        return Advice(
            VERDICT_SAFE,
            "回收站中的文件，已在清理建议页提供一并清空。",
            "可在「清理建议」页勾选「回收站」统一清空，或直接删除。",
        )

    # ---- 五、其余系统目录 ----
    if "\\windows\\system32\\driverstore" in p:
        return Advice(
            VERDICT_FORBID,
            "驱动仓库，保存所有已安装驱动的副本，删除会导致设备驱动失效。",
            "不可手动删除。可用「设备管理器」卸载不再使用的旧设备来间接释放。",
        )
    if "\\windows\\" in p:
        return Advice(
            VERDICT_RISKY,
            "位于 Windows 系统目录下，删除可能影响系统组件或已安装功能。",
            "建议先确认该文件用途；不确定时请保留。",
        )

    # ---- 六、程序与用户数据 ----
    if "\\program files" in p:
        return Advice(
            VERDICT_RISKY,
            "已安装程序的组成部分，直接删除会破坏该软件。",
            "请通过「设置 → 应用」或该软件自带的卸载程序移除，不要手动删除。",
        )
    if "\\appdata\\" in p:
        if "\\cache" in p or "\\code cache" in p or "\\gpucache" in p:
            return Advice(
                VERDICT_SAFE,
                "应用缓存目录，删除后应用会自动重建，可安全清理。",
                "可直接删除。",
            )
        return Advice(
            VERDICT_KEEP,
            "应用配置或数据目录，删除可能丢失登录状态与本地数据。",
            "请先确认对应软件的可清理项，或使用软件自带的清理功能。",
        )
    if "\\users\\" in p or "\\3d objects" in p:
        if "\\downloads\\" in p:
            return Advice(
                VERDICT_KEEP,
                "下载目录中的个人文件，删除不可恢复。",
                "请确认不再需要后再自行删除；若是安装包，重装时可重新下载。",
            )
        return Advice(
            VERDICT_KEEP,
            "个人数据文件，删除不可恢复，且不属于系统可清理范围。",
            "请自行确认用途后决定是否删除。",
        )

    # ---- 七、兜底 ----
    if base.endswith((".iso", ".vmdk", ".vdi", ".vhd", ".vhdx")):
        return Advice(
            VERDICT_KEEP,
            "镜像或虚拟机磁盘文件，体积大但通常有特定用途。",
            "请确认不再需要后自行删除。",
        )
    return Advice(
        VERDICT_KEEP,
        "无法根据路径判断其用途，交由你自行确认。",
        "建议先「在资源管理器中打开位置」核对，确认后再决定是否删除。",
    )


def summarize(entries):
    """汇总评估结果，返回 {结论: (个数, 字节数)}。

    ``entries`` 为 ``[(size, path), ...]``。
    """
    stats = dict.fromkeys(VERDICTS, (0, 0))
    for size, path in entries:
        verdict = assess(path, size).verdict
        count, total = stats[verdict]
        stats[verdict] = (count + 1, total + size)
    return stats
