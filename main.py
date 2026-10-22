# -*- coding: utf-8 -*-
"""DiskCleaner 程序入口。

运行方式：
    源码运行：  python main.py
    打包运行：  DiskCleaner.exe
"""

import os
import sys
import tkinter as tk

# 支持以脚本方式从任意工作目录运行
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.core.runtime import (config_path, custom_targets_path, data_dir,  # noqa: E402
                              enable_dpi_awareness, icon_path, log_dir,
                              set_app_user_model_id)
from src.core.targets import build_targets  # noqa: E402
from src.gui.app import CleanupApp  # noqa: E402
from src.utils.config import Config  # noqa: E402
from src.utils.logger import Logger  # noqa: E402


def main():
    enable_dpi_awareness()
    # 必须在创建窗口前设置，否则任务栏会显示解释器自带图标
    set_app_user_model_id()
    os.makedirs(data_dir(), exist_ok=True)

    # 配置：首次运行自动生成 data/settings.ini 与 data/custom_targets.txt
    config = Config(config_path(), custom_path=custom_targets_path())
    config.ensure_custom_targets_file()

    # 清理目标：合并内置目标与自定义目录，并同步勾选状态到配置
    targets = build_targets(config)
    config.save()

    logger = Logger(log_dir(), level=config.log_level,
                    max_bytes=config.log_max_bytes,
                    backup_count=config.log_backup_count)

    root = tk.Tk()
    # 应用图标（Windows 窗口标题栏 + 任务栏）
    ico = icon_path()
    if ico:
        try:
            root.iconbitmap(ico)
        except Exception:
            pass
    app = CleanupApp(root, config, logger, targets)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
