# -*- coding: utf-8 -*-
"""设置页：在界面内编辑 settings.ini，无需手动编辑文本文件。

可配置项：
    - 界面：语言（重启后生效）
    - 扫描：时间预算 / 条目预算 / 自动计算大小的子目录上限
    - 清理：临时文件最小保留时长 / 清理前二次确认
    - 大文件：返回结果数上限 / 最小体积阈值（MB）
    - 历史：清理历史保留条数上限
    - 日志：级别 / 单文件大小 / 滚动份数

保存后立即写入 settings.ini；语言与日志级别变更在下次启动时生效。
"""

import os
import tkinter as tk
from tkinter import messagebox, ttk

from ..utils.config import GENERAL
from ..utils.i18n import tr
from . import theme


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
        # 底部按钮栏固定，表单主体可滚动，避免小窗口下按钮被挤出可视区
        bar = tk.Frame(self, background=theme.BG)
        bar.pack(side="bottom", fill="x", pady=(8, 8))
        ttk.Button(bar, text=tr("settings.btn.save"), style="Accent.TButton",
                   command=self.save).pack(side="left")
        ttk.Button(bar, text=tr("settings.btn.reload"), style="Ghost.TButton",
                   command=self.load).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text=tr("settings.btn.open_dir"), style="Ghost.TButton",
                   command=self._open_config_dir).pack(side="right")

        self.path_label = ttk.Label(
            bar, style="Muted.TLabel",
            text=tr("settings.path_label", path=self.app.config.path))
        self.path_label.pack(side="right", padx=(0, 16))

        body = tk.Frame(self, background=theme.BG)
        body.pack(fill="both", expand=True)
        canvas = tk.Canvas(body, background=theme.BG, highlightthickness=0)
        vsb = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self._scroll_canvas = canvas

        outer = tk.Frame(canvas, background=theme.BG)
        win = canvas.create_window((0, 0), window=outer, anchor="nw")
        outer.bind("<Configure>", lambda _e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(
            win, width=e.width))

        # 左列：界面 + 扫描 + 清理
        left = tk.Frame(outer, background=theme.BG)
        left.pack(side="left", fill="y", padx=(0, 12), pady=(0, 6))

        self._group(left, "settings.group.ui", [
            ("language", "settings.field.language", "lang"),
        ])

        self._group(left, "settings.group.scan", [
            ("scan_budget_seconds", "settings.field.scan_budget_seconds", "float"),
            ("scan_budget_entries", "settings.field.scan_budget_entries", "int"),
            ("auto_size_limit", "settings.field.auto_size_limit", "int"),
        ])

        self._group(left, "settings.group.clean", [
            ("temp_min_age_hours", "settings.field.temp_min_age_hours", "float"),
        ])
        # 清理前二次确认（布尔，单独处理）
        self.confirm_var = tk.BooleanVar()
        self.confirm_card = theme.card(left)
        self.confirm_card.pack(fill="x", pady=(0, 10))
        ttk.Checkbutton(self.confirm_card, text=tr("settings.confirm_before_clean"),
                        variable=self.confirm_var,
                        style="Card.TCheckbutton").pack(
            anchor="w", padx=14, pady=10)

        # 右列：大文件 + 历史 + 日志
        right = tk.Frame(outer, background=theme.BG)
        right.pack(side="left", fill="y", padx=(12, 0), pady=(0, 6))

        self._group(right, "settings.group.large", [
            ("large_files_top_n", "settings.field.large_files_top_n", "int"),
            ("large_files_min_mb", "settings.field.large_files_min_mb", "int"),
        ])

        self._group(right, "settings.group.dup", [
            ("duplicates_min_mb", "settings.field.duplicates_min_mb", "int"),
            ("duplicates_budget_seconds", "settings.field.duplicates_budget_seconds", "float"),
        ])

        self._group(right, "settings.group.history", [
            ("history_max_records", "settings.field.history_max_records", "int"),
        ])
        ttk.Button(right, text=tr("settings.btn.view_history"),
                   style="Ghost.TButton",
                   command=self._open_history).pack(anchor="w", pady=(0, 10))

        self._group(right, "settings.group.log", [
            ("log_level", "settings.field.log_level", "level"),
            ("log_max_bytes", "settings.field.log_max_bytes", "int"),
            ("log_backup_count", "settings.field.log_backup_count", "int"),
        ])

        self._bind_wheel(canvas)
        self._bind_wheel(outer)

    def _bind_wheel(self, widget):
        """让鼠标滚轮在表单区域内滚动；不依赖全局绑定，避免影响其它页。"""
        widget.bind("<MouseWheel>", self._on_wheel)
        for child in widget.winfo_children():
            self._bind_wheel(child)

    def _on_wheel(self, event):
        self._scroll_canvas.yview_scroll(int(-event.delta / 120), "units")

    def _group(self, parent, title_key, fields):
        frame = ttk.LabelFrame(parent, text=tr(title_key),
                               style="Card.TLabelframe", padding=(14, 8))
        frame.pack(fill="x", pady=(0, 10))
        for key, label_key, kind in fields:
            row = tk.Frame(frame, background=theme.CARD)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=tr(label_key), width=34, anchor="w",
                      style="Card.TLabel").pack(side="left")
            var = tk.StringVar()
            self.vars[key] = var
            if kind == "level":
                ttk.Combobox(row, textvariable=var, width=12,
                             values=["DEBUG", "INFO", "WARNING", "ERROR"],
                             state="readonly").pack(side="left")
            elif kind == "lang":
                ttk.Combobox(row, textvariable=var, width=12,
                             values=["zh_CN", "en_US"],
                             state="readonly").pack(side="left")
            else:
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
                      "duplicates_min_mb",
                      "history_max_records",
                      "log_max_bytes", "log_backup_count"]
        float_fields = ["scan_budget_seconds", "duplicates_budget_seconds",
                        "temp_min_age_hours"]

        for key in int_fields:
            raw = self.vars[key].get().strip()
            try:
                int(raw)
            except ValueError:
                messagebox.showwarning(tr("settings.msg.invalid_title"),
                                       tr("settings.msg.int", key=key))
                return

        for key in float_fields:
            raw = self.vars[key].get().strip()
            try:
                float(raw)
            except ValueError:
                messagebox.showwarning(tr("settings.msg.invalid_title"),
                                       tr("settings.msg.number", key=key))
                return

        old_language = cfg.language
        for key, var in self.vars.items():
            cfg.set(GENERAL, key, var.get().strip())
        cfg.set(GENERAL, "confirm_before_clean",
                "true" if self.confirm_var.get() else "false")

        ok = cfg.save()
        if not ok:
            messagebox.showerror(tr("settings.msg.save_failed_title"),
                                 tr("settings.msg.save_failed", path=cfg.path))
            return

        # 保留条数上限可能被改，同步到已存在的历史对象
        self.app.history.max_records = cfg.history_max_records
        self.app.set_status(tr("settings.status.saved"))
        self.app.logger.info("用户保存设置：%s" % cfg.path)
        if cfg.language != old_language:
            messagebox.showinfo(tr("settings.msg.lang_restart_title"),
                                tr("settings.msg.lang_restart"))

    # ---------------- 辅助 ----------------

    def _open_history(self):
        self.app.show_history()

    def _open_config_dir(self):
        d = os.path.dirname(self.app.config.path)
        try:
            os.startfile(d)  # noqa: S606
        except OSError as e:
            messagebox.showwarning(tr("settings.msg.open_failed"), str(e))
