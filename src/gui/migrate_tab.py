# -*- coding: utf-8 -*-
"""迁移页：把 C 盘大目录搬到其他盘，并在原路径保留目录链接。

交互约定：
    - 左侧填写源目录（C 盘上的大目录）与目标目录（其他盘的不存在路径）；
    - 「检查并计算体积」在后台估算体积并做全部安全校验，结果直接显示在信息栏；
    - 校验通过后才能「开始迁移」，迁移前会再次确认风险；
    - 迁移是三阶段的：复制 → 校验 → 删源 → 建链接，中途可停止并稍后续跑；
    - 下方表格列出所有迁移记录，可续跑、撤销（仅复制阶段）、打开目标或移除记录。
"""

import os
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..core.migrator import (
    STAGE_COPIED,
    STAGE_LINKED,
    STAGE_PLANNED,
    STAGE_SOURCE_DELETED,
    estimate,
    migrate,
    undo,
    validate,
)
from ..utils.fmt import fmt_size
from ..utils.i18n import tr
from ..utils.taskrunner import LANE_BATCH, LANE_SCAN, PRIORITY_BATCH, PRIORITY_SCAN
from . import theme

_STAGE_KEYS = {
    STAGE_PLANNED: "migrate.stage.planned",
    STAGE_COPIED: "migrate.stage.copied",
    STAGE_SOURCE_DELETED: "migrate.stage.source_deleted",
    STAGE_LINKED: "migrate.stage.linked",
}


def _stage_label(stage):
    key = _STAGE_KEYS.get(stage)
    return tr(key) if key else str(stage)


