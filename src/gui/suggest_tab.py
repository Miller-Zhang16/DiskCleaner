# -*- coding: utf-8 -*-
"""清理建议页：列出清理项、预估可释放空间，并支持一键采用建议。"""

from tkinter import messagebox, ttk

from ..core.targets import estimate_target_size
from ..utils.fmt import fmt_size


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
        bar.pack(fill="x", padx=6, pady=(6, 2))
        ttk.Button(bar, text="一键采用建议", command=self.one_click).pack(side="left")
        ttk.Button(bar, text="清理选中项", command=self.run_checked).pack(side="left", padx=6)
        ttk.Button(bar, text="重新估算", command=self.reestimate).pack(side="left")
        self.hint = ttk.Label(bar, foreground="#555", text="")
        self.hint.pack(side="left", padx=12)

        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True, padx=6, pady=6)

        cols = ("check", "name", "size", "category", "risk", "desc")
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings",
                                 selectmode="browse")
        for col, text, width, anchor in (
                ("check", "勾选", 50, "center"),
                ("name", "清理项", 210, "w"),
                ("size", "预估可释放", 110, "e"),
                ("category", "分类", 90, "center"),
                ("risk", "风险", 60, "center"),
                ("desc", "说明", 520, "w")):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor=anchor)

        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.tag_configure("disabled", foreground="#999")
        self.tree.tag_configure("risk_high", foreground="#c62828")
        self.tree.tag_configure("risk_mid", foreground="#ef6c00")
        self.tree.bind("<ButtonRelease-1>", self._on_click)

        self.populate()

    # ---------------- 行渲染 ----------------

    def _values(self, t):
        if t.get("_size") is None:
            size_str = "计算中…"
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
            self.hint.configure(text="当前：管理员模式，全部清理项可用")
        else:
            self.hint.configure(text="当前：普通模式，标灰的清理项需管理员权限")

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
        self.app.set_status("正在估算各清理项可释放空间…")
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
            self.app.set_status("“%s”需要管理员权限，请先点击“以管理员身份重启”。" % t["name"])
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
                    "需要管理员权限",
                    "选中的清理项均需管理员权限：\n%s\n\n请先点击“以管理员身份重启”。"
                    % "\n".join(blocked))
            else:
                messagebox.showinfo("未选择", "请先勾选要清理的项目。")
            return
        if blocked:
            self.app.logger.info("以下项目因缺少管理员权限被跳过：%s" % "、".join(blocked))

        if self.app.config.confirm_before_clean:
            names = "\n".join("· %s" % t["name"] for t in selected)
            est = sum((t["_size"] or 0) for t in selected)
            if not messagebox.askyesno(
                    "确认清理",
                    "即将清理以下 %d 项：\n%s\n\n预估可释放：约 %s\n\n"
                    "删除后不可恢复，确定继续吗？" % (len(selected), names, fmt_size(est))):
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
