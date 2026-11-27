# -*- coding: utf-8 -*-
"""迁移可靠性：抽样校验、完整回滚、进程占用匹配。"""

import os

from src.core.migrator import (
    STAGE_SOURCE_DELETED,
    rollback,
    spot_check,
    validate,
)
from src.core.processes import executables_under


class _Store:
    def __init__(self):
        self.removed = []

    def remove(self, src):
        self.removed.append(src)
        return True


def _write(path, content="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def test_spot_check_detects_mtime_mismatch(tmp_path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _write(str(src / "a.txt"), "12345")
    _write(str(dst / "a.txt"), "12345")
    assert spot_check(str(src), str(dst)) == []

    os.utime(str(dst / "a.txt"), (0, 0))
    problems = spot_check(str(src), str(dst))
    assert problems and "修改时间" in problems[0]


def test_rollback_restores_source_and_removes_target(tmp_path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _write(str(dst / "a.txt"), "12345")
    _write(str(dst / "sub" / "b.txt"), "67890")
    store = _Store()
    rec = {"src": str(src), "dst": str(dst),
           "stage": STAGE_SOURCE_DELETED, "size": 10}

    ok, msg = rollback(rec, store=store)

    assert ok, msg
    assert (src / "a.txt").read_text(encoding="utf-8") == "12345"
    assert (src / "sub" / "b.txt").exists()
    assert not dst.exists()
    assert store.removed == [str(src)]


def test_rollback_refuses_missing_target(tmp_path):
    rec = {"src": str(tmp_path / "src"), "dst": str(tmp_path / "missing"),
           "stage": STAGE_SOURCE_DELETED, "size": 10}
    ok, msg = rollback(rec, store=_Store())
    assert not ok
    assert "目标目录不存在" in msg


def test_validate_reports_long_target_path(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    long_dst = str(tmp_path / ("x" * 200) / ("y" * 40))
    problems = validate(str(src), long_dst)
    assert any("路径过长" in p for p in problems)


def test_executables_under_matches_directory_prefix():
    exes = [r"c:\apps\foo\foo.exe", r"c:\apps\foobar\bar.exe".lower(),
            r"d:\other\baz.exe"]
    hits = executables_under(r"C:\Apps\Foo", exes)
    assert hits == [r"c:\apps\foo\foo.exe"]
    assert executables_under("", exes) == []
