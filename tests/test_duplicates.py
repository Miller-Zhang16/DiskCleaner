# -*- coding: utf-8 -*-
"""测试重复文件查找：分组、体积过滤、硬链接与保留规则。"""

import os

import pytest

from src.core.duplicates import find_duplicates, keep_path, reclaimable_size


def _dup_pair(tmp_path, size=12000, prefix=b"A"):
    """在根目录与子目录各放一份内容相同、体积超过指纹阈值的文件。"""
    a = tmp_path / "a.bin"
    a.write_bytes(prefix * size)
    sub = tmp_path / "sub"
    sub.mkdir()
    b = sub / "b.bin"
    b.write_bytes(prefix * size)
    return str(a), str(b)


def test_finds_identical_files(tmp_path):
    a, b = _dup_pair(tmp_path)
    groups, trunc, entries = find_duplicates(str(tmp_path), min_size=1024)
    assert trunc is False
    assert entries > 0
    assert len(groups) == 1
    assert sorted(groups[0].files) == sorted([a, b])
    assert groups[0].size == 12000
    assert groups[0].reclaimable == 12000


def test_same_size_different_content_not_grouped(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"A" * 12000)
    (tmp_path / "b.bin").write_bytes(b"B" * 12000)
    groups, _, _ = find_duplicates(str(tmp_path), min_size=1024)
    assert groups == []


def test_min_size_filter(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"A" * 1000)
    (tmp_path / "b.bin").write_bytes(b"A" * 1000)
    groups, _, _ = find_duplicates(str(tmp_path), min_size=2048)
    assert groups == []


def test_hardlink_not_counted(tmp_path):
    a = tmp_path / "a.bin"
    a.write_bytes(b"A" * 12000)
    b = tmp_path / "b.bin"
    try:
        os.link(a, b)
    except (OSError, NotImplementedError):
        pytest.skip("当前文件系统不支持硬链接")
    groups, _, _ = find_duplicates(str(tmp_path), min_size=1024)
    assert groups == []


def test_keep_path_prefers_earliest(tmp_path):
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    for path in (a, b):
        path.write_bytes(b"A" * 12000)
    os.utime(a, (1000, 1000))
    os.utime(b, (2000, 2000))
    assert keep_path([str(a), str(b)]) == str(a)
    assert keep_path([str(b), str(a)]) == str(a)


def test_reclaimable_size(tmp_path):
    a, b = _dup_pair(tmp_path, size=5000, prefix=b"C")
    c = tmp_path / "sub" / "c.bin"
    c.write_bytes(b"C" * 5000)
    groups, _, _ = find_duplicates(str(tmp_path), min_size=1024)
    assert len(groups) == 1
    assert groups[0].count == 3
    assert reclaimable_size(groups) == 10000


def test_invalid_root_returns_empty(tmp_path):
    groups, trunc, entries = find_duplicates(str(tmp_path / "missing"))
    assert groups == []
    assert trunc is False
    assert entries == 0
