# -*- coding: utf-8 -*-
"""清理结果对话框。

替代原先的 messagebox：除了统计数字，还能逐项核对失败明细——
哪个文件没删掉、为什么（被占用 / 无权限 / 路径不存在）。
失败项支持双击复制路径，便于用户手动处理。

设计取舍：失败明细用表格而非纯文本列表，是因为一次清理可能跳过上百项，
文本堆叠既看不清也无法复制单条路径。
"""

import tkinter as tk
from tkinter import ttk

from ..utils.fmt import fmt_size
from ..utils.i18n import tr
from . import theme


def _error_text(err):
    """把底层 OSError 文本转成用户能理解的说法。"""
    text = str(err)
    low = text.lower()
    if "winerror 32" in low or "being used" in low or "另一个程序" in text:
        return tr("result.reason.busy")
    if "winerror 5" in low or "access is denied" in low or "拒绝访问" in text:
        return tr("result.reason.denied")
    if "winerror 2" in low or "no such file" in low or "找不到" in text:
        return tr("result.reason.missing")
    return text


class ResultDialog(tk.Toplevel):
    """展示一次清理/删除的结果。"""

    def __init__(self, app, payload, on_history=None):
        super().__init__(app.root)
        self.app = app
        self.payload = payload
        self.on_history = on_history

        self.title(tr("result.title"))
        self.transient(app.root)
        self.resizable(True, True)

        skipped = payload.get("skipped", [])
        has_more = len(payload.get("results", [])) > 1
        if skipped:
            self.geometry("720x520")
        elif has_more:
            self.geometry("560x400")
        else:
            self.geometry("520x260")

        self._build(skipped, has_more)
        self.grab_set()
        self.focus_set()

    def _build(self, skipped, has_more):
        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)

        title = self.payload.get("title", tr("app.clean_title"))
        ttk.Label(body, text=title, font=theme.font(11, True)).pack(anchor="w")

        freed = self.payload.get("freed", 0)
        deleted = self.payload.get("deleted", 0)
        summary = tr("result.summary", freed=fmt_size(freed), deleted=deleted)
        ttk.Label(body, text=summary, font=theme.font(10)).pack(anchor="w", pady=(4, 2))

        if self.payload.get("cancelled"):
            ttk.Label(body, text=tr("result.cancelled"),
                      foreground=theme.DANGER).pack(anchor="w", pady=(0, 4))

        # 分目标明细
        results = self.payload.get("results", [])
        if has_more:
            ttk.Label(body, text=tr("result.results_heading"),
                      font=theme.font(9, True)).pack(
                anchor="w", pady=(8, 2))
            cols = ("name", "freed", "deleted", "skipped")
            tree = ttk.Treeview(body, columns=cols, show="headings", height=min(6, len(results)))
            tree.heading("name", text=tr("result.col.name"))
            tree.heading("freed", text=tr("result.col.freed"))
            tree.heading("deleted", text=tr("result.col.deleted"))
            tree.heading("skipped", text=tr("result.col.skipped"))
            tree.column("name", width=260, anchor="w")
            tree.column("freed", width=100, anchor="e")
            tree.column("deleted", width=80, anchor="e")
            tree.column("skipped", width=80, anchor="e")
            for r in results:
                tree.insert("", "end", values=(
                    r.get("name", ""), fmt_size(r.get("freed", 0)),
                    r.get("deleted", 0), r.get("skipped", 0)))
            tree.pack(fill="x")

        # 失败明细
        if skipped:
            ttk.Label(body, text=tr("result.failures_heading", count=len(skipped)),
                      font=theme.font(9, True),
                      foreground=theme.DANGER).pack(anchor="w", pady=(10, 2))

            wrap = ttk.Frame(body)
            wrap.pack(fill="both", expand=True)
            cols = ("path", "reason")
            ftree = ttk.Treeview(wrap, columns=cols, show="headings")
            ftree.heading("path", text=tr("result.col.path"))
            ftree.heading("reason", text=tr("result.col.reason"))
            ftree.column("path", width=470, anchor="w")
            ftree.column("reason", width=160, anchor="w")
            vsb = ttk.Scrollbar(wrap, orient="vertical", command=ftree.yview)
            ftree.configure(yscrollcommand=vsb.set)
            ftree.grid(row=0, column=0, sticky="nsew")
            vsb.grid(row=0, column=1, sticky="ns")
            wrap.rowconfigure(0, weight=1)
            wrap.columnconfigure(0, weight=1)

            for path, err in skipped:
                ftree.insert("", "end", iid=path,
                             values=(path, _error_text(err)))

            def copy_sel(_event=None):
                sel = ftree.selection()
                if sel:
                    self.clipboard_clear()
                    self.clipboard_append(sel[0])
                    self.app.set_status(tr("result.status.copied", path=sel[0]))

            ftree.bind("<Double-1>", copy_sel)

        # 底部按钮
        bar = ttk.Frame(self, padding=(14, 0, 14, 12))
        bar.pack(fill="x")
        ttk.Button(bar, text=tr("common.close"), command=self.destroy).pack(side="right")
        if self.on_history is not None:
            ttk.Button(bar, text=tr("result.btn.history"), command=self._open_history).pack(
                side="right", padx=(0, 8))

    def _open_history(self):
        if self.on_history is not None:
            self.on_history()
