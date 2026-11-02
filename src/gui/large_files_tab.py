# -*- coding: utf-8 -*-
"""大文件扫描页：找出指定目录下体积最大的 N 个文件，并评估可删性。

交互约定：
    - 输入扫描路径（默认 C:\\），点击「扫描大文件」后在后台遍历；
    - 表格按体积降序列出最大的 N 个文件，并给出可删性评估（禁止/高风险/可清理/建议保留）；
    - 顶部汇总条按结论统计数量与体积，便于一眼看出「哪些是真不能删的」；
    - 双击任意行查看评估详情（原因 + 安全释放方式 + 可复制的命令）；
    - 右键菜单：打开位置 / 复制路径 / 查看清理建议 / 删除（「禁止删除」项被禁用）；
    - 扫描受时间与条目预算限制，提前结束时状态栏会提示「可能不完整」。
"""

import datetime
import os
import tkinter as tk
from tkinter import messagebox, ttk

from ..core.file_advice import (
    VERDICT_FORBID,
    VERDICT_KEEP,
    VERDICT_RISKY,
    VERDICT_SAFE,
    assess,
)
from ..core.scanner import scan_large_files
from ..utils.fmt import dir_of, fmt_size
from ..utils.i18n import tr
from ..utils.taskrunner import LANE_SCAN, PRIORITY_SCAN
from . import theme

# 结论 → 行背景色
VERDICT_COLORS = {
    VERDICT_FORBID: theme.DANGER_BG,
    VERDICT_RISKY: theme.WARN_BG,
    VERDICT_SAFE: theme.SUCCESS_BG,
    VERDICT_KEEP: theme.NEUTRAL_BG,
}


