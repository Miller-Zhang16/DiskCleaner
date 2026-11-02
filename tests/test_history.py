# -*- coding: utf-8 -*-
"""测试清理历史记录（追加 / 读取 / 淘汰 / 容错）。"""

import json

from src.core.history import History


def test_append_and_load(tmp_path):
    h = History(str(tmp_path / "history.jsonl"))
    assert h.append({"title": "一键清理", "freed": 1024, "deleted": 3}) is True

    records = h.load()
    assert len(records) == 1
    assert records[0]["title"] == "一键清理"
    assert records[0]["freed"] == 1024
    # 自动补充时间字段
    assert "time" in records[0]
    assert "ts" in records[0]


def test_load_newest_first(tmp_path):
    h = History(str(tmp_path / "history.jsonl"))
    for i in range(3):
        h.append({"title": "第%d次" % i, "freed": i})
    records = h.load()
    assert [r["title"] for r in records] == ["第2次", "第1次", "第0次"]


def test_load_limit(tmp_path):
    h = History(str(tmp_path / "history.jsonl"))
    for i in range(5):
        h.append({"title": "t%d" % i})
    assert len(h.load(limit=2)) == 2


def test_trim_keeps_newest(tmp_path):
    """超出上限时淘汰最旧记录。"""
    h = History(str(tmp_path / "history.jsonl"), max_records=3)
    for i in range(6):
        h.append({"title": "t%d" % i})

    records = h.load()
    assert len(records) == 3
    assert [r["title"] for r in records] == ["t5", "t4", "t3"]
    # 文件内也确实只剩 3 行
    lines = (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    assert len([ln for ln in lines if ln.strip()]) == 3


def test_corrupted_line_is_skipped(tmp_path):
    """单行损坏不影响其他记录解析。"""
    path = tmp_path / "history.jsonl"
    h = History(str(path))
    h.append({"title": "good1"})
    with open(path, "a", encoding="utf-8") as f:
        f.write("{ this is not json\n")
    h.append({"title": "good2"})

    records = h.load()
    titles = [r["title"] for r in records]
    assert "good1" in titles and "good2" in titles
    assert len(records) == 2


def test_clear(tmp_path):
    h = History(str(tmp_path / "history.jsonl"))
    h.append({"title": "x"})
    assert h.clear() is True
    assert h.load() == []


def test_missing_file_returns_empty(tmp_path):
    h = History(str(tmp_path / "nope" / "history.jsonl"))
    assert h.load() == []


def test_append_creates_parent_dir(tmp_path):
    h = History(str(tmp_path / "sub" / "history.jsonl"))
    assert h.append({"title": "x"}) is True
    assert (tmp_path / "sub" / "history.jsonl").is_file()


def test_failures_are_serialized(tmp_path):
    """失败明细（含中文错误文本）能正确落盘并读回。"""
    h = History(str(tmp_path / "history.jsonl"))
    h.append({"title": "清理", "failures": [
        {"path": r"C:\Windows\Temp\a.tmp", "error": "文件被占用"},
        {"path": r"C:\Windows\Temp\b.tmp", "error": "无权限访问"},
    ]})
    rec = h.load()[0]
    assert len(rec["failures"]) == 2
    assert rec["failures"][0]["error"] == "文件被占用"
    # 中文不该被转义成 \uXXXX
    raw = (tmp_path / "history.jsonl").read_text(encoding="utf-8")
    assert "文件被占用" in raw
    assert json.loads(raw.splitlines()[0])["failures"][1]["path"].endswith("b.tmp")
