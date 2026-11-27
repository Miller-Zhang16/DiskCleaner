# -*- coding: utf-8 -*-
"""多盘回收站：盘符枚举与体积汇总。"""

from src.core.recycle import fixed_drives, recycle_bin_size_all


def test_fixed_drives_returns_root_paths():
    drives = fixed_drives()
    assert drives
    for root in drives:
        assert len(root) == 3 and root.endswith(":\\")


def test_recycle_bin_size_all_is_int_or_none():
    size = recycle_bin_size_all()
    assert size is None or (isinstance(size, int) and size >= 0)
