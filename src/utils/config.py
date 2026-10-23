# -*- coding: utf-8 -*-
"""配置管理。

配置文件：``data/settings.ini``（可用记事本编辑）
自定义清理目录：``data/custom_targets.txt``（每行一个绝对路径，``#`` 开头为注释）

配置项说明见 README.md 的「配置文件」章节。
"""

import configparser
import os

GENERAL = "General"
TARGETS = "Targets"

# [General] 默认值
DEFAULTS = {
    "scan_budget_seconds": "6",       # 单次目录扫描时间预算（秒）
    "scan_budget_entries": "200000",  # 单次目录扫描条目预算
    "temp_min_age_hours": "24",       # 临时文件仅清理该小时数之前的
    "auto_size_limit": "150",         # 展开目录时自动计算大小的子目录数上限
    "large_files_top_n": "200",       # 大文件扫描返回的结果数上限
    "large_files_min_mb": "100",      # 大文件扫描仅统计不小于该 MB 数的文件（0 表示不过滤）
    "log_level": "INFO",
    "log_max_bytes": "1048576",
    "log_backup_count": "3",
    "window_geometry": "1120x740",
    "confirm_before_clean": "true",   # 清理前是否二次确认
}


def _to_bool(value, fallback=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return fallback
    v = str(value).strip().lower()
    if v in ("1", "true", "yes", "on", "y"):
        return True
    if v in ("0", "false", "no", "off", "n"):
        return False
    return fallback


class Config:
    """settings.ini 读写封装。"""

    def __init__(self, path, custom_path=None):
        self.path = path
        self.custom_path = custom_path or os.path.join(
            os.path.dirname(path), "custom_targets.txt")
        self._cp = configparser.ConfigParser()
        self._load()

    # ---------------- 载入 / 保存 ----------------

    def _load(self):
        if os.path.isfile(self.path):
            try:
                self._cp.read(self.path, encoding="utf-8")
            except (OSError, configparser.Error):
                pass
        if not self._cp.has_section(GENERAL):
            self._cp.add_section(GENERAL)
        if not self._cp.has_section(TARGETS):
            self._cp.add_section(TARGETS)
        for key, val in DEFAULTS.items():
            if not self._cp.has_option(GENERAL, key):
                self._cp.set(GENERAL, key, val)

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                self._cp.write(f)
            return True
        except OSError:
            return False

    def reload(self):
        """重新从磁盘读取配置（用于界面上的「重新加载配置」）。"""
        self._cp = configparser.ConfigParser()
        self._load()

    # ---------------- 通用读写 ----------------

    def get(self, section, option, fallback=None):
        try:
            return self._cp.get(section, option)
        except (configparser.Error, KeyError):
            return fallback

    def get_int(self, section, option, fallback=0):
        try:
            return self._cp.getint(section, option)
        except (configparser.Error, ValueError):
            return fallback

    def get_float(self, section, option, fallback=0.0):
        try:
            return self._cp.getfloat(section, option)
        except (configparser.Error, ValueError):
            return fallback

    def get_bool(self, section, option, fallback=False):
        raw = self.get(section, option, None)
        return _to_bool(raw, fallback)

    def set(self, section, option, value):
        if not self._cp.has_section(section):
            self._cp.add_section(section)
        self._cp.set(section, option, str(value))

    # ---------------- 便捷访问器 ----------------

    @property
    def scan_budget_seconds(self):
        return self.get_float(GENERAL, "scan_budget_seconds", 6.0)

    @property
    def scan_budget_entries(self):
        return self.get_int(GENERAL, "scan_budget_entries", 200000)

    @property
    def temp_min_age_seconds(self):
        return self.get_float(GENERAL, "temp_min_age_hours", 24) * 3600.0

    @property
    def auto_size_limit(self):
        return self.get_int(GENERAL, "auto_size_limit", 150)

    @property
    def large_files_top_n(self):
        return self.get_int(GENERAL, "large_files_top_n", 200)

    @property
    def large_files_min_bytes(self):
        """大文件扫描的最小体积阈值（字节），0 表示不过滤。"""
        mb = self.get_int(GENERAL, "large_files_min_mb", 100)
        return max(0, mb) * 1024 * 1024

    @property
    def log_level(self):
        return self.get(GENERAL, "log_level", "INFO")

    @property
    def log_max_bytes(self):
        return self.get_int(GENERAL, "log_max_bytes", 1048576)

    @property
    def log_backup_count(self):
        return self.get_int(GENERAL, "log_backup_count", 3)

    @property
    def window_geometry(self):
        return self.get(GENERAL, "window_geometry", "1120x740")

    @property
    def confirm_before_clean(self):
        return self.get_bool(GENERAL, "confirm_before_clean", True)

    def set_window_geometry(self, geometry):
        self.set(GENERAL, "window_geometry", geometry)

    # ---------------- 清理项勾选状态 ----------------

    def ensure_target(self, key, default_checked):
        """登记清理项；已存在则保留用户选择。"""
        if not self._cp.has_option(TARGETS, key):
            self._cp.set(TARGETS, key, "true" if default_checked else "false")

    def target_default(self, key, fallback=True):
        """读取某清理项的默认勾选状态。"""
        return self.get_bool(TARGETS, key, fallback)

    def set_target_default(self, key, value):
        self.set(TARGETS, key, "true" if value else "false")

    # ---------------- 自定义清理目录 ----------------

    def custom_targets(self):
        """读取自定义清理目录列表（忽略空行与 # 注释行）。"""
        if not os.path.isfile(self.custom_path):
            return []
        try:
            with open(self.custom_path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
        except OSError:
            return []
        out = []
        for line in lines:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            out.append(s)
        return out

    def ensure_custom_targets_file(self):
        """首次运行时生成带注释的自定义目录模板文件。"""
        if os.path.isfile(self.custom_path):
            return
        try:
            os.makedirs(os.path.dirname(self.custom_path), exist_ok=True)
            with open(self.custom_path, "w", encoding="utf-8") as f:
                f.write("# 自定义清理目录：每行一个绝对路径，程序只删除目录内的内容（保留目录本身）\n")
                f.write("# 例如：\n")
                f.write("# C:\\Temp\\MyAppCache\n")
        except OSError:
            pass
