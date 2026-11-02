# -*- coding: utf-8 -*-
"""清理历史窗口。

以表格列出历次清理（时间 / 动作 / 释放空间 / 删除项 / 失败项），
双击某条查看该次的分目标明细与失败原因。记录由
:class:`~src.core.history.History` 维护，条数上限见 ``history_max_records``。
"""

import tkinter as tk
from tkinter import messagebox, ttk

from ..utils.fmt import fmt_size
from ..utils.i18n import tr
from . import theme
from .result_dialog import _error_text


class HistoryDialog(tk.Toplevel):
    """清理历史列表。"""

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.records = []

        self.title(tr("history.title"))
        self.transient(app.root)
        self.geometry("760x460")
        self._build()
        self.reload()
        self.grab_set()

    def _build(self):
        body = ttk.Frame(self, padding=(10, 10, 10, 0))
        body.pack(fill="both", expand=True)

        ttk.Label(body, text=tr("history.hint"),
                  foreground=theme.MUTED).pack(anchor="w", pady=(0, 6))

        wrap = ttk.Frame(body)
        wrap.pack(fill="both", expand=True)

        cols = ("time", "title", "freed", "deleted", "failures")
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings")
        self.tree.heading("time", text=tr("history.col.time"))
        self.tree.heading("title", text=tr("history.col.title"))
        self.tree.heading("freed", text=tr("history.col.freed"))
        self.tree.heading("deleted", text=tr("history.col.deleted"))
        self.tree.heading("failures", text=tr("history.col.failures"))
        self.tree.column("time", width=150, anchor="center")
        self.tree.column("title", width=330, anchor="w")
        self.tree.column("freed", width=100, anchor="e")
        self.tree.column("deleted", width=80, anchor="e")
        self.tree.column("failures", width=80, anchor="e")

        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        self.tree.bind("<Double-1>", self._show_detail)

        bar = ttk.Frame(self, padding=(10, 8))
        bar.pack(fill="x")
        self.count_var = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.count_var,
                  foreground=theme.MUTED).pack(side="left")
        ttk.Button(bar, text=tr("common.close"), command=self.destroy).pack(side="right")
        ttk.Button(bar, text=tr("history.btn.clear"),
                   command=self._clear).pack(side="right", padx=(0, 8))

    def reload(self):
        self.records = self.app.history.load()
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for idx, rec in enumerate(self.records):
            self.tree.insert("", "end", iid=str(idx), values=(
                rec.get("time", ""),
                rec.get("title", ""),
                fmt_size(rec.get("freed", 0)),
                rec.get("deleted", 0),
                rec.get("skipped", 0)))
        self.count_var.set(tr("history.count", count=len(self.records)))

    def _clear(self):
        if not self.records:
            return
        if not messagebox.askyesno(
                tr("history.clear_title"),
                tr("history.clear_confirm", count=len(self.records))):
            return
        self.app.history.clear()
        self.reload()

    def _show_detail(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        rec = self.records[int(sel[0])]
        self._open_record(rec)

    def _open_record(self, rec):
        win = tk.Toplevel(self)
        win.title(tr("history.detail_title", time=rec.get("time", "")))
        win.transient(self)
        win.geometry("680x440")

        body = ttk.Frame(win, padding=12)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text=rec.get("title", tr("app.clean_title")),
                  font=theme.font(10, True)).pack(anchor="w")
        ttk.Label(body, text=tr("history.detail_summary",
                                time=rec.get("time", ""),
                                freed=fmt_size(rec.get("freed", 0)),
                                deleted=rec.get("deleted", 0),
                                failures=rec.get("skipped", 0))).pack(
            anchor="w", pady=(2, 8))

        results = rec.get("results", [])
        if results:
            ttk.Label(body, text=tr("history.detail_results"),
                      font=theme.font(9, True)).pack(anchor="w")
            cols = ("name", "freed", "deleted", "skipped")
            tree = ttk.Treeview(body, columns=cols, show="headings", height=min(6, len(results)))
            tree.heading("name", text=tr("result.col.name"))
            tree.heading("freed", text=tr("result.col.freed"))
            tree.heading("deleted", text=tr("result.col.deleted"))
            tree.heading("skipped", text=tr("result.col.skipped"))
            tree.column("name", width=300, anchor="w")
            tree.column("freed", width=100, anchor="e")
            tree.column("deleted", width=80, anchor="e")
            tree.column("skipped", width=80, anchor="e")
            for r in results:
                tree.insert("", "end", values=(
                    r.get("name", ""), fmt_size(r.get("freed", 0)),
                    r.get("deleted", 0), r.get("skipped", 0)))
            tree.pack(fill="x")

        failures = rec.get("failures", [])
        if failures:
            ttk.Label(body, text=tr("history.detail_failures"),
                      font=theme.font(9, True),
                      foreground=theme.DANGER).pack(anchor="w", pady=(10, 2))
            wrap = ttk.Frame(body)
            wrap.pack(fill="both", expand=True)
            cols = ("path", "reason")
            ftree = ttk.Treeview(wrap, columns=cols, show="headings")
            ftree.heading("path", text=tr("result.col.path"))
            ftree.heading("reason", text=tr("result.col.reason"))
            ftree.column("path", width=440, anchor="w")
            ftree.column("reason", width=180, anchor="w")
            vsb = ttk.Scrollbar(wrap, orient="vertical", command=ftree.yview)
            ftree.configure(yscrollcommand=vsb.set)
            ftree.grid(row=0, column=0, sticky="nsew")
            vsb.grid(row=0, column=1, sticky="ns")
            wrap.rowconfigure(0, weight=1)
            wrap.columnconfigure(0, weight=1)
            for item in failures:
                path = item.get("path", "")
                ftree.insert("", "end", values=(path, _error_text(item.get("error", ""))))

        ttk.Button(body, text=tr("common.close"), command=win.destroy).pack(pady=(10, 0))
