# -*- coding: utf-8 -*-
"""清理建议页：列出清理项、预估可释放空间，并支持一键采用建议。"""

import tkinter as tk
from tkinter import messagebox, ttk

from ..core.targets import estimate_target_size
from ..utils.fmt import fmt_size
from ..utils.i18n import tr
from . import theme


class SuggestTab(ttk.Frame):
    """清理建议页。"""

    def __init__(self, master, runner, app, targets):
        super().__init__(master)
        self.runner = runner
        self.app = app
        self.targets = targets
        self.index = {}   # iid -> target 下标

        self._build()

    # ---------------- 构建界面 ----------------

    def _build(self):
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Button(bar, text=tr("suggest.btn.apply"),
                   style="Accent.TButton", command=self.one_click).pack(side="left")
        ttk.Button(bar, text=tr("suggest.btn.clean_selected"),
                   style="Ghost.TButton",
                   command=self.run_checked).pack(side="left", padx=6)
        ttk.Button(bar, text=tr("suggest.btn.reestimate"),
                   style="Ghost.TButton",
                   command=self.reestimate).pack(side="left")
        self.hint = ttk.Label(bar, style="Muted.TLabel", text="")
        self.hint.pack(side="left", padx=12)

        wrap = tk.Frame(self, background=theme.CARD,
                        highlightbackground=theme.BORDER, highlightthickness=1)
        wrap.pack(fill="both", expand=True)

        cols = ("check", "name", "size", "category", "risk", "desc")
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings",
                                 selectmode="browse")
        for col, text, width, anchor in (
                ("check", tr("suggest.col.check"), 50, "center"),
                ("name", tr("suggest.col.name"), 210, "w"),
                ("size", tr("suggest.col.size"), 110, "e"),
                ("category", tr("suggest.col.category"), 90, "center"),
                ("risk", tr("suggest.col.risk"), 60, "center"),
                ("desc", tr("suggest.col.desc"), 520, "w")):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor=anchor)

        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(wrap, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        self.tree.tag_configure("disabled", foreground=theme.FAINT)
        self.tree.tag_configure("risk_high", foreground=theme.DANGER)
        self.tree.tag_configure("risk_mid", foreground=theme.WARN)
        self.tree.bind("<ButtonRelease-1>", self._on_click)

        self.populate()

    # ---------------- 行渲染 ----------------

    def _values(self, t):
        if t.get("_size") is None:
            size_str = tr("suggest.calculating")
        else:
            size_str = fmt_size(t["_size"]) + (" ≥" if t.get("_trunc") else "")
        desc = t.get("desc", "")
        if t.get("note"):
            desc = "%s（%s）" % (desc, t["note"])
        checked = t.get("_checked")
        if t["needs_admin"] and not self.app.admin:
            checked = False
        return ("☑" if checked else "☐", t["name"], size_str,
                t["category"], t["risk"], desc)

    def populate(self):
        self.tree.delete(*self.tree.get_children())
        self.index.clear()
        for idx, t in enumerate(self.targets):
            iid = "t%d" % idx
            self.index[iid] = idx
            self.tree.insert("", "end", iid=iid, values=self._values(t))
        self.refresh_tags()
        self._update_hint()

    def refresh_rows(self):
        for iid, idx in self.index.items():
            self.tree.item(iid, values=self._values(self.targets[idx]))
        self.refresh_tags()
        self._update_hint()

    def refresh_tags(self):
        for iid, idx in self.index.items():
            t = self.targets[idx]
            tags = []
            if t["needs_admin"] and not self.app.admin:
                tags.append("disabled")
            if t.get("risk") == "高":
                tags.append("risk_high")
            elif t.get("risk") == "中":
                tags.append("risk_mid")
            self.tree.item(iid, tags=tuple(tags))

    def _update_hint(self):
        if self.app.admin:
            self.hint.configure(text=tr("suggest.hint.admin"))
        else:
            self.hint.configure(text=tr("suggest.hint.normal"))

    def refresh_sizes(self):
        """清空预估并重新估算（清理完成后调用）。"""
        for t in self.targets:
            t["_size"] = None
            t["_trunc"] = False
        self.refresh_rows()
        self.reestimate()

    # ---------------- 任务 ----------------

    def reestimate(self):
        self.runner.reset("suggest")
        for t in self.targets:
            t["_size"] = None
            t["_trunc"] = False
        self.refresh_rows()
        self.app.set_status(tr("suggest.status.estimating"))
        for idx in range(len(self.targets)):
            self.runner.submit("suggest", lambda g, ev, i=idx: self._job_estimate(g, ev, i))

    def _job_estimate(self, gen, ev, idx):
        size, trunc = estimate_target_size(
            self.targets[idx], cancel=ev,
            budget_seconds=self.app.config.scan_budget_seconds,
            budget_entries=self.app.config.scan_budget_entries)
        self.runner.emit("suggest", gen, "suggest_size", (idx, size, trunc))

    def handle(self, kind, payload):
        if kind == "suggest_size":
            idx, size, trunc = payload
            t = self.targets[idx]
            t["_size"] = size
            t["_trunc"] = trunc
            iid = "t%d" % idx
            if iid in self.index:
                self.tree.item(iid, values=self._values(t))
        elif kind == "log":
            self.app.logger.warning(payload)

    # ---------------- 交互 ----------------

    def _on_click(self, event):
        if self.tree.identify_column(event.x) != "#1":
            return
        iid = self.tree.identify_row(event.y)
        if not iid or iid not in self.index:
            return
        t = self.targets[self.index[iid]]
        if t["needs_admin"] and not self.app.admin:
            self.app.set_status(tr("suggest.status.need_admin", name=t["name"]))
            return
        t["_checked"] = not t.get("_checked")
        # 记住用户的选择
        self.app.config.set_target_default(t["key"], t["_checked"])
        self.app.config.save()
        self.tree.item(iid, values=self._values(t))

    def _checked_targets(self):
        """返回已勾选且当前权限可执行的目标，以及被权限拦截的目标名。"""
        selected, blocked = [], []
        for t in self.targets:
            if not t.get("_checked"):
                continue
            if t["needs_admin"] and not self.app.admin:
                blocked.append(t["name"])
            else:
                selected.append(t)
        return selected, blocked

    def run_checked(self):
        selected, blocked = self._checked_targets()
        if not selected:
            if blocked:
                messagebox.showwarning(
                    tr("suggest.msg.need_admin_title"),
                    tr("suggest.msg.need_admin", names="\n".join(blocked)))
            else:
                messagebox.showinfo(tr("suggest.msg.none_title"), tr("suggest.msg.none"))
            return
        if blocked:
            self.app.logger.info("以下项目因缺少管理员权限被跳过：%s" % "、".join(blocked))

        if self.app.config.confirm_before_clean:
            names = "\n".join("· %s" % t["name"] for t in selected)
            est = sum((t["_size"] or 0) for t in selected)
            if not messagebox.askyesno(
                    tr("suggest.msg.confirm_title"),
                    tr("suggest.msg.confirm", count=len(selected), names=names,
                       size=fmt_size(est))):
                return
        self.app.run_cleanup(selected)

    def one_click(self):
        """一键采用建议：勾选全部内置推荐的安全清理项并执行。"""
        for t in self.targets:
            t["_checked"] = bool(t.get("default")) and (
                not t["needs_admin"] or self.app.admin)
            self.app.config.set_target_default(t["key"], t["_checked"])
        self.app.config.save()
        self.refresh_rows()
        self.run_checked()
