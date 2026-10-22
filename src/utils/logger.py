# -*- coding: utf-8 -*-
"""日志系统。

日志写入 ``data/logs/diskcleaner.log``，按大小滚动（默认 1MB × 3 份）；
同时可通过 ``set_ui_sink`` 把日志转发到界面上的日志面板。

打包为 GUI 程序（--windowed）时标准输出为 None，因此控制台回显会自动跳过。
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

_LOGGER_NAME = "diskcleaner"


class Logger:
    """轻量日志封装：文件滚动日志 + 可选的界面回显。"""

    def __init__(self, log_dir, level="INFO", max_bytes=1048576,
                 backup_count=3, echo_console=True):
        os.makedirs(log_dir, exist_ok=True)
        self.path = os.path.join(log_dir, "diskcleaner.log")
        self._ui_sink = None

        self._logger = logging.getLogger(_LOGGER_NAME)
        self._logger.propagate = False
        self._logger.handlers.clear()
        self._logger.setLevel(self._parse_level(level))

        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

        try:
            fh = RotatingFileHandler(self.path, maxBytes=int(max_bytes),
                                     backupCount=int(backup_count), encoding="utf-8")
            fh.setFormatter(formatter)
            self._logger.addHandler(fh)
        except OSError:
            pass  # 日志目录不可写时降级为仅界面输出

        # --windowed 打包下 stdout/stderr 均为 None，需跳过控制台输出
        if echo_console and sys.stdout is not None:
            sh = logging.StreamHandler(sys.stdout)
            sh.setFormatter(formatter)
            self._logger.addHandler(sh)

    # ---------------- 内部 ----------------

    @staticmethod
    def _parse_level(level):
        if isinstance(level, int):
            return level
        return getattr(logging, str(level).upper(), logging.INFO)

    def _emit(self, level, msg):
        self._logger.log(level, msg)
        if self._ui_sink is not None:
            try:
                self._ui_sink(msg)
            except Exception:  # noqa: BLE001
                pass  # 界面回调异常不能影响日志写入

    # ---------------- 对外接口 ----------------

    def set_ui_sink(self, callback):
        """注册界面日志回调（callable(str)）。"""
        self._ui_sink = callback

    def get_logger(self):
        return self._logger

    def debug(self, msg):
        self._emit(logging.DEBUG, msg)

    def info(self, msg):
        self._emit(logging.INFO, msg)

    def warning(self, msg):
        self._emit(logging.WARNING, msg)

    def error(self, msg):
        self._emit(logging.ERROR, msg)

    def exception(self, msg):
        self._logger.exception(msg)
        if self._ui_sink is not None:
            try:
                self._ui_sink(msg)
            except Exception:  # noqa: BLE001
                pass
