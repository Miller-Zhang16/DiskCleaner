# -*- coding: utf-8 -*-
"""测试文件/目录分类逻辑。

重点：
    - 分类优先级正确（回收站 > 缓存临时 > 系统 > 软件 > 数据 > 其他）；
    - 用户数据目录（桌面、文档、下载等）绝不会被归为「缓存临时」；
    - OneDriveTemp 这类带 Temp 字样但属于数据目录的路径不被误判；
    - 扩展名兜底只在前面规则都不命中时生效。
"""

from src.core.classify import CATEGORIES, CATEGORY_COLORS, classify


def test_categories_and_colors_consistent():
    """颜色表必须覆盖所有分类。"""
    assert set(CATEGORY_COLORS) == set(CATEGORIES)


def test_recycle_bin_priority():
    """回收站优先级最高，即便路径里也含 temp。"""
    p = r"C:\$Recycle.Bin\S-1-5-21\$R123ABC.tmp"
    assert classify(p) == "回收站"


def test_cache_temp_markers():
    cases = [
        r"C:\Windows\Temp\xxx",
        r"C:\Windows\Prefetch\a.pf",
        r"C:\Windows\SoftwareDistribution\Download\abc.cab",
        r"C:\Users\foo\AppData\Local\Microsoft\Windows\WER\foo.txt",
        r"C:\Users\foo\AppData\Local\Google\Chrome\User Data\Default\Cache\a",
        r"C:\ProgramData\Microsoft\Windows\DeliveryOptimization\cache\a",
    ]
    for p in cases:
        assert classify(p) == "缓存临时", p


def test_system_files():
    cases = [
        r"C:\Windows\System32\ntdll.dll",
        r"C:\System Volume Information\abc",
        r"C:\pagefile.sys",
        r"C:\hiberfil.sys",
    ]
    for p in cases:
        assert classify(p) == "系统文件", p


def test_software_files():
    cases = [
        r"C:\Program Files\Foo\bar.exe",
        r"C:\Program Files (x86)\Foo\bar.exe",
        r"C:\ProgramData\Foo\config.json",
        r"C:\Users\foo\AppData\Roaming\Foo\bar",
        r"C:\Users\foo\AppData\Local\Microsoft\WindowsApps\foo",
    ]
    for p in cases:
        assert classify(p) == "软件文件", p


def test_user_data_never_temp():
    """用户数据目录绝不被判为缓存临时。"""
    data_cases = [
        r"C:\Users\foo\Desktop\report.docx",
        r"C:\Users\foo\Documents\notes.txt",
        r"C:\Users\foo\Downloads\installer.zip",
        r"C:\Users\foo\Pictures\vacation.jpg",
        r"C:\Users\foo\OneDrive\Documents\x.docx",
    ]
    for p in data_cases:
        cat = classify(p)
        assert cat != "缓存临时", "%s -> %s (不应被判为缓存临时)" % (p, cat)
        assert cat == "数据文件", p


def test_onedrive_temp_not_cache():
    """OneDriveTemp 含 Temp 字样但属于数据目录，不应判为缓存临时。"""
    p = r"C:\Users\foo\OneDriveTemp\file.txt"
    assert classify(p) == "数据文件"


def test_extension_fallback():
    """前面规则都不命中时，扩展名兜底为数据文件。"""
    cases = [
        r"D:\misc\report.pdf",
        r"E:\archive\backup.zip",
        r"C:\somewhere\photo.png",
    ]
    for p in cases:
        assert classify(p) == "数据文件", p


def test_unknown_fallback_to_other():
    p = r"D:\weird\file.xyz"
    assert classify(p) == "其他"


def test_trailing_backslash_stripped():
    """目录路径末尾的反斜杠不影响分类。"""
    assert classify(r"C:\Windows\Temp\\") == "缓存临时"
    assert classify(r"C:\Users\foo\Desktop\\") == "数据文件"
