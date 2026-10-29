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
from ..utils.taskrunner import LANE_SCAN, PRIORITY_SCAN

# 结论 → 行背景色
VERDICT_COLORS = {
    VERDICT_FORBID: "#fbe0e0",
    VERDICT_RISKY: "#fdf3d8",
    VERDICT_SAFE: "#e8f6e8",
    VERDICT_KEEP: "#f0f0f0",
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
        bar.pack(fill="x", padx=6, pady=(6, 2))
        ttk.Label(bar, text="扫描路径：").pack(side="left")
        self.path_var = tk.StringVar(value="C:\\")
        ttk.Entry(bar, textvariable=self.path_var, width=60).pack(side="left", padx=(0, 6))
        self.scan_btn = ttk.Button(bar, text="扫描大文件", command=self.on_scan)
        self.scan_btn.pack(side="left")
        self.stop_btn = ttk.Button(bar, text="停止", command=self.on_stop, state="disabled")
        self.stop_btn.pack(side="left", padx=(4, 0))
        ttk.Label(bar, foreground="#888",
                  text="默认仅显示 ≥ 100 MB 的文件（可在设置页调整）").pack(side="left", padx=12)

        # 汇总条：按评估结论统计数量与体积
        self.summary_var = tk.StringVar(value="扫描后这里会给出可删性汇总。")
        ttk.Label(self, textvariable=self.summary_var, anchor="w",
                  foreground="#333").pack(fill="x", padx=8, pady=(0, 2))

        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True, padx=6, pady=6)

        cols = ("advice", "size", "dir", "mtime")
        self.tree = ttk.Treeview(wrap, columns=cols, show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="文件路径")
        self.tree.heading("advice", text="可删性评估")
        self.tree.heading("size", text="大小")
        self.tree.heading("dir", text="所在目录")
        self.tree.heading("mtime", text="修改时间")
        self.tree.column("#0", width=380, anchor="w")
        self.tree.column("advice", width=100, anchor="center")
        self.tree.column("size", width=100, anchor="e")
        self.tree.column("dir", width=200, anchor="w")
        self.tree.column("mtime", width=140, anchor="center")

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
        self.menu.add_command(label="查看评估详情与清理建议", command=self._show_detail)
        self.menu.add_separator()
        self.menu.add_command(label="在资源管理器中打开位置", command=self._open_location)
        self.menu.add_command(label="复制完整路径", command=self._copy_path)
        self.menu.add_separator()
        self._delete_item = self.menu.add_command(label="删除此文件…",
                                                  command=self._delete_selected)

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
            self.summary_var.set("未发现符合条件的大文件。")
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
                parts.append("%s：%d 项 / %s" % (verdict, count, fmt_size(total)))
        self.summary_var.set("按可删性汇总 —— " + "　".join(parts))

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
        if not iid:
            return
        self.tree.selection_set(iid)
        self.tree.focus(iid)
        # 「禁止删除」项禁用删除菜单
        adv = self.advice.get(iid)
        state = "normal" if (adv and adv.deletable) else "disabled"
        self.menu.entryconfig("删除此文件…", state=state)
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
            messagebox.showinfo("提示", "该项尚未完成评估。")
            return

        try:
            size = os.path.getsize(path)
            size_str = fmt_size(size)
        except OSError:
            size_str = "无法读取"

        win = tk.Toplevel(self)
        win.title("评估详情 — " + os.path.basename(path))
        win.transient(self.winfo_toplevel())
        win.grab_set()
        win.resizable(True, True)
        win.geometry("640x420")

        body = ttk.Frame(win, padding=14)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text=path, wraplength=600,
                  font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w")
        ttk.Label(body, text="大小：%s" % size_str,
                  foreground="#555").pack(anchor="w", pady=(2, 10))

        # 结论 + 原因
        ttk.Label(body, text="评估结论", font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w")
        verdict_label = tk.Label(body, text=adv.verdict,
                                 bg=VERDICT_COLORS.get(adv.verdict, "#f0f0f0"),
                                 anchor="w", padx=8, pady=4)
        verdict_label.pack(fill="x", pady=(2, 8))

        ttk.Label(body, text="原因", font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w")
        ttk.Label(body, text=adv.reason, wraplength=600, justify="left").pack(anchor="w", pady=(2, 8))

        ttk.Label(body, text="安全释放方式", font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w")
        ttk.Label(body, text=adv.action, wraplength=600, justify="left").pack(anchor="w", pady=(2, 8))

        # 可选命令（可复制）
        if adv.command:
            ttk.Label(body, text="参考命令（复制后以管理员身份在终端运行）",
                      font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w", pady=(6, 0))
            row = ttk.Frame(body)
            row.pack(fill="x", pady=(2, 0))
            cmd_var = tk.StringVar(value=adv.command)
            cmd_entry = ttk.Entry(row, textvariable=cmd_var, state="readonly")
            cmd_entry.pack(side="left", fill="x", expand=True)
            ttk.Button(row, text="复制", width=6,
                       command=lambda: self._copy_text(win, adv.command)).pack(side="left", padx=(6, 0))

        ttk.Button(body, text="关闭", command=win.destroy).pack(pady=(14, 0))

    def _copy_text(self, win, text):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.app.set_status("已复制命令：%s" % text)
        win.lift()

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
        adv = self.advice.get(path)
        if adv and not adv.deletable:
            messagebox.showwarning(
                "禁止删除",
                "「%s」属于%s类别，不允许通过本程序直接删除。\n\n%s\n\n%s"
                % (os.path.basename(path), adv.verdict, adv.reason, adv.action))
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