class MigrateTab(ttk.Frame):
    """目录迁移页。"""

    def __init__(self, master, runner, app):
        super().__init__(master)
        self.runner = runner
        self.app = app
        self.busy = False
        self.checked = False      # 当前源/目标是否已通过校验
        self.check_size = 0
        self.check_files = 0
        self.records = []
        self._build()
        self.reload_records()

    # ---------------- 构建界面 ----------------

    def _build(self):
        tip = ttk.Label(self, style="Muted.TLabel", justify="left",
                        text=tr("migrate.tip"))
        tip.pack(fill="x", pady=(0, 10))
        theme.autowrap(tip)

        form_card = theme.card(self)
        form_card.pack(fill="x", pady=(0, 10))
        form = tk.Frame(form_card, background=theme.CARD)
        form.pack(fill="x", padx=14, pady=12)

        ttk.Label(form, style="Card.TLabel",
                  text=tr("migrate.src")).grid(row=0, column=0, sticky="w", pady=3)
        self.src_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.src_var, width=80).grid(
            row=0, column=1, sticky="ew", padx=(0, 6), pady=3)
        ttk.Button(form, text=tr("common.browse"), width=8,
                   command=lambda: self._pick(self.src_var)).grid(row=0, column=2, pady=3)

        ttk.Label(form, style="Card.TLabel",
                  text=tr("migrate.dst")).grid(row=1, column=0, sticky="w", pady=3)
        self.dst_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.dst_var, width=80).grid(
            row=1, column=1, sticky="ew", padx=(0, 6), pady=3)
        ttk.Button(form, text=tr("common.browse"), width=8,
                   command=lambda: self._pick(self.dst_var)).grid(row=1, column=2, pady=3)
        form.columnconfigure(1, weight=1)

        self.info_var = tk.StringVar(value=tr("migrate.info.initial"))
        self.info_label = ttk.Label(self, textvariable=self.info_var,
                                    justify="left", foreground=theme.TEXT)
        self.info_label.pack(fill="x", pady=(0, 8))
        theme.autowrap(self.info_label)

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 6))
        self.check_btn = ttk.Button(bar, text=tr("migrate.btn.check"),
                                    style="Accent.TButton", command=self.on_check)
        self.check_btn.pack(side="left")
        self.start_btn = ttk.Button(bar, text=tr("migrate.btn.start"),
                                    style="Accent.TButton", command=self.on_start,
                                    state="disabled")
        self.start_btn.pack(side="left", padx=6)
        self.stop_btn = ttk.Button(bar, text=tr("migrate.btn.stop"),
                                   style="Ghost.TButton", command=self.on_stop,
                                   state="disabled")
        self.stop_btn.pack(side="left")

        prog_row = ttk.Frame(self)
        prog_row.pack(fill="x", pady=(0, 8))
        self.progress = ttk.Progressbar(prog_row, mode="determinate", maximum=100, length=400)
        self.progress_var = tk.StringVar(value="")
        self.progress_label = ttk.Label(prog_row, textvariable=self.progress_var,
                                        style="Muted.TLabel")

        # 迁移记录
        rec = ttk.LabelFrame(self, text=tr("migrate.group.records"),
                             style="Card.TLabelframe", padding=(10, 6))
        rec.pack(fill="both", expand=True, pady=(0, 4))

        # 操作按钮先占底部空间，避免表格把按钮挤出可视区域
        actions = tk.Frame(rec, background=theme.CARD)
        actions.pack(side="bottom", fill="x", pady=(8, 0))
        ttk.Button(actions, text=tr("migrate.btn.resume"), style="Ghost.TButton",
                   command=self.on_resume).pack(side="left")
        ttk.Button(actions, text=tr("migrate.btn.undo"), style="Ghost.TButton",
                   command=self.on_undo).pack(side="left", padx=6)
        ttk.Button(actions, text=tr("migrate.btn.open_target"), style="Ghost.TButton",
                   command=self.on_open_target).pack(side="left")
        ttk.Button(actions, text=tr("migrate.btn.remove"), style="Ghost.TButton",
                   command=self.on_remove_record).pack(side="left", padx=6)
        ttk.Button(actions, text=tr("common.refresh"), style="Ghost.TButton",
                   command=self.reload_records).pack(side="right")

        cols = ("src", "dst", "stage", "size", "updated")
        wrap = tk.Frame(rec, background=theme.CARD)
        wrap.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("src", text=tr("migrate.col.src"))
        self.tree.heading("dst", text=tr("migrate.col.dst"))
        self.tree.heading("stage", text=tr("migrate.col.stage"))
        self.tree.heading("size", text=tr("migrate.col.size"))
        self.tree.heading("updated", text=tr("migrate.col.updated"))
        self.tree.column("src", width=330, anchor="w")
        self.tree.column("dst", width=330, anchor="w")
        self.tree.column("stage", width=110, anchor="center")
        self.tree.column("size", width=90, anchor="e")
        self.tree.column("updated", width=150, anchor="center")
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        for stage in _STAGE_KEYS:
            self.tree.tag_configure("st_" + stage, background=(
                theme.SUCCESS_BG if stage == STAGE_LINKED else theme.WARN_BG))
        self.tree.bind("<Double-1>", self._on_double_click)

        # 任一输入变化都让已通过的校验失效
        self.src_var.trace_add("write", lambda *_a: self._invalidate())
        self.dst_var.trace_add("write", lambda *_a: self._invalidate())

    def _pick(self, var):
        path = filedialog.askdirectory(title=tr("migrate.pick_title"))
        if path:
            var.set(path)

    # ---------------- 校验 ----------------

    def _invalidate(self):
        self.checked = False
        if not self.busy:
            self.start_btn.state(["disabled"])

    def on_check(self):
        if self.busy:
            return
        src = self.src_var.get().strip().strip('"')
        dst = self.dst_var.get().strip().strip('"')
        if not src or not dst:
            self.info_var.set(tr("migrate.info.need_paths"))
            return
        self.check_btn.state(["disabled"])
        self.app.set_status(tr("migrate.status.estimating", path=src))
        self.runner.reset("migrate")

        def job(gen, ev, s=src, d=dst):
            size, files, entries, links, errors = estimate(s, ev)
            problems = validate(s, d, size)
            if links:
                problems.append(tr("migrate.problem.links",
                                   count=len(links), example=links[0]))
            if errors:
                problems.append(tr("migrate.problem.errors",
                                   count=len(errors), example=errors[0][0]))
            if size <= 0 and not problems:
                problems.append(tr("migrate.problem.empty"))
            self.runner.emit("migrate", gen, "checked", {
                "src": s, "dst": d, "size": size, "files": files,
                "entries": entries, "problems": problems})

        self.runner.submit("migrate", job, priority=PRIORITY_SCAN, lane=LANE_SCAN)

    def _on_checked(self, payload):
        self.check_btn.state(["!disabled"])
        problems = payload["problems"]
        size = payload["size"]
        files = payload["files"]
        if problems:
            self.checked = False
            self.start_btn.state(["disabled"])
            self.info_var.set(tr("migrate.info.problems",
                                 problems="\n• ".join(problems)))
            self.app.set_status(tr("migrate.status.check_failed",
                                   count=len(problems)))
            self.app.logger.info("迁移校验未通过：%s" % problems)
            return

        self.checked = True
        self.check_size = size
        self.check_files = files
        self.start_btn.state(["!disabled"])
        self.info_var.set(tr("migrate.info.checked",
                             files=files, size=fmt_size(size)))
        self.app.set_status(tr("migrate.status.checked",
                               src=payload["src"], size=fmt_size(size)))

    # ---------------- 迁移执行 ----------------

    def on_start(self):
        if self.busy or not self.checked:
            return
        src = self.src_var.get().strip().strip('"')
        dst = self.dst_var.get().strip().strip('"')
        if not messagebox.askyesno(
                tr("migrate.msg.confirm_title"),
                tr("migrate.msg.confirm", src=src, dst=dst,
                   size=fmt_size(self.check_size), files=self.check_files)):
            return

        record = {
            "src": src,
            "dst": dst,
            "stage": STAGE_PLANNED,
            "size": self.check_size,
            "files": self.check_files,
        }
        self._submit(record, tr("migrate.title.start",
                                name=os.path.basename(src.rstrip("\\/"))))

    def on_resume(self):
        rec = self._selected_record()
        if not rec:
            messagebox.showinfo(tr("migrate.msg.pick_title"), tr("migrate.msg.pick"))
            return
        if rec.get("stage") == STAGE_LINKED:
            messagebox.showinfo(tr("migrate.msg.linked_title"), tr("migrate.msg.linked"))
            return
        stage = rec.get("stage", STAGE_PLANNED)
        hint = {
            STAGE_PLANNED: tr("migrate.msg.resume_hint_planned"),
            STAGE_COPIED: tr("migrate.msg.resume_hint_copied"),
        }.get(stage, tr("migrate.msg.resume_hint_other"))
        if not messagebox.askyesno(
                tr("migrate.msg.resume_title"),
                tr("migrate.msg.resume", hint=hint, src=rec["src"], dst=rec["dst"])):
            return
        self._submit(rec, tr("migrate.title.resume",
                             name=os.path.basename(rec["src"].rstrip("\\/"))))

    def _submit(self, record, title):
        if self.busy:
            messagebox.showinfo(tr("migrate.msg.busy_title"), tr("migrate.msg.busy"))
            return
        self.busy = True
        self._set_running(True)
        self.progress.configure(value=0)
        self.progress_var.set("0%")
        self.app.set_status(tr("migrate.info.running", title=title))
        self.runner.reset("migrate")

        def job(gen, ev, rec=dict(record)):
            last = [0, 0.0]

            def on_progress(copied, total, name):
                pct = int(copied * 100 / total) if total else 0
                now = time.time()
                if pct >= last[0] + 1 or now - last[1] >= 0.3:
                    last[0], last[1] = pct, now
                    self.runner.emit("migrate", gen, "progress",
                                     {"percent": pct, "text": name})

            def log(msg):
                self.runner.emit("migrate", gen, "log", msg)

            rec, ok, msg = migrate(rec, cancel=ev, on_progress=on_progress,
                                   log=log, store=self.app.migrations)
            self.runner.emit("migrate", gen, "done",
                             {"record": rec, "ok": ok, "message": msg,
                              "title": title, "undo": False})

        self.runner.submit("migrate", job, priority=PRIORITY_BATCH, lane=LANE_BATCH)

    def on_stop(self):
        if not self.busy:
            return
        self.runner.reset("migrate")
        self.busy = False
        self._set_running(False)
        self.progress_var.set(tr("migrate.progress.stopped"))
        self.app.set_status(tr("migrate.status.stopping"))
        self.app.logger.info("用户请求停止迁移。")
        self.after(800, self.reload_records)

    def handle(self, kind, payload):
        if kind == "checked":
            self._on_checked(payload)
        elif kind == "progress":
            self.progress.configure(value=payload["percent"])
            self.progress_var.set("%d%%  %s" % (payload["percent"],
                                                os.path.basename(payload["text"] or "")))
        elif kind == "log":
            self.app.logger.info(payload)
        elif kind == "done":
            self._on_done(payload)

    def _on_done(self, payload):
        self.busy = False
        self._set_running(False)
        rec = payload["record"]
        ok = payload["ok"]
        msg = payload["message"]
        self.reload_records()
        self.check_btn.state(["!disabled"])
        self._invalidate()
        if payload.get("undo"):
            if ok:
                self.app.set_status(tr("migrate.status.undoed", src=rec["src"]))
                self.info_var.set(tr("migrate.info.undoed", src=rec["src"]))
                messagebox.showinfo(tr("migrate.msg.undoed_title"),
                                    tr("migrate.msg.undoed", msg=msg))
            else:
                self.app.set_status(tr("migrate.status.undo_failed", msg=msg))
                messagebox.showwarning(tr("migrate.msg.undo_failed_title"), msg)
            return
        if ok:
            self.progress.configure(value=100)
            self.progress_var.set("100%")
            self.app.set_status(tr("migrate.status.done", src=rec["src"]))
            self.info_var.set(tr("migrate.info.done", src=rec["src"], dst=rec["dst"]))
            messagebox.showinfo(tr("migrate.msg.done_title"),
                                tr("migrate.msg.done", msg=msg,
                                   src=rec["src"], dst=rec["dst"]))
        else:
            self.app.set_status(tr("migrate.status.failed", msg=msg))
            self.info_var.set(tr("migrate.info.failed", msg=msg))
            self.app.logger.warning("迁移未完成：%s" % msg)
            messagebox.showwarning(tr("migrate.msg.failed_title"),
                                   tr("migrate.msg.failed", msg=msg))

    def _set_running(self, running):
        if running:
            if not self.progress.winfo_manager():
                self.progress.pack(side="left")
                self.progress_label.pack(side="left", padx=8)
        else:
            self.progress.pack_forget()
            self.progress_label.pack_forget()
        self.check_btn.state(["disabled"] if running else ["!disabled"])
        self.start_btn.state(["disabled"] if running or not self.checked else ["!disabled"])
        self.stop_btn.state(["!disabled"] if running else ["disabled"])

    # ---------------- 记录表 ----------------

    def reload_records(self):
        self.records = self.app.migrations.load()
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for idx, rec in enumerate(self.records):
            stage = rec.get("stage", STAGE_PLANNED)
            self.tree.insert("", "end", iid=str(idx), values=(
                rec.get("src", ""), rec.get("dst", ""),
                _stage_label(stage),
                fmt_size(rec.get("size", 0)), rec.get("updated", "")),
                tags=("st_" + stage,))

    def _selected_record(self):
        sel = self.tree.selection()
        if not sel:
            return None
        try:
            return self.records[int(sel[0])]
        except (ValueError, IndexError):
            return None

    def _on_double_click(self, _event=None):
        rec = self._selected_record()
        if rec:
            self.info_var.set(tr("migrate.info.record",
                                 src=rec.get("src"), dst=rec.get("dst"),
                                 stage=_stage_label(rec.get("stage", STAGE_PLANNED)),
                                 size=fmt_size(rec.get("size", 0))))

    def on_undo(self):
        rec = self._selected_record()
        if not rec:
            messagebox.showinfo(tr("migrate.msg.pick_title"), tr("migrate.msg.pick"))
            return
        stage = rec.get("stage", STAGE_PLANNED)
        if stage not in (STAGE_PLANNED, STAGE_COPIED):
            messagebox.showwarning(tr("migrate.msg.undo_refuse_title"),
                                   tr("migrate.msg.undo_refuse"))
            return
        if not messagebox.askyesno(
                tr("migrate.msg.undo_confirm_title"),
                tr("migrate.msg.undo_confirm", dst=rec.get("dst"))):
            return
        self.busy = True
        self._set_running(True)
        self.runner.reset("migrate")

        def job(gen, ev, r=dict(rec)):
            ok, msg = undo(r, cancel=ev, log=lambda m: self.runner.emit(
                "migrate", gen, "log", m), store=self.app.migrations)
            self.runner.emit("migrate", gen, "done", {
                "record": r, "ok": ok, "message": msg,
                "title": tr("migrate.undo_title"), "undo": True})

        self.runner.submit("migrate", job, priority=PRIORITY_BATCH, lane=LANE_BATCH)

    def on_open_target(self):
        rec = self._selected_record()
        if not rec:
            return
        target = rec.get("dst")
        if not os.path.isdir(target):
            messagebox.showinfo(tr("migrate.msg.open_missing_title"),
                                tr("migrate.msg.open_missing", path=target))
            return
        try:
            os.startfile(target)  # noqa: S606
        except OSError as e:
            messagebox.showwarning(tr("migrate.msg.open_failed"), str(e))

    def on_remove_record(self):
        rec = self._selected_record()
        if not rec:
            return
        stage = rec.get("stage", STAGE_PLANNED)
        extra = tr("migrate.msg.remove_extra") if stage == STAGE_LINKED else ""
        if not messagebox.askyesno(tr("migrate.msg.remove_title"),
                                   tr("migrate.msg.remove", src=rec["src"], extra=extra)):
            return
        self.app.migrations.remove(rec["src"])
        self.reload_records()
        self.app.set_status(tr("migrate.status.removed", src=rec["src"]))
