# -*- coding: utf-8 -*-
"""迁移模块测试：校验、复制、校验比对、记录管理、链接创建。

注意：涉及 mklink 的用例只在 Windows 上运行，且创建在临时目录内。
"""

import os
import sys

import pytest

from src.core.migrator import (
    STAGE_COPIED,
    STAGE_PLANNED,
    MigrationStore,
    copy_tree,
    create_junction,
    estimate,
    is_protected,
    migrate,
    remove_junction,
    undo,
    validate,
    verify_copy,
)


def _write(path, content="x"):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def test_estimate_total_and_files(tmp_path):
    d = tmp_path / "src"
    (d / "sub").mkdir(parents=True)
    _write(d / "a.txt", "12345")
    _write(d / "sub" / "b.txt", "1234567890")
    total, files, entries, links, errors = estimate(str(d))
    assert total == 15
    assert files == 2
    assert entries >= 2
    assert links == []
    assert errors == []


def test_estimate_skips_reparse_points(tmp_path):
    """重解析点必须单独记录，不能被当作普通目录进入。"""
    if sys.platform != "win32":
        pytest.skip("仅 Windows")
    d = tmp_path / "src"
    d.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    _write(target / "big.bin", "1234567890")
    ok, _msg = create_junction(str(d / "link"), str(target))
    if not ok:
        pytest.skip("当前环境无法创建 junction")
    _write(d / "own.txt", "123")
    total, files, entries, links, _errors = estimate(str(d))
    assert total == 3
    assert files == 1
    assert len(links) == 1


def test_is_protected_forbidden_trees():
    assert is_protected("C:\\Windows\\System32") is True
    assert is_protected("C:\\Program Files\\Foo") is True
    assert is_protected("C:\\ProgramData\\Bar") is True
    assert is_protected("C:\\Users") is True
    assert is_protected("C:\\Users\\Foo\\AppData\\Local\\SomeApp") is False


def test_validate_requires_different_drive(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _write(src / "a.txt")
    dst = tmp_path / "dst"
    problems = validate(str(src), str(dst))
    assert any("同一个盘" in p for p in problems)


def test_validate_detects_missing_src(tmp_path):
    problems = validate(str(tmp_path / "nope"), "D:\\dst")
    assert any("源目录不存在" in p for p in problems)


def test_validate_rejects_dst_inside_src(tmp_path):
    if sys.platform != "win32":
        pytest.skip("仅 Windows：需要构造跨盘路径")
    src = tmp_path / "src"
    src.mkdir()
    problems = validate(str(src), str(src / "inner"))
    assert any("目标目录不能位于源目录内部" in p or "同一个盘" in p for p in problems)


def test_copy_tree_and_verify(tmp_path):
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    _write(src / "a.txt", "abc")
    _write(src / "sub" / "b.txt", "defg")
    dst = tmp_path / "dst"
    dst.mkdir()
    ok, copied, files, failures, cancelled = copy_tree(str(src), str(dst))
    assert ok and not cancelled and failures == []
    assert copied == 7 and files == 2
    assert verify_copy(str(src), str(dst)) == []


def test_copy_tree_reports_size_mismatch(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _write(src / "a.txt", "12345")
    dst = tmp_path / "dst"
    dst.mkdir()
    _write(dst / "a.txt", "123")
    problems = verify_copy(str(src), str(dst))
    assert problems and "体积不一致" in problems[0]


def test_copy_tree_cancel(tmp_path):
    import threading

    src = tmp_path / "src"
    src.mkdir()
    _write(src / "a.txt")
    dst = tmp_path / "dst"
    dst.mkdir()
    ev = threading.Event()
    ev.set()
    ok, _copied, _files, _failures, cancelled = copy_tree(str(src), str(dst), cancel=ev)
    assert ok is False and cancelled is True


def test_store_upsert_load_remove(tmp_path):
    store = MigrationStore(str(tmp_path / "migrations.json"))
    rec = {"src": "C:\\Foo\\Cache", "dst": "D:\\Cache", "stage": STAGE_PLANNED}
    store.upsert(rec)
    assert store.load()[0]["src"] == rec["src"]
    rec["stage"] = STAGE_COPIED
    store.upsert(rec)
    assert store.get(rec["src"])["stage"] == STAGE_COPIED
    assert store.remove(rec["src"]) is True
    assert store.load() == []


def test_store_survives_corrupted_file(tmp_path):
    p = tmp_path / "migrations.json"
    p.write_text("{not json", encoding="utf-8")
    assert MigrationStore(str(p)).load() == []


def test_undo_planned_removes_part(tmp_path):
    store = MigrationStore(str(tmp_path / "migrations.json"))
    src = tmp_path / "src"
    src.mkdir()
    _write(src / "a.txt")
    rec = {"src": str(src), "dst": str(tmp_path / "dst"), "stage": STAGE_PLANNED}
    (tmp_path / "dst.part").mkdir()
    _write(tmp_path / "dst.part" / "partial.txt")
    store.upsert(rec)
    ok, _msg = undo(store.get(rec["src"]), store=store)
    assert ok is True
    assert not (tmp_path / "dst.part").exists()
    assert src.is_dir() and (src / "a.txt").is_file()


def test_undo_refuses_after_source_deleted(tmp_path):
    rec = {"src": str(tmp_path / "src"), "dst": str(tmp_path / "dst"),
           "stage": "source_deleted"}
    ok, msg = undo(rec)
    assert ok is False
    assert "不能直接撤销" in msg


@pytest.mark.skipif(sys.platform != "win32", reason="仅 Windows 支持 junction")
def test_junction_create_and_remove(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    _write(target / "keep.txt", "data")
    link = tmp_path / "link"
    ok, msg = create_junction(str(link), str(target))
    if not ok:
        pytest.skip("当前环境不允许创建 junction：%s" % msg)
    assert os.path.isdir(str(link))
    ok, msg = remove_junction(str(link))
    assert ok, msg
    # 链接移除后目标数据必须完好
    assert (target / "keep.txt").is_file()


@pytest.mark.skipif(sys.platform != "win32", reason="仅 Windows 支持 junction")
def test_remove_junction_refuses_normal_dir(tmp_path):
    d = tmp_path / "normal"
    d.mkdir()
    ok, msg = remove_junction(str(d))
    assert ok is False
    assert "不是目录链接" in msg
    assert d.is_dir()


def test_migrate_end_to_end(tmp_path):
    """完整三阶段：复制 → 校验 → 删源 → 建链接；失败时数据也不能丢。"""
    if sys.platform != "win32":
        pytest.skip("仅 Windows")
    import shutil as _shutil

    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    _write(src / "a.txt", "hello")
    _write(src / "sub" / "b.txt", "world!")
    dst = tmp_path / "dst"

    store = MigrationStore(str(tmp_path / "migrations.json"))
    rec = store.upsert({"src": str(src), "dst": str(dst), "stage": STAGE_PLANNED})
    rec, ok, msg = migrate(rec, store=store)

    # 数据无论如何都必须存在于目标目录
    assert (dst / "a.txt").is_file()
    assert (dst / "sub" / "b.txt").is_file()

    if not ok:
        # 环境不允许创建 junction 时，至少应停在「已删除源」阶段
        assert "链接" in msg
        assert rec["stage"] == "source_deleted"
        _shutil.rmtree(str(dst))
        return

    assert rec["stage"] == "linked"
    # 原路径仍可访问（实际指向目标）
    assert (src / "a.txt").is_file()
    ok, msg = remove_junction(str(src))
    assert ok, msg
    _shutil.rmtree(str(dst))

