# -*- coding: utf-8 -*-
"""大文件扫描页：找出指定目录下体积最大的 N 个文件。

交互约定：
    - 输入扫描路径（默认 C:\\），点击「扫描大文件」后在后台遍历；
    - 表格按体积降序列出最大的 N 个文件（N 与最小体积阈值由 settings.ini 配置）；
    - 右键菜单：打开所在位置 / 复制完整路径 / 删除此文件；
    - 扫描受时间与条目预算限制，提前结束时状态栏会提示「可能不完整」。
"""

import datetime
import os
import tkinter as tk
from tkinter import messagebox, ttk

from ..core.classify import CATEGORY_COLORS, classify
from ..core.scanner import scan_large_files
from ..utils.fmt import dir_of, fmt_size
from ..utils.taskrunner import LANE_SCAN, PRIORITY_SCAN


class LargeFilesTab(ttk.Frame):
    """大文件扫描页。"""

    def __init__(self, master, runner, app):
        super().__init__(master)
        self.runner = runner
        self.app = app
        self.scanning = False
        self._build()

    # ---------------- 构建界面 ----------------

    def _build(self):
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=6, pady=(6, 2))
        ttk.Label(bar, text="扫描路径：").pack(side="left")
        self.path_var = tk.StringVar(value="C:\\")
        ttk.Entry(bar, textvariable=self.path_var, width=60).pack(side="left", padx=(0, 6))
        self.scan_btn = ttk.Button(bar, text="扫描大文件", command=self.on_scan)
        self.scan_btn.pack(side="left")
        self.stop_btn = ttk.Button(bar, text="停止", command=self.on_stop, state="disabled")
        self.stop_btn.pack(side="left", padx=(4, 0))
        ttk.Label(bar, foreground="#888",
                  text="默认仅显示 ≥ 100 MB 的文件（可在 settings.ini 调整）").pack(side="left", padx=12)

        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True, padx=6, pady=6)

        cols = ("size", "dir", "mtime")
        self.tree = ttk.Treeview(wrap, columns=cols, show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="文件路径")
        self.tree.heading("size", text="大小")
        self.tree.heading("dir", text="所在目录")
        self.tree.heading("mtime", text="修改时间")
        self.tree.column("#0", width=460, anchor="w")
        self.tree.column("size", width=110, anchor="e")
        self.tree.column("dir", width=220, anchor="w")
        self.tree.column("mtime", width=150, anchor="center")

        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(wrap, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        for cat, color in CATEGORY_COLORS.items():
            self.tree.tag_configure("cat_" + cat, background=color)

        self.tree.bind("<Button-3>", self._on_right_click)

        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="在资源管理器中打开位置", command=self._open_location)
        self.menu.add_command(label="复制完整路径", command=self._copy_path)
        self.menu.add_separator()
        self.menu.add_command(label="删除此文件…", command=self._delete_selected)

    # ---------------- 扫描 ----------------

    def on_scan(self):
        path = self.path_var.get().strip()
        if not path:
            messagebox.showwarning("路径为空", "请输入要扫描的目录路径。")
            return
        if not os.path.isdir(path):
            messagebox.showwarning("路径无效", "该目录不存在：\n%s" % path)
            return
        if self.scanning:
            return
        self._clear_tree()
        self.scanning = True
        self.scan_btn.state(["disabled"])
        self.stop_btn.state(["!disabled"])
        self.app.set_status("正在扫描大文件：%s …" % path)

        self.runner.reset("large_files")
        top_n = self.app.config.large_files_top_n
        min_size = self.app.config.large_files_min_bytes
        budget_s = self.app.config.scan_budget_seconds
        budget_e = self.app.config.scan_budget_entries

        def job(gen, ev, p=path, tn=top_n, ms=min_size, bs=budget_s, be=budget_e):
            files, trunc, entries = scan_large_files(p, tn, bs, be, ev, ms)
            self.runner.emit("large_files", gen, "done", {
                "files": files, "truncated": trunc, "entries": entries, "root": p})

        self.runner.submit("large_files", job, priority=PRIORITY_SCAN, lane=LANE_SCAN)

    def on_stop(self):
        if not self.scanning:
            return
        self.runner.reset("large_files")
        self.app.set_status("已请求停止扫描…")

    # ---------------- 结果处理 ----------------

    def handle(self, kind, payload):
        if kind == "done":
            self._on_done(payload)
        elif kind == "log":
            self.app.logger.warning(payload)

    def _on_done(self, payload):
        self.scanning = False
        self.scan_btn.state(["!disabled"])
        self.stop_btn.state(["disabled"])

        files = payload["files"]
        truncated = payload["truncated"]
        entries = payload["entries"]
        root = payload["root"]

        if not files:
            self.app.set_status("扫描完成，未发现符合条件的大文件（已遍历 %d 项）" % entries)
            return

        for size, path in files:
            name = os.path.basename(path) or path
            parent = os.path.dirname(path)
            mtime = self._mtime_str(path)
            category = classify(path)
            self.tree.insert("", "end", iid=path, text=name,
                             values=(fmt_size(size), parent, mtime),
                             tags=("cat_" + category,))

        suffix = "（受预算限制，结果可能不完整）" if truncated else ""
        self.app.set_status("扫描完成：找到 %d 个大文件（已遍历 %d 项）%s"
                            % (len(files), entries, suffix))
        self.app.logger.info("大文件扫描[%s]完成：%d 个文件，遍历 %d 项%s"
                             % (root, len(files), entries, suffix))

    # ---------------- 交互 ----------------

    def _clear_tree(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)

    def _selected_path(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _on_right_click(self, event):
        iid = self.tree.identify_row(event.y)
        if iid:
            self.tree.selection_set(iid)
            self.tree.focus(iid)
            self.menu.tk_popup(event.x_root, event.y_root)

    def _open_location(self):
        path = self._selected_path()
        if not path:
            return
        try:
            os.startfile(dir_of(path))  # noqa: S606
        except OSError as e:
            messagebox.showwarning("无法打开", str(e))

    def _copy_path(self):
        path = self._selected_path()
        if not path:
            return
        self.clipboard_clear()
        self.clipboard_append(path)
        self.app.set_status("已复制路径：%s" % path)

    def _delete_selected(self):
        path = self._selected_path()
        if not path:
            return
        self.app.run_delete(path, "file")

    @staticmethod
    def _mtime_str(path):
        try:
            ts = os.path.getmtime(path)
        except OSError:
            return "—"
        try:
            return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        except (OSError, ValueError):
            return "—"
