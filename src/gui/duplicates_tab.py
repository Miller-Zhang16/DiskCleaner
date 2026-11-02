# -*- coding: utf-8 -*-
"""重复文件页：查找内容完全相同的文件，并清理多余副本。

交互约定：
    - 输入扫描路径、选择最小体积阈值后点击「查找重复文件」；
    - 后台遍历采用「大小预筛 → 轻量指纹 → SHA-256 确认」，可随时停止；
    - 表格按分组展示，每组默认保留「最早修改」的那一份，其余标记为「删除」；
    - 选中分组后点击「删除选中组的额外副本」，二次确认后批量删除；
    - 删除完成后自动从表格中移除已删除的文件，失败项在结果对话框中逐项列出。
"""

import os
import tkinter as tk
from tkinter import messagebox, ttk

from ..core.duplicates import find_duplicates, keep_path
from ..utils.fmt import dir_of, fmt_size
from ..utils.i18n import tr
from ..utils.taskrunner import LANE_SCAN, PRIORITY_SCAN
from . import theme

MIN_SIZE_CHOICES = (1, 10, 50, 100)


class DuplicatesTab(ttk.Frame):
    """重复文件查找页。"""

    def __init__(self, master, runner, app):
        super().__init__(master)
        self.runner = runner
        self.app = app
        self.scanning = False
        self.groups = []
        self._build()

    # ---------------- 构建界面 ----------------

    def _build(self):
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Label(bar, text=tr("dup.path_label")).pack(side="left")
        self.path_var = tk.StringVar(value="C:\\")
        ttk.Entry(bar, textvariable=self.path_var, width=44).pack(
            side="left", padx=(0, 8))
        ttk.Label(bar, text=tr("dup.min_size")).pack(side="left")
        self.min_var = tk.StringVar(value="%d MB" % self.app.config.duplicates_min_mb)
        ttk.Combobox(bar, textvariable=self.min_var, width=8, state="readonly",
                     values=["%d MB" % n for n in MIN_SIZE_CHOICES]).pack(
            side="left", padx=(4, 10))
        self.scan_btn = ttk.Button(bar, text=tr("dup.btn.scan"),
                                   style="Accent.TButton", command=self.on_scan)
        self.scan_btn.pack(side="left")
        self.stop_btn = ttk.Button(bar, text=tr("dup.btn.stop"),
                                   style="Ghost.TButton", command=self.on_stop,
                                   state="disabled")
        self.stop_btn.pack(side="left", padx=(6, 0))

        hint = ttk.Label(self, style="Muted.TLabel", text=tr("dup.hint"))
        hint.pack(fill="x", pady=(0, 6), anchor="w")
        theme.autowrap(hint)

        head = ttk.Frame(self)
        head.pack(fill="x", pady=(0, 6))
        self.summary_var = tk.StringVar(value=tr("dup.summary.initial"))
        ttk.Label(head, textvariable=self.summary_var, anchor="w",
                  foreground=theme.TEXT, font=theme.font(10, True)).pack(
            side="left", fill="x", expand=True)
        self.clean_btn = ttk.Button(head, text=tr("dup.btn.clean"),
                                    style="Accent.TButton", command=self.on_clean)
        self.clean_btn.pack(side="right")

        wrap = tk.Frame(self, background=theme.CARD,
                        highlightbackground=theme.BORDER, highlightthickness=1)
        wrap.pack(fill="both", expand=True)

        cols = ("size", "count", "reclaim", "keep")
        self.tree = ttk.Treeview(wrap, columns=cols, show="tree headings",
                                 selectmode="browse")
        self.tree.heading("#0", text=tr("dup.col.name"))
        self.tree.heading("size", text=tr("dup.col.size"))
        self.tree.heading("count", text=tr("dup.col.count"))
        self.tree.heading("reclaim", text=tr("dup.col.reclaim"))
        self.tree.heading("keep", text=tr("dup.col.keep"))
        self.tree.column("#0", width=540, anchor="w")
        self.tree.column("size", width=100, anchor="e")
        self.tree.column("count", width=70, anchor="center")
        self.tree.column("reclaim", width=110, anchor="e")
        self.tree.column("keep", width=110, anchor="w")

        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(wrap, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        self.tree.tag_configure("group", background=theme.NEUTRAL_BG,
                                font=theme.font(10, True))
        self.tree.tag_configure("keep", background=theme.SUCCESS_BG)
        self.tree.tag_configure("delete", background=theme.WARN_BG)
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Button-3>", self._on_right_click)

        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label=tr("common.open_location"), command=self._open_location)
        self.menu.add_command(label=tr("common.copy_path"), command=self._copy_path)

    # ---------------- 扫描 ----------------

    def _min_bytes(self):
        raw = self.min_var.get().split()[0]
        try:
            mb = max(1, int(raw))
        except ValueError:
            mb = self.app.config.duplicates_min_mb
        return mb * 1024 * 1024

    def on_scan(self):
        path = self.path_var.get().strip().strip('"')
        if not path:
            messagebox.showwarning(tr("lf.msg.empty_path_title"), tr("lf.msg.empty_path"))
            return
        if not os.path.isdir(path):
            messagebox.showwarning(tr("lf.msg.invalid_path_title"),
                                   tr("lf.msg.invalid_path", path=path))
            return
        if self.scanning:
            return
        self.scanning = True
        self._clear_tree()
        self.groups = []
        self.summary_var.set(tr("dup.status.scanning", path=path, entries=0, candidates=0))
        self.scan_btn.state(["disabled"])
        self.stop_btn.state(["!disabled"])
        self.app.set_status(tr("dup.status.scanning", path=path, entries=0, candidates=0))

        self.runner.reset("duplicates")
        min_bytes = self._min_bytes()
        budget_s = self.app.config.duplicates_budget_seconds
        budget_e = self.app.config.scan_budget_entries

        def job(gen, ev, p=path, ms=min_bytes, bs=budget_s, be=budget_e):
            def progress(entries, candidates):
                self.runner.emit("duplicates", gen, "progress", {
                    "path": p, "entries": entries, "candidates": candidates})
            groups, trunc, entries = find_duplicates(
                p, min_size=ms, budget_seconds=bs, budget_entries=be,
                cancel=ev, progress=progress)
            files = [{"size": g.size, "files": g.files, "keep": keep_path(g.files)}
                     for g in groups]
            self.runner.emit("duplicates", gen, "done", {
                "groups": files, "truncated": trunc, "entries": entries, "root": p})

        self.runner.submit("duplicates", job, priority=PRIORITY_SCAN, lane=LANE_SCAN)

    def on_stop(self):
        if not self.scanning:
            return
        self.runner.reset("duplicates")
        self.app.set_status(tr("dup.status.stop"))

    # ---------------- 结果处理 ----------------

    def handle(self, kind, payload):
        if kind == "progress":
            self.app.set_status(tr("dup.status.scanning", path=payload["path"],
                                   entries=payload["entries"],
                                   candidates=payload["candidates"]))
        elif kind == "done":
            self._on_done(payload)
        elif kind == "log":
            self.app.logger.warning(payload)

    def _on_done(self, payload):
        self.scanning = False
        self.scan_btn.state(["!disabled"])
        self.stop_btn.state(["disabled"])
        self.groups = payload["groups"]
        self._fill_tree()
        self._update_summary()

        total = self._total_reclaimable(self.groups)
        suffix = tr("dup.status.trunc") if payload["truncated"] else ""
        if not self.groups:
            self.app.set_status(tr("dup.status.empty", entries=payload["entries"]) + suffix)
        else:
            self.app.set_status(tr("dup.status.done", groups=len(self.groups),
                                   size=fmt_size(total), entries=payload["entries"],
                                   suffix=suffix))
        self.app.logger.info("重复文件扫描[%s]完成：%d 组，可释放 %s%s"
                             % (payload["root"], len(self.groups),
                                fmt_size(total), suffix))

    @staticmethod
    def _total_reclaimable(groups):
        return sum(g["size"] * (len(g["files"]) - 1) for g in groups)

    def _clear_tree(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)

    def _fill_tree(self):
        self._clear_tree()
        for idx, group in enumerate(self.groups):
            gid = "g:%d" % idx
            name = tr("dup.group", count=len(group["files"]))
            self.tree.insert("", "end", iid=gid, text=name, open=True,
                             values=(fmt_size(group["size"]), len(group["files"]),
                                     fmt_size(group["size"] * (len(group["files"]) - 1)),
                                     os.path.basename(group["keep"])),
                             tags=("group",))
            for path in group["files"]:
                keep = path == group["keep"]
                self.tree.insert(gid, "end", iid=path, text=path,
                                 values=(fmt_size(group["size"]), "", "",
                                         tr("dup.child.keep") if keep else tr("dup.child.delete")),
                                 tags=("keep" if keep else "delete",))

    def _update_summary(self):
        if not self.groups:
            self.summary_var.set(tr("dup.summary.empty"))
            return
        total = self._total_reclaimable(self.groups)
        self.summary_var.set(tr("dup.summary.prefix", groups=len(self.groups),
                                size=fmt_size(total)))

    # ---------------- 交互 ----------------

    def _selected_index(self):
        sel = self.tree.selection()
        if not sel:
            return None
        iid = sel[0]
        if iid.startswith("g:"):
            try:
                return int(iid[2:])
            except ValueError:
                return None
        parent = self.tree.parent(iid)
        if parent.startswith("g:"):
            try:
                return int(parent[2:])
            except ValueError:
                return None
        return None

    def _on_double_click(self, _event):
        iid = self.tree.focus()
        if iid and not iid.startswith("g:"):
            self._open_location()

    def _on_right_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid or iid.startswith("g:"):
            return
        self.tree.selection_set(iid)
        self.tree.focus(iid)
        self.menu.tk_popup(event.x_root, event.y_root)

    def _open_location(self):
        sel = self.tree.selection()
        if not sel or sel[0].startswith("g:"):
            return
        try:
            os.startfile(dir_of(sel[0]))  # noqa: S606
        except OSError as e:
            messagebox.showwarning(tr("common.open_failed"), str(e))

    def _copy_path(self):
        sel = self.tree.selection()
        if not sel or sel[0].startswith("g:"):
            return
        self.clipboard_clear()
        self.clipboard_append(sel[0])
        self.app.set_status(tr("dup.status.copied", path=sel[0]))

    # ---------------- 清理 ----------------

    def on_clean(self):
        idx = self._selected_index()
        if idx is None or idx >= len(self.groups):
            messagebox.showinfo(tr("dup.msg.none_title"), tr("dup.msg.none"))
            return
        group = self.groups[idx]
        paths = [p for p in group["files"] if p != group["keep"]]
        if not paths:
            return
        size = group["size"] * len(paths)
        if not messagebox.askyesno(
                tr("dup.msg.confirm_title"),
                tr("dup.msg.confirm", count=len(paths), size=fmt_size(size))):
            return

        submitted = set(paths)
        self.app.run_delete_many(
            paths, tr("dup.title.delete"),
            on_done=lambda payload: self._after_delete(submitted, payload))

    def _after_delete(self, submitted, payload):
        failed = {p for p, _ in payload.get("skipped", [])}
        gone = submitted - failed
        for group in self.groups:
            group["files"] = [p for p in group["files"] if p not in gone]
            if group["keep"] in gone and group["files"]:
                group["keep"] = keep_path(group["files"])
        self.groups = [g for g in self.groups if len(g["files"]) >= 2]
        self._fill_tree()
        self._update_summary()
