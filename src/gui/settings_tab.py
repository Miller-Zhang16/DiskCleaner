# -*- coding: utf-8 -*-
"""设置页：在界面内编辑 settings.ini，无需手动编辑文本文件。

可配置项：
    - 扫描：时间预算 / 条目预算 / 自动计算大小的子目录上限
    - 清理：临时文件最小保留时长 / 清理前二次确认
    - 大文件：返回结果数上限 / 最小体积阈值（MB）
    - 日志：级别 / 单文件大小 / 滚动份数

保存后立即写入 settings.ini；日志级别变更在下次启动时生效。
"""

import os
import tkinter as tk
from tkinter import messagebox, ttk

from ..utils.config import GENERAL


class SettingsTab(ttk.Frame):
    """设置页。"""

    def __init__(self, master, runner, app):
        super().__init__(master)
        self.runner = runner
        self.app = app
        self.vars = {}
        self._build()
        self.load()

    # ---------------- 构建界面 ----------------

    def _build(self):
        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True, padx=12, pady=12)

        # 左列：扫描 + 清理
        left = ttk.Frame(outer)
        left.pack(side="left", fill="y", padx=(0, 12))

        self._group(left, "扫描", [
            ("scan_budget_seconds", "单次扫描时间预算（秒）", "float"),
            ("scan_budget_entries", "单次扫描条目预算", "int"),
            ("auto_size_limit", "展开时自动计算大小的子目录数", "int"),
        ])

        self._group(left, "清理", [
            ("temp_min_age_hours", "临时文件最小保留时长（小时）", "float"),
        ])
        # 清理前二次确认（布尔，单独处理）
        self.confirm_var = tk.BooleanVar()
        ttk.Checkbutton(left, text="清理操作前二次确认",
                        variable=self.confirm_var).pack(anchor="w", pady=(4, 0))

        # 右列：大文件 + 日志
        right = ttk.Frame(outer)
        right.pack(side="left", fill="y", padx=(12, 0))

        self._group(right, "大文件", [
            ("large_files_top_n", "返回结果数上限", "int"),
            ("large_files_min_mb", "最小体积阈值（MB，0=不过滤）", "int"),
        ])

        self._group(right, "日志", [
            ("log_level", "日志级别", "level"),
            ("log_max_bytes", "单份日志最大字节数", "int"),
            ("log_backup_count", "保留的历史日志份数", "int"),
        ])

        # 底部按钮栏
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=12, pady=(0, 8))
        ttk.Button(bar, text="保存设置", command=self.save).pack(side="left")
        ttk.Button(bar, text="重新加载", command=self.load).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="打开配置文件所在目录",
                   command=self._open_config_dir).pack(side="right")

        path_bar = ttk.Frame(self)
        path_bar.pack(fill="x", padx=12, pady=(0, 8))
        self.path_label = ttk.Label(path_bar, foreground="#666",
                                    text="配置文件：%s" % self.app.config.path)
        self.path_label.pack(side="left")

    def _group(self, parent, title, fields):
        frame = ttk.LabelFrame(parent, text=title, padding=(10, 6))
        frame.pack(fill="x", pady=(0, 10))
        for key, label, kind in fields:
            row = ttk.Frame(frame)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=label, width=34, anchor="w").pack(side="left")
            if kind == "level":
                var = tk.StringVar()
                self.vars[key] = var
                cb = ttk.Combobox(row, textvariable=var, width=12,
                                  values=["DEBUG", "INFO", "WARNING", "ERROR"],
                                  state="readonly")
                cb.pack(side="left")
            else:
                var = tk.StringVar()
                self.vars[key] = var
                ttk.Entry(row, textvariable=var, width=14).pack(side="left")

    # ---------------- 数据加载 / 保存 ----------------

    def load(self):
        """从配置对象读取并填充界面。"""
        cfg = self.app.config
        for key in self.vars:
            val = cfg.get(GENERAL, key, "")
            self.vars[key].set(val)
        self.confirm_var.set(cfg.confirm_before_clean)

    def save(self):
        """校验并写入配置。"""
        cfg = self.app.config

        int_fields = ["scan_budget_entries", "auto_size_limit",
                      "large_files_top_n", "large_files_min_mb",
                      "log_max_bytes", "log_backup_count"]
        float_fields = ["scan_budget_seconds", "temp_min_age_hours"]

        for key in int_fields:
            raw = self.vars[key].get().strip()
            try:
                int(raw)
            except ValueError:
                messagebox.showwarning("输入无效",
                                       "%s 必须是整数。" % key)
                return

        for key in float_fields:
            raw = self.vars[key].get().strip()
            try:
                float(raw)
            except ValueError:
                messagebox.showwarning("输入无效",
                                       "%s 必须是数字。" % key)
                return

        for key, var in self.vars.items():
            cfg.set(GENERAL, key, var.get().strip())
        cfg.set(GENERAL, "confirm_before_clean",
                "true" if self.confirm_var.get() else "false")

        ok = cfg.save()
        if ok:
            self.app.set_status("设置已保存。")
            self.app.logger.info("用户保存设置：%s" % cfg.path)
        else:
            messagebox.showerror("保存失败", "无法写入配置文件：\n%s" % cfg.path)

    # ---------------- 辅助 ----------------

    def _open_config_dir(self):
        d = os.path.dirname(self.app.config.path)
        try:
            os.startfile(d)  # noqa: S606
        except OSError as e:
            messagebox.showwarning("无法打开", str(e))