class LargeFilesTab(ttk.Frame):
    """大文件扫描页。"""

    def __init__(self, master, runner, app):
        super().__init__(master)
        self.runner = runner
        self.app = app
        self.scanning = False
        self.advice = {}  # path -> Advice
        self._build()

    # ---------------- 构建界面 ----------------

    def _build(self):
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Label(bar, text=tr("lf.path_label")).pack(side="left")
        self.path_var = tk.StringVar(value="C:\\")
        ttk.Entry(bar, textvariable=self.path_var, width=52).pack(
            side="left", padx=(0, 8))
        self.scan_btn = ttk.Button(bar, text=tr("lf.btn.scan"),
                                   style="Accent.TButton", command=self.on_scan)
        self.scan_btn.pack(side="left")
        self.stop_btn = ttk.Button(bar, text=tr("lf.btn.stop"),
                                   style="Ghost.TButton", command=self.on_stop,
                                   state="disabled")
        self.stop_btn.pack(side="left", padx=(6, 0))

        hint = ttk.Label(self, style="Muted.TLabel", text=tr("lf.hint"))
        hint.pack(fill="x", pady=(0, 4), anchor="w")
        theme.autowrap(hint)

        # 汇总条：按评估结论统计数量与体积
        self.summary_var = tk.StringVar(value=tr("lf.summary.initial"))
        ttk.Label(self, textvariable=self.summary_var, anchor="w",
                  foreground=theme.TEXT, font=theme.font(10, True)).pack(
            fill="x", pady=(0, 6))

        wrap = tk.Frame(self, background=theme.CARD,
                        highlightbackground=theme.BORDER, highlightthickness=1)
        wrap.pack(fill="both", expand=True)

        cols = ("advice", "size", "dir", "mtime")
        self.tree = ttk.Treeview(wrap, columns=cols, show="tree headings", selectmode="browse")
        self.tree.heading("#0", text=tr("lf.col.path"))
        self.tree.heading("advice", text=tr("lf.col.advice"))
        self.tree.heading("size", text=tr("lf.col.size"))
        self.tree.heading("dir", text=tr("lf.col.dir"))
        self.tree.heading("mtime", text=tr("lf.col.mtime"))
        self.tree.column("#0", width=340, anchor="w")
        self.tree.column("advice", width=96, anchor="center")
        self.tree.column("size", width=90, anchor="e")
        self.tree.column("dir", width=170, anchor="w")
        self.tree.column("mtime", width=125, anchor="center")

        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(wrap, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        for verdict, color in VERDICT_COLORS.items():
            self.tree.tag_configure(verdict, background=color)

        self.tree.bind("<Button-3>", self._on_right_click)
        self.tree.bind("<Double-1>", self._on_double_click)

        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label=tr("lf.menu.detail"), command=self._show_detail)
        self.menu.add_separator()
        self.menu.add_command(label=tr("common.open_location"), command=self._open_location)
        self.menu.add_command(label=tr("common.copy_path"), command=self._copy_path)
        self.menu.add_separator()
        self._delete_item = self.menu.add_command(label=tr("lf.menu.delete"),
                                                  command=self._delete_selected)

    # ---------------- 扫描 ----------------

    def on_scan(self):
        path = self.path_var.get().strip()
        if not path:
            messagebox.showwarning(tr("lf.msg.empty_path_title"), tr("lf.msg.empty_path"))
            return
        if not os.path.isdir(path):
            messagebox.showwarning(tr("lf.msg.invalid_path_title"),
                                   tr("lf.msg.invalid_path", path=path))
            return
        if self.scanning:
            return
        self._clear_tree()
        self.scanning = True
        self.scan_btn.state(["disabled"])
        self.stop_btn.state(["!disabled"])
        self.app.set_status(tr("lf.status.scanning", path=path))

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
        self.app.set_status(tr("lf.status.stop"))

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
            self.app.set_status(tr("lf.status.empty", entries=entries))
            self.summary_var.set(tr("lf.summary.empty"))
            return

        # 评估并填充表格
        self.advice.clear()
        stats = {}
        for size, path in files:
            adv = assess(path, size)
            self.advice[path] = adv
            count, total = stats.get(adv.verdict, (0, 0))
            stats[adv.verdict] = (count + 1, total + size)

            name = os.path.basename(path) or path
            parent = os.path.dirname(path)
            mtime = self._mtime_str(path)
            self.tree.insert("", "end", iid=path, text=name,
                             values=(adv.verdict, fmt_size(size), parent, mtime),
                             tags=(adv.verdict,))

        # 汇总条
        parts = []
        for verdict in (VERDICT_FORBID, VERDICT_RISKY, VERDICT_SAFE, VERDICT_KEEP):
            if verdict in stats:
                count, total = stats[verdict]
                parts.append(tr("lf.summary.item", verdict=verdict, count=count,
                                size=fmt_size(total)))
        self.summary_var.set(tr("lf.summary.prefix") + "　".join(parts))

        suffix = tr("lf.status.trunc_suffix") if truncated else ""
        self.app.set_status(tr("lf.status.done", count=len(files),
                               entries=entries, suffix=suffix))
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
        if not iid:
            return
        self.tree.selection_set(iid)
        self.tree.focus(iid)
        # 「禁止删除」项禁用删除菜单
        adv = self.advice.get(iid)
        state = "normal" if (adv and adv.deletable) else "disabled"
        self.menu.entryconfig(self._delete_item, state=state)
        self.menu.tk_popup(event.x_root, event.y_root)

    def _on_double_click(self, _event):
        self._show_detail()

    def _show_detail(self):
        """弹出评估详情对话框：结论、原因、安全操作、可复制命令。"""
        path = self._selected_path()
        if not path:
            return
        adv = self.advice.get(path)
        if not adv:
            messagebox.showinfo(tr("lf.msg.no_advice_title"), tr("lf.msg.no_advice"))
            return

        try:
            size = os.path.getsize(path)
            size_str = fmt_size(size)
        except OSError:
            size_str = "—"

        win = tk.Toplevel(self)
        win.title(tr("lf.detail.title", name=os.path.basename(path)))
        win.transient(self.winfo_toplevel())
        win.grab_set()
        win.resizable(True, True)
        win.geometry("640x420")

        body = ttk.Frame(win, padding=14)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text=path, wraplength=600,
                  font=theme.font(10, True)).pack(anchor="w")
        ttk.Label(body, text=tr("lf.detail.size", size=size_str),
                  foreground=theme.MUTED).pack(anchor="w", pady=(2, 10))

        # 结论 + 原因
        ttk.Label(body, text=tr("lf.detail.verdict"),
                  font=theme.font(9, True)).pack(anchor="w")
        verdict_label = tk.Label(body, text=adv.verdict,
                                 bg=VERDICT_COLORS.get(adv.verdict, theme.NEUTRAL_BG),
                                 fg=theme.TEXT, anchor="w", padx=8, pady=4)
        verdict_label.pack(fill="x", pady=(2, 8))

        ttk.Label(body, text=tr("lf.detail.reason"),
                  font=theme.font(9, True)).pack(anchor="w")
        ttk.Label(body, text=adv.reason, wraplength=600, justify="left").pack(anchor="w", pady=(2, 8))

        ttk.Label(body, text=tr("lf.detail.action"),
                  font=theme.font(9, True)).pack(anchor="w")
        ttk.Label(body, text=adv.action, wraplength=600, justify="left").pack(anchor="w", pady=(2, 8))

        # 可选命令（可复制）
        if adv.command:
            ttk.Label(body, text=tr("lf.detail.command"),
                      font=theme.font(9, True)).pack(anchor="w", pady=(6, 0))
            row = ttk.Frame(body)
            row.pack(fill="x", pady=(2, 0))
            cmd_var = tk.StringVar(value=adv.command)
            cmd_entry = ttk.Entry(row, textvariable=cmd_var, state="readonly")
            cmd_entry.pack(side="left", fill="x", expand=True)
            ttk.Button(row, text=tr("common.copy"), width=6,
                       command=lambda: self._copy_text(win, adv.command)).pack(side="left", padx=(6, 0))

        ttk.Button(body, text=tr("common.close"), command=win.destroy).pack(pady=(14, 0))

    def _copy_text(self, win, text):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.app.set_status(tr("lf.status.copied_cmd", cmd=text))
        win.lift()

    def _open_location(self):
        path = self._selected_path()
        if not path:
            return
        try:
            os.startfile(dir_of(path))  # noqa: S606
        except OSError as e:
            messagebox.showwarning(tr("common.open_failed"), str(e))

    def _copy_path(self):
        path = self._selected_path()
        if not path:
            return
        self.clipboard_clear()
        self.clipboard_append(path)
        self.app.set_status(tr("lf.status.copied_path", path=path))

    def _delete_selected(self):
        path = self._selected_path()
        if not path:
            return
        adv = self.advice.get(path)
        if adv and not adv.deletable:
            messagebox.showwarning(
                tr("lf.msg.forbid_title"),
                tr("lf.msg.forbid", name=os.path.basename(path), verdict=adv.verdict,
                   reason=adv.reason, action=adv.action))
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
