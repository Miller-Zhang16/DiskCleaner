# -*- coding: utf-8 -*-
"""测试扫描器：scan_dir_size 与 scan_large_files。

重点：
    - scan_large_files 按体积降序返回，top_n 截断，min_size 过滤；
    - 预算耗尽时返回 truncated=True；
    - 重解析点不被深入（junction 目标不计入）。
"""

import os
import subprocess
import threading

import pytest

from src.core.scanner import scan_dir_size, scan_large_files


def _make_junction(target, link):
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True, text=True)
    return result.returncode == 0


# ---------------- scan_large_files ----------------

def test_scan_large_files_sorted_and_top_n(tmp_path):
    sizes = [100000, 80000, 50000, 30000, 10000]
    for i, s in enumerate(sizes):
        (tmp_path / ("f%d.bin" % i)).write_bytes(b"x" * s)

    files, trunc, entries = scan_large_files(str(tmp_path), top_n=3)
    assert trunc is False
    assert len(files) == 3
    got = [s for s, _ in files]
    assert got == [100000, 80000, 50000]


def test_scan_large_files_min_size_filter(tmp_path):
    (tmp_path / "big.bin").write_bytes(b"x" * 100000)
    (tmp_path / "small.bin").write_bytes(b"x" * 1000)

    files, _, _ = scan_large_files(str(tmp_path), top_n=10, min_size=50000)
    names = [os.path.basename(p) for _, p in files]
    assert names == ["big.bin"]


def test_scan_large_files_recurses_subdirs(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"x" * 5000)
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.bin").write_bytes(b"x" * 9000)  # 子目录里的大文件

    files, _, _ = scan_large_files(str(tmp_path), top_n=10)
    got = sorted([s for s, _ in files], reverse=True)
    assert got == [9000, 5000]


def test_scan_large_files_budget_truncation(tmp_path):
    """预算极小时应提前返回并标记 truncated。"""
    # 造一些文件确保会触发条目预算
    for i in range(50):
        (tmp_path / ("f%d.bin" % i)).write_bytes(b"x" * 1000)

    files, trunc, entries = scan_large_files(
        str(tmp_path), top_n=100, budget_entries=5, budget_seconds=60)
    assert trunc is True
    assert entries <= 6  # 超出预算即停


def test_scan_large_files_cancel(tmp_path):
    for i in range(100):
        (tmp_path / ("f%d.bin" % i)).write_bytes(b"x" * 1000)

    cancel = threading.Event()
    cancel.set()  # 预先取消
    files, trunc, entries = scan_large_files(str(tmp_path), cancel=cancel)
    assert trunc is True
    assert entries == 0  # 第一个 entry 就检测到取消


def test_scan_large_files_skips_junction_target(tmp_path):
    """junction 目标的内容不应被计入扫描结果。"""
    if os.name != "nt":
        pytest.skip("仅 Windows")
    target = tmp_path / "target"
    target.mkdir()
    (target / "huge.bin").write_bytes(b"x" * 500000)

    root = tmp_path / "root"
    root.mkdir()
    (root / "small.bin").write_bytes(b"x" * 1000)

    if not _make_junction(target, root / "link"):
        pytest.skip("无法创建 junction")

    files, _, _ = scan_large_files(str(root), top_n=10)
    paths = [p for _, p in files]
    # huge.bin 位于 junction 目标内，不应出现
    assert not any("huge.bin" in p for p in paths)


# ---------------- scan_dir_size ----------------

def test_scan_dir_size_basic(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"x" * 100)
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.bin").write_bytes(b"y" * 200)

    size, trunc, entries = scan_dir_size(str(tmp_path))
    assert trunc is False
    assert size == 300
    assert entries >= 2


def test_scan_dir_size_budget_entries(tmp_path):
    for i in range(200):
        (tmp_path / ("f%d.bin" % i)).write_bytes(b"x" * 100)

    size, trunc, entries = scan_dir_size(str(tmp_path), budget_entries=10,
                                         budget_seconds=60)
    assert trunc is True
    assert entries <= 11
