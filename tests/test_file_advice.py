# -*- coding: utf-8 -*-
"""测试大文件可删性评估引擎。

重点：截图中真实出现的 pagefile.sys / hiberfil.sys / MEMORY.DMP / swapfile.sys
必须被判为「禁止删除」或「可清理」，绝不能让用户误删。
"""

from src.core.file_advice import (
    VERDICT_FORBID,
    VERDICT_KEEP,
    VERDICT_RISKY,
    VERDICT_SAFE,
    assess,
    summarize,
)


def test_system_root_files_are_forbidden():
    """截图中的系统文件必须被禁止删除。"""
    cases = {
        r"C:\pagefile.sys": "虚拟内存",
        r"C:\hiberfil.sys": "休眠",
        r"C:\swapfile.sys": "交换",
    }
    for path, keyword in cases.items():
        adv = assess(path, 10 * 1024**3)
        assert adv.verdict == VERDICT_FORBID, "%s 应为禁止删除" % path
        assert not adv.deletable
        assert keyword in adv.reason
        assert adv.action  # 必须给出安全释放路径


def test_hiberfil_provides_powercfg_command():
    adv = assess(r"C:\hiberfil.sys")
    assert "powercfg" in adv.command


def test_memory_dump_is_safe():
    """截图中的 MEMORY.DMP 应可安全删除。"""
    adv = assess(r"C:\Windows\MEMORY.DMP", 2 * 1024**3)
    assert adv.verdict == VERDICT_SAFE
    assert adv.deletable


def test_minidump_and_livekernel_safe():
    assert assess(r"C:\Windows\Minidump\123456-78901-01.dmp").verdict == VERDICT_SAFE
    assert assess(r"C:\Windows\LiveKernelReports\a.dmp").verdict == VERDICT_SAFE


def test_boot_files_forbidden():
    for p in [r"C:\bootmgr", r"C:\bootmgr.efi", r"C:\bootnxt"]:
        assert assess(p).verdict == VERDICT_FORBID


def test_windows_old_safe_with_cleanmgr():
    adv = assess(r"C:\Windows.old\Users\foo\big.zip")
    assert adv.verdict == VERDICT_SAFE
    assert "cleanmgr" in adv.command


def test_winsxs_forbidden_with_dism():
    adv = assess(r"C:\Windows\WinSxS\amd64_xxx\comp.dll")
    assert adv.verdict == VERDICT_FORBID
    assert "dism" in adv.command


def test_installer_cache_risky():
    adv = assess(r"C:\Windows\Installer\abc123.msi")
    assert adv.verdict == VERDICT_RISKY


def test_windows_temp_and_update_cache_safe():
    assert assess(r"C:\Windows\Temp\abc.tmp").verdict == VERDICT_SAFE
    assert assess(r"C:\Windows\SoftwareDistribution\Download\x.cab").verdict == VERDICT_SAFE


def test_system_volume_information_forbidden():
    adv = assess(r"C:\System Volume Information\{guid}\restore.dat")
    assert adv.verdict == VERDICT_FORBID


def test_driverstore_forbidden():
    assert assess(r"C:\Windows\System32\DriverStore\FileRepository\x.inf").verdict == VERDICT_FORBID


def test_generic_windows_path_risky():
    adv = assess(r"C:\Windows\Fonts\bigfont.ttf")
    assert adv.verdict == VERDICT_RISKY


def test_program_files_risky():
    adv = assess(r"C:\Program Files\Foo\bar.exe")
    assert adv.verdict == VERDICT_RISKY


def test_appdata_cache_safe_appdata_data_keep():
    assert assess(r"C:\Users\foo\AppData\Local\Chrome\User Data\Default\Cache\x").verdict == VERDICT_SAFE
    assert assess(r"C:\Users\foo\AppData\Roaming\Foo\config.db").verdict == VERDICT_KEEP


def test_user_downloads_keep():
    adv = assess(r"C:\Users\foo\Downloads\setup.exe", 500 * 1024**2)
    assert adv.verdict == VERDICT_KEEP


def test_disk_images_keep():
    for p in [r"D:\vm\disk.vmdk", r"D:\iso\windows.iso", r"D:\vm\disk.vhdx"]:
        assert assess(p).verdict == VERDICT_KEEP


def test_unknown_defaults_to_keep():
    adv = assess(r"D:\misc\unknown.bin")
    assert adv.verdict == VERDICT_KEEP
    assert adv.deletable


def test_summarize_counts_and_bytes():
    entries = [
        (10, r"C:\pagefile.sys"),       # FORBID
        (5, r"C:\Windows\MEMORY.DMP"),  # SAFE
        (3, r"C:\Windows\Temp\x.tmp"),  # SAFE
        (7, r"C:\Users\foo\Downloads\a.zip"),  # KEEP
    ]
    stats = summarize(entries)
    assert stats[VERDICT_FORBID] == (1, 10)
    assert stats[VERDICT_SAFE] == (2, 8)
    assert stats[VERDICT_KEEP] == (1, 7)
    assert stats[VERDICT_RISKY] == (0, 0)
