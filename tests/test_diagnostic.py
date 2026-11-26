# -*- coding: utf-8 -*-
"""诊断包导出。"""

import zipfile

from src.core.diagnostic import build_diagnostics


def test_build_diagnostics_collects_config_logs_history(tmp_path):
    data = tmp_path / "data"
    (data / "logs").mkdir(parents=True)
    (data / "settings.ini").write_text("[general]\nlanguage = zh_CN\n", encoding="utf-8")
    (data / "custom_targets.txt").write_text("D:\\Temp\n", encoding="utf-8")
    (data / "logs" / "diskcleaner.log").write_text("started\n", encoding="utf-8")
    (data / "history.jsonl").write_text('{"title": "test"}\n' * 5, encoding="utf-8")

    dest = tmp_path / "diag.zip"
    count = build_diagnostics(str(dest), data_root=str(data))

    assert dest.exists()
    assert count >= 5
    with zipfile.ZipFile(dest) as zf:
        names = zf.namelist()
        info = zf.read("version.txt").decode("utf-8")
    assert "config/settings.ini" in names
    assert "config/custom_targets.txt" in names
    assert any(n.startswith("logs/") for n in names)
    assert "history/recent.jsonl" in names
    assert "DiskCleaner v" in info


def test_build_diagnostics_without_data(tmp_path):
    dest = tmp_path / "empty.zip"
    count = build_diagnostics(str(dest), data_root=str(tmp_path / "missing"))
    assert dest.exists()
    assert count == 1
