# -*- coding: utf-8 -*-
"""测试删除执行器的安全边界。

重点：
    - is_within() 必须拒绝前缀绕过（如 C:\\Windows\\Temp2 不属于 C:\\Windows\\Temp）；
    - delete_tree_contents() 对位于受保护路径内的目录整体放弃；
    - skip_paths 中的目录及其内容不被删除；
    - 重解析点（junction）只删链接本身，不深入目标。
"""

import os
import stat
import subprocess

import pytest

from src.core.cleaner import (
    PROTECTED_PATHS,
    delete_tree_contents,
    is_within,
    unlink_file,
)

# ---------------- is_within ----------------

def test_is_within_accepts_child():
    root = os.path.realpath(os.getcwd())
    assert is_within(root, os.path.join(root, "sub", "file.txt")) is True


def test_is_within_rejects_prefix_traversal():
    """C:\\Windows\\Temp2 不应落在 C:\\Windows\\Temp 内。"""
    root = os.path.realpath(r"C:\Windows\Temp")
    cand = r"C:\Windows\Temp2\evil"
    assert is_within(root, cand) is False


def test_is_within_rejects_sibling():
    root = os.path.realpath(r"C:\Windows\Temp")
    cand = r"C:\Windows\System32"
    assert is_within(root, cand) is False


def test_is_within_invalid_path_returns_false():
    assert is_within(r"C:\valid", "") is False
    assert is_within(r"C:\valid", "\x00bad") is False


# ---------------- delete_tree_contents ----------------

@pytest.fixture
def sandbox(tmp_path):
    """创建一个临时目录树用于清理测试。"""
    root = tmp_path / "clean_root"
    root.mkdir()
    (root / "a.txt").write_text("x" * 100)
    sub = root / "sub"
    sub.mkdir()
    (sub / "b.txt").write_text("y" * 200)
    (sub / "c.txt").write_text("z" * 50)
    return root


def test_delete_tree_contents_removes_files(sandbox):
    freed, deleted, skipped, msg = delete_tree_contents(str(sandbox))
    assert msg is None
    assert deleted == 3
    assert freed == 100 + 200 + 50
    assert skipped == []
    # root 本身保留，内容清除
    assert sandbox.exists()
    assert not (sandbox / "a.txt").exists()


def test_delete_tree_contents_skips_protected_subdir(sandbox, tmp_path):
    """skip_paths 指向的目录及其内容不被删除。"""
    protected = tmp_path / "protected"
    protected.mkdir()
    (protected / "keep.txt").write_text("keep")

    freed, deleted, skipped, msg = delete_tree_contents(
        str(sandbox), skip_paths=[str(protected)])
    assert msg is None
    assert deleted == 3
    # 受保护目录本身未被触动
    assert (protected / "keep.txt").exists()


def test_delete_tree_contents_root_inside_protected(sandbox, tmp_path):
    """若清理目标本身位于 skip_paths 内，整体放弃。"""
    # 让 sandbox 成为 protected 的子目录
    protected = tmp_path / "protected"
    protected.mkdir()
    inner = protected / "inner"
    inner.mkdir()
    (inner / "x.txt").write_text("x")

    freed, deleted, skipped, msg = delete_tree_contents(
        str(inner), skip_paths=[str(protected)])
    assert "受保护路径内" in msg
    assert freed == 0 and deleted == 0


def test_delete_tree_contents_nonexistent_dir():
    freed, deleted, skipped, msg = delete_tree_contents(r"C:\no_such_dir_xyz_123")
    assert "目录不存在" in msg
    assert freed == 0 and deleted == 0


# ---------------- unlink_file ----------------

def test_unlink_file_removes_and_returns_size(tmp_path):
    f = tmp_path / "f.bin"
    f.write_bytes(b"a" * 42)
    size, err = unlink_file(str(f))
    assert err is None
    assert size == 42
    assert not f.exists()


def test_unlink_file_missing_returns_zero(tmp_path):
    size, err = unlink_file(str(tmp_path / "missing.bin"))
    assert err is None
    assert size == 0


def test_unlink_file_readonly(tmp_path):
    f = tmp_path / "ro.bin"
    f.write_bytes(b"b" * 10)
    os.chmod(str(f), stat.S_IREAD)
    try:
        size, err = unlink_file(str(f))
    finally:
        # 兜底恢复，防止影响后续
        try:
            os.chmod(str(f), stat.S_IWRITE)
        except OSError:
            pass
    assert err is None
    assert size == 10
    assert not f.exists()


# ---------------- 重解析点（junction）只删链接 ----------------

def _make_junction(target, link):
    """用 mklink /J 创建 junction，非管理员也可创建。"""
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True, text=True)
    return result.returncode == 0


def test_junction_target_outside_root_not_deleted(tmp_path):
    """junction 指向清理根目录外时，其外部目标内容不得被删除。

    这是防误删的核心保证：_collect 用 realpath + commonpath 校验，
    指向根目录外的重解析点会被整体跳过。
    """
    if os.name != "nt":
        pytest.skip("junction 测试仅在 Windows 有效")
    target = tmp_path / "target"
    target.mkdir()
    (target / "inside.txt").write_text("inside")

    root = tmp_path / "clean"
    root.mkdir()
    (root / "real.txt").write_text("real")  # 根目录内的真实文件

    if not _make_junction(target, root / "link"):
        pytest.skip("无法创建 junction（可能权限不足）")

    freed, deleted, skipped, msg = delete_tree_contents(str(root))
    assert msg is None
    # 根目录内的真实文件被删除
    assert not (root / "real.txt").exists()
    # junction 指向的外部目标内容完好
    assert target.exists()
    assert (target / "inside.txt").exists()


# ---------------- PROTECTED_PATHS 覆盖关键路径 ----------------

def test_protected_paths_cover_critical_top_level():
    for p in ["c:\\", "c:\\windows", "c:\\program files", "c:\\users"]:
        assert p in PROTECTED_PATHS
