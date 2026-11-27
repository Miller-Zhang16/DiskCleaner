# -*- coding: utf-8 -*-
"""迁移页：把 C 盘大目录搬到其他盘，并在原路径保留目录链接。

交互约定：
    - 手动迁移：填写源目录（C 盘上的大目录）与目标目录（其他盘的不存在路径），
      「检查并计算体积」在后台估算体积并做全部安全校验；
    - 软件迁移：点击「扫描已安装软件」自动枚举 C 盘安装项，过滤系统组件后
      展示可勾选清单，统一指定目标盘后批量提交；
    - 迁移是三阶段的：复制 → 校验 → 删源 → 建链接，中途可停止并稍后续跑；
    - 下方表格列出所有迁移记录，可续跑、撤销（仅复制阶段）、打开目标或移除记录。
"""

import os
import re
import shutil
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
    probe_locked,
    rollback,
    undo,
    validate,
)
from ..core.processes import executables_under, running_executables
from ..core.software import (
    RISK_FORBID,
    RISK_SAFE,
    RISK_WARN,
    scan_candidates,
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
        self.software_items: list = []     # SoftwareItem 列表
        self._row_index: dict = {}         # 表格行 iid -> software_items 下标
        self.submitted_srcs: set = set()   # 已在迁移记录中的源目录（normcase）
        self.sw_drives: list = []          # 探测到的可用目标盘
        self._build()
        self.reload_records()

    # ---------------- 构建界面 ----------------

    def _build(self):
        # 顶部用子页签分成「目录迁移」「软件迁移」「迁移记录」，避免互相挤占高度
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, pady=(0, 8))

        manual = ttk.Frame(self.notebook, padding=(2, 10, 2, 2))
        self.sw_page = ttk.Frame(self.notebook, padding=(2, 10, 2, 2))
        self.records_page = ttk.Frame(self.notebook, padding=(2, 10, 2, 2))
        self.notebook.add(manual, text=tr("migrate.subtab.manual"))
        self.notebook.add(self.sw_page, text=tr("migrate.subtab.software"))
        self.notebook.add(self.records_page, text=tr("migrate.subtab.records"))

        tip = ttk.Label(manual, style="Muted.TLabel", justify="left",
                        text=tr("migrate.tip"))
        tip.pack(fill="x", pady=(0, 10))
        theme.autowrap(tip)

        form_card = theme.card(manual)
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
        self.info_label = ttk.Label(manual, textvariable=self.info_var,
                                    justify="left", foreground=theme.TEXT)
        self.info_label.pack(fill="x", pady=(0, 8))
        theme.autowrap(self.info_label)

        bar = ttk.Frame(manual)
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

        # 软件迁移子页
        self._build_software_page(self.sw_page)

        # 进度条由两种迁移共用，空闲时隐藏，仅在执行中占用一行高度
        prog_row = ttk.Frame(self)
        prog_row.pack(fill="x", pady=(0, 8))
        self.progress = ttk.Progressbar(prog_row, mode="determinate", maximum=100, length=400)
        self.progress_var = tk.StringVar(value="")
        self.progress_label = ttk.Label(prog_row, textvariable=self.progress_var,
                                        style="Muted.TLabel")

        # 迁移记录（独立子页签）
        rec = ttk.Frame(self.records_page)
        rec.pack(fill="both", expand=True)

        # 操作按钮先占底部空间，避免表格把按钮挤出可视区域
        actions = ttk.Frame(rec)
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

    # ---------------- 软件迁移子页 ----------------

    def _build_software_page(self, page):
        hint = ttk.Label(page, text=tr("sw.hint"), style="Muted.TLabel", justify="left")
        hint.pack(fill="x", pady=(0, 8))
        theme.autowrap(hint)

        bar1 = ttk.Frame(page)
        bar1.pack(fill="x", pady=(0, 6))
        self.sw_scan_btn = ttk.Button(bar1, text=tr("sw.btn.scan"),
                                      style="Accent.TButton",
                                      command=self.on_scan_software)
        self.sw_scan_btn.pack(side="left")
        self.sw_stop_btn = ttk.Button(bar1, text=tr("sw.btn.stop"),
                                      style="Ghost.TButton",
                                      command=self.on_stop_software, state="disabled")
        self.sw_stop_btn.pack(side="left", padx=(6, 14))
        self.sw_all_btn = ttk.Button(bar1, text=tr("sw.btn.select_all"),
                                     style="Ghost.TButton",
                                     command=lambda: self._bulk_check("all"))
        self.sw_all_btn.pack(side="left")
        self.sw_none_btn = ttk.Button(bar1, text=tr("sw.btn.select_none"),
                                      style="Ghost.TButton",
                                      command=lambda: self._bulk_check("none"))
        self.sw_none_btn.pack(side="left", padx=6)
        self.sw_safe_btn = ttk.Button(bar1, text=tr("sw.btn.select_safe"),
                                      style="Ghost.TButton",
                                      command=lambda: self._bulk_check("safe"))
        self.sw_safe_btn.pack(side="left")

        bar2 = ttk.Frame(page)
        bar2.pack(fill="x", pady=(0, 8))
        ttk.Label(bar2, text=tr("sw.target_drive")).pack(side="left")
        self.sw_target_var = tk.StringVar()
        self.sw_drive_box = ttk.Combobox(bar2, textvariable=self.sw_target_var,
                                         width=10, state="readonly")
        self.sw_drive_box.pack(side="left", padx=(6, 8))
        self.sw_drive_box.bind("<<ComboboxSelected>>", lambda _e: self._on_drive_change())
        self.sw_free_var = tk.StringVar(value="")
        ttk.Label(bar2, textvariable=self.sw_free_var,
                  style="Muted.TLabel").pack(side="left")
        self.sw_submit_btn = ttk.Button(bar2, text=tr("sw.btn.batch_submit"),
                                        style="Accent.TButton", state="disabled",
                                        command=self.on_batch_submit)
        self.sw_submit_btn.pack(side="right")

        # 详情与汇总先占底部空间，窗口变小时只压缩表格而不是把它们挤没
        self.sw_summary_var = tk.StringVar(value=tr("sw.summary.initial"))
        ttk.Label(page, textvariable=self.sw_summary_var, style="Muted.TLabel",
                  justify="left").pack(side="bottom", fill="x")

        detail = tk.Frame(page, background=theme.CARD, bd=0,
                          highlightbackground=theme.BORDER, highlightthickness=1)
        detail.pack(side="bottom", fill="x", pady=(6, 6))
        self.sw_detail_var = tk.StringVar(value=tr("sw.detail.hint"))
        self.sw_detail_label = ttk.Label(detail, textvariable=self.sw_detail_var,
                                         style="Card.TLabel", justify="left")
        self.sw_detail_label.pack(fill="x", padx=10, pady=8)
        theme.autowrap(self.sw_detail_label)

        cols = ("check", "name", "publisher", "size", "risk", "state")
        wrap = ttk.Frame(page)
        wrap.pack(fill="both", expand=True)
        self.sw_tree = ttk.Treeview(wrap, columns=cols, show="headings",
                                    selectmode="browse", height=6)
        for key, text in (
                ("check", tr("sw.col.check")),
                ("name", tr("sw.col.name")),
                ("publisher", tr("sw.col.publisher")),
                ("size", tr("sw.col.size")),
                ("risk", tr("sw.col.risk")),
                ("state", tr("sw.col.status"))):
            self.sw_tree.heading(key, text=text)
        self.sw_tree.column("check", width=56, anchor="center", stretch=False)
        self.sw_tree.column("name", width=250, anchor="w")
        self.sw_tree.column("publisher", width=150, anchor="w")
        self.sw_tree.column("size", width=90, anchor="e", stretch=False)
        self.sw_tree.column("risk", width=80, anchor="center", stretch=False)
        self.sw_tree.column("state", width=80, anchor="center", stretch=False)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.sw_tree.yview)
        self.sw_tree.configure(yscrollcommand=vsb.set)
        self.sw_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        self.sw_tree.tag_configure("risk_forbid", foreground=theme.DANGER)
        self.sw_tree.tag_configure("risk_warn", foreground=theme.WARN)
        self.sw_tree.tag_configure("risk_safe", foreground=theme.TEXT)
        self.sw_tree.tag_configure("hint", foreground=theme.FAINT)
        # 第一列即勾选框，单击切换；空格键切换当前行
        self.sw_tree.bind("<Button-1>", self._on_sw_click, add="+")
        self.sw_tree.bind("<space>", self._on_sw_space)
        self.sw_tree.bind("<<TreeviewSelect>>", lambda _e: self._refresh_sw_detail())

        self._init_drives()

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
        self.app.begin_progress(tr("migrate.status.estimating", path=src))
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
            # 预检：源目录内是否有程序正在运行、文件是否被占用
            busy = executables_under(s)
            if busy:
                problems.append(tr("migrate.problem.busy",
                                   name=os.path.basename(busy[0])))
            locked = probe_locked(s, ev)
            if locked:
                problems.append(tr("migrate.problem.locked",
                                   count=len(locked),
                                   example=os.path.basename(locked[0][0])))
            self.runner.emit("migrate", gen, "checked", {
                "src": s, "dst": d, "size": size, "files": files,
                "entries": entries, "problems": problems})

        self.runner.submit("migrate", job, priority=PRIORITY_SCAN, lane=LANE_SCAN)

    def _on_checked(self, payload):
        self.check_btn.state(["!disabled"])
        self.app.end_progress()
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
        busy = executables_under(src)
        if busy:
            messagebox.showwarning(
                tr("migrate.msg.busy_proc_title"),
                tr("migrate.problem.busy", name=os.path.basename(busy[0])))
            return
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
        elif kind == "sw_scan_progress":
            done = payload.get("done", 0)
            total = payload.get("total", 0)
            self.sw_summary_var.set(tr("sw.summary.scanning_progress",
                                       done=done, total=total))
            self.app.update_progress(done, total,
                                     text=tr("sw.status.scanning",
                                             name=payload.get("name", "")))
        elif kind == "sw_scan_done":
            self._on_sw_scan_done(payload)

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
        # 记录中已有的源目录，在软件清单里标记「已提交」
        self.submitted_srcs = {
            os.path.normcase(os.path.abspath(r["src"]))
            for r in self.records if r.get("src")}
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for idx, rec in enumerate(self.records):
            stage = rec.get("stage", STAGE_PLANNED)
            self.tree.insert("", "end", iid=str(idx), values=(
                rec.get("src", ""), rec.get("dst", ""),
                _stage_label(stage),
                fmt_size(rec.get("size", 0)), rec.get("updated", "")),
                tags=("st_" + stage,))
        self._refresh_sw_rows()

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
        is_rollback = stage in (STAGE_SOURCE_DELETED, STAGE_LINKED)
        if is_rollback:
            title = tr("migrate.msg.rollback_confirm_title")
            body = tr("migrate.msg.rollback_confirm", src=rec.get("src"),
                      dst=rec.get("dst"), size=fmt_size(rec.get("size", 0)))
        else:
            title = tr("migrate.msg.undo_confirm_title")
            body = tr("migrate.msg.undo_confirm", dst=rec.get("dst"))
        if not messagebox.askyesno(title, body):
            return
        self.busy = True
        self._set_running(True)
        self.progress.configure(value=0)
        self.progress_var.set("")
        self.runner.reset("migrate")

        def job(gen, ev, r=dict(rec), rb=is_rollback):
            def on_progress(copied, total, name):
                pct = int(copied * 100 / total) if total else 0
                self.runner.emit("migrate", gen, "progress",
                                 {"percent": pct, "text": name})

            if rb:
                ok, msg = rollback(
                    r, cancel=ev, on_progress=on_progress,
                    log=lambda m: self.runner.emit("migrate", gen, "log", m),
                    store=self.app.migrations)
                title = tr("migrate.rollback_title",
                           name=os.path.basename(r["src"].rstrip("\\/")))
            else:
                ok, msg = undo(
                    r, cancel=ev,
                    log=lambda m: self.runner.emit("migrate", gen, "log", m),
                    store=self.app.migrations)
                title = tr("migrate.undo_title")
            self.runner.emit("migrate", gen, "done", {
                "record": r, "ok": ok, "message": msg,
                "title": title, "undo": True})

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

    # ---------------- 目标盘与详情 ----------------

    def _init_drives(self):
        """探测实际存在的数据盘，避免让用户选到不存在的盘符。"""
        drives = []
        for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
            root = letter + ":\\"
            try:
                if os.path.isdir(root):
                    drives.append(letter + ":")
            except OSError:
                continue
        self.sw_drives = drives
        self.sw_drive_box.configure(values=drives)
        if drives:
            self.sw_target_var.set(drives[0])
            self._on_drive_change()
        else:
            self.sw_target_var.set("")
            self.sw_free_var.set(tr("sw.target.none"))

    def _target_root(self):
        drive = (self.sw_target_var.get() or "").strip()
        return drive.rstrip("\\/") + "\\Software" if drive else ""

    def _target_path_for(self, item):
        root = self._target_root()
        if not root:
            return ""
        return os.path.join(root, self._sanitize_target_name(item.name))

    def _on_drive_change(self):
        drive = (self.sw_target_var.get() or "").strip()
        if not drive:
            self.sw_free_var.set(tr("sw.target.none"))
            return
        try:
            free = shutil.disk_usage(drive + "\\").free
        except OSError:
            self.sw_free_var.set(tr("sw.target.unreadable"))
        else:
            self.sw_free_var.set(tr("sw.target_free", free=fmt_size(free)))
        self._refresh_sw_detail()

    # ---------------- 清单渲染 ----------------

    @staticmethod
    def _risk_label(item):
        return {RISK_FORBID: tr("sw.risk.forbid"),
                RISK_WARN: tr("sw.risk.warn")}.get(item.risk, tr("sw.risk.safe"))

    def _is_submitted(self, item):
        return os.path.normcase(os.path.abspath(item.install_dir_norm)) in self.submitted_srcs

    def _row_values(self, item):
        if item.risk == RISK_FORBID:
            check = "—"
        else:
            check = "☑" if item.checked else "☐"
        state = tr("sw.state.submitted") if self._is_submitted(item) else ""
        return (check, item.name, item.publisher or "—",
                fmt_size(item.effective_size), self._risk_label(item), state)

    @staticmethod
    def _row_tag(item):
        return {RISK_FORBID: "risk_forbid",
                RISK_WARN: "risk_warn"}.get(item.risk, "risk_safe")

    def _render_row(self, iid, item):
        self.sw_tree.item(iid, values=self._row_values(item))

    def _refresh_sw_rows(self):
        """记录表变化后刷新「已提交」标记。"""
        for iid, idx in list(self._row_index.items()):
            if idx < len(self.software_items) and self.sw_tree.exists(iid):
                self._render_row(iid, self.software_items[idx])

    # ---------------- 勾选交互 ----------------

    def _on_sw_click(self, event):
        """点在第一列（勾选框）就切换，点其他列保持默认行选中。"""
        if self.sw_tree.identify_region(event.x, event.y) != "cell":
            return None
        if self.sw_tree.identify_column(event.x) != "#1":
            return None
        row = self.sw_tree.identify_row(event.y)
        if row:
            self._toggle_row(row)
        return None

    def _on_sw_space(self, _event=None):
        sel = self.sw_tree.selection()
        if sel:
            self._toggle_row(sel[0])
        return "break"

    def _toggle_row(self, iid):
        idx = self._row_index.get(iid)
        if idx is None:
            return
        item = self.software_items[idx]
        if item.risk == RISK_FORBID:
            self.app.set_status(tr("sw.status.forbid_toggle"))
            return
        item.checked = not item.checked
        self._render_row(iid, item)
        self._refresh_sw_summary()
        self._show_detail(item)

    def _bulk_check(self, mode):
        """批量勾选：全部 / 全不选 / 仅可迁移。禁止项始终跳过。"""
        if not self.software_items:
            return
        for iid, idx in self._row_index.items():
            item = self.software_items[idx]
            if item.risk == RISK_FORBID:
                continue
            if mode == "all":
                item.checked = True
            elif mode == "none":
                item.checked = False
            else:
                item.checked = item.risk == RISK_SAFE
            self._render_row(iid, item)
        self._refresh_sw_summary()
        self._refresh_sw_detail()

    # ---------------- 详情面板 ----------------

    def _selected_item(self):
        sel = self.sw_tree.selection()
        if not sel:
            return None
        idx = self._row_index.get(sel[0])
        if idx is None or idx >= len(self.software_items):
            return None
        return self.software_items[idx]

    def _show_detail(self, item):
        target = self._target_path_for(item)
        exists = bool(target) and os.path.exists(target)
        lines = [
            "   ".join([
                tr("sw.detail.line", label=tr("sw.detail.version"),
                   value=item.version or "—"),
                tr("sw.detail.line", label=tr("sw.col.publisher"),
                   value=item.publisher or "—"),
                tr("sw.detail.line", label=tr("sw.col.size"),
                   value=fmt_size(item.effective_size)),
            ]),
            tr("sw.detail.line", label=tr("sw.col.dir"), value=item.install_dir_norm),
        ]
        if item.install_date:
            lines.append(tr("sw.detail.line", label=tr("sw.detail.installed"),
                            value=item.install_date))
        risk = self._risk_label(item)
        if item.reason_key:
            risk = "%s — %s" % (risk, tr(item.reason_key, hint=item.reason_hint))
        lines.append(tr("sw.detail.line", label=tr("sw.col.risk"), value=risk))
        lines.append(tr("sw.detail.line", label=tr("sw.detail.target"),
                        value=target or "—")
                     + (tr("sw.detail.exists") if exists else ""))
        if self._is_submitted(item):
            lines.append(tr("sw.detail.submitted"))
        self.sw_detail_var.set("\n".join(lines))
        self.sw_detail_label.configure(foreground={
            RISK_FORBID: theme.DANGER, RISK_WARN: theme.WARN}.get(item.risk, theme.TEXT))

    def _refresh_sw_detail(self):
        item = self._selected_item()
        if item is None:
            if self.software_items:
                self.sw_detail_var.set(tr("sw.detail.hint"))
            self.sw_detail_label.configure(foreground=theme.MUTED)
            return
        self._show_detail(item)

    def _refresh_sw_summary(self):
        """重算勾选数量与可释放体积，并联动提交按钮。"""
        if not self.software_items:
            return
        chosen = [it for it in self.software_items if it.checked]
        if not chosen:
            self.sw_summary_var.set(tr("sw.summary.empty_selected"))
            self.sw_submit_btn.state(["disabled"])
            return
        self.sw_summary_var.set(tr("sw.summary.selected",
                                   total=fmt_size(sum(i.effective_size for i in chosen)),
                                   count=len(chosen)))
        self.sw_submit_btn.state(["!disabled"])

    # ---------------- 扫描 ----------------

    def on_scan_software(self):
        """后台扫描注册表，找出 C 盘上可迁移的软件安装项。"""
        if self.busy:
            return
        if not self.sw_drives:
            self._init_drives()
        self.sw_scan_btn.state(["disabled"])
        self.sw_stop_btn.state(["!disabled"])
        self.sw_submit_btn.state(["disabled"])
        self.sw_summary_var.set(tr("sw.summary.scanning"))
        self.sw_detail_var.set(tr("sw.detail.scanning"))
        self.sw_detail_label.configure(foreground=theme.MUTED)
        self.software_items = []
        self._row_index = {}
        for iid in self.sw_tree.get_children():
            self.sw_tree.delete(iid)
        self.sw_tree.insert("", "end", iid="_scanning",
                            values=("", tr("sw.summary.scanning"), "", "", "", ""),
                            tags=("hint",))
        self.app.begin_progress(tr("sw.status.start"))
        self.runner.reset("sw_scan")

        def job(gen, ev):
            def on_progress(idx, total, name):
                if idx % 5 == 0:
                    self.runner.emit("sw_scan", gen, "sw_scan_progress",
                                     {"name": name, "done": idx, "total": total})

            items = scan_candidates(cancel=ev, measure_actual=True,
                                    on_progress=on_progress)
            self.runner.emit("sw_scan", gen, "sw_scan_done",
                             {"items": items, "cancelled": ev.is_set()})

        self.runner.submit("sw_scan", job, priority=PRIORITY_SCAN)

    def on_stop_software(self):
        self.runner.reset("sw_scan")
        self.app.end_progress()
        self.sw_summary_var.set(tr("sw.summary.stopped"))
        self.app.set_status(tr("sw.status.stopped"))
        self.sw_scan_btn.state(["!disabled"])
        self.sw_stop_btn.state(["disabled"])

    def _on_sw_scan_done(self, payload):
        self.sw_scan_btn.state(["!disabled"])
        self.sw_stop_btn.state(["disabled"])
        self.app.end_progress()
        items = payload.get("items", [])
        self.software_items = items
        self._row_index = {}
        for iid in self.sw_tree.get_children():
            self.sw_tree.delete(iid)
        for idx, item in enumerate(items):
            iid = "sw%d" % idx
            self._row_index[iid] = idx
            self.sw_tree.insert("", "end", iid=iid, values=self._row_values(item),
                                tags=(self._row_tag(item),))
        chosen = [it for it in items if it.checked]
        if payload.get("cancelled"):
            self.sw_summary_var.set(tr("sw.summary.partial", count=len(items)))
        elif not items:
            self.sw_summary_var.set(tr("sw.summary.none"))
        else:
            self.sw_summary_var.set(tr(
                "sw.summary.done", total=fmt_size(sum(i.effective_size for i in chosen)),
                count=len(chosen), total_count=len(items)))
        self.sw_submit_btn.state(["!disabled"] if chosen else ["disabled"])
        self.sw_detail_var.set(tr("sw.detail.hint"))
        self.sw_detail_label.configure(foreground=theme.MUTED)
        self.app.set_status(tr("sw.status.done", count=len(items)))

    # ---------- 批量提交 ----------

    def _sanitize_target_name(self, name: str) -> str:
        """从软件名生成合法的目标目录名。"""
        # 去掉盘符、反斜杠，只保留可打印字符
        base = os.path.basename(name.strip().rstrip("\\/"))
        # 去掉版本号和无意义后缀
        base = re.sub(r"\s*[-_\.]\s*(v?\d+[\d\.\-]*|Program|App)$", "", base, flags=re.IGNORECASE)
        # 把非字母数字替换为下划线
        base = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", base).strip("_")
        return base or "software"

    def on_batch_submit(self):
        """把勾选的软件批量生成迁移记录，并引导用户立即开始。"""
        checked = [it for it in self.software_items if it.checked]
        if not checked:
            messagebox.showinfo(tr("sw.msg.none_title"), tr("sw.msg.none"))
            return
        # 运行中的软件文件会被占用，复制必然失败，提交前直接拦截
        exes = running_executables()
        busy = [it for it in checked if executables_under(it.install_dir_norm, exes)]
        if busy:
            names = "\n".join("· %s" % it.name for it in busy[:10])
            messagebox.showwarning(tr("sw.msg.busy_title"),
                                   tr("sw.msg.busy", items=names))
            return
        root = self._target_root()
        if not root:
            messagebox.showwarning(tr("sw.msg.bad_drive_title"), tr("sw.target.none"))
            return
        try:
            # 先建好 <盘>:\Software，否则 validate 会因上级目录不存在而全部失败
            os.makedirs(root, exist_ok=True)
        except OSError as e:
            messagebox.showwarning(tr("sw.msg.bad_drive_title"),
                                   tr("sw.msg.bad_drive", drive=root) + "\n" + str(e))
            return

        records = []
        problems = []
        for item in checked:
            dst = os.path.join(root, self._sanitize_target_name(item.name))
            errs = validate(item.install_dir_norm, dst, item.effective_size)
            # 源目录本来就在 C 盘，validate 的「同盘」「系统目录」判定不适用于软件迁移
            errs = [e for e in errs
                    if not e.startswith("源目录与目标目录在同一个盘")
                    and not e.startswith("源目录属于系统关键目录")]
            if errs:
                problems.append((item.name, errs))
                continue
            records.append({"src": item.install_dir_norm, "dst": dst,
                            "stage": STAGE_PLANNED, "size": item.effective_size,
                            "files": 0, "software_name": item.name})

        if problems:
            body = "\n".join("• %s：%s" % (name, "；".join(errs[:2]))
                             for name, errs in problems[:10])
            if not records:
                messagebox.showwarning(tr("sw.msg.problem_all_title"),
                                       tr("sw.msg.problem_all") + "\n\n" + body)
                return
            if not messagebox.askyesno(
                    tr("sw.msg.problem_partial_title"),
                    tr("sw.msg.problem_partial") + "\n\n" + body + "\n\n"
                    + tr("sw.msg.confirm_partial", count=len(records))):
                return

        if not messagebox.askyesno(
                tr("sw.msg.batch_confirm_title"),
                tr("sw.msg.batch_confirm", count=len(records), drive=root,
                   size=fmt_size(sum(r["size"] for r in records)))):
            return

        # 逐条写入 store，让用户可在记录表中续跑/撤销
        for rec in records:
            self.app.migrations.upsert(rec)
        self.reload_records()
        self.app.set_status(tr("sw.msg.batch_submitted", count=len(records)))
        self.info_var.set(tr("sw.info.batch_submitted", count=len(records), drive=root))

        # 提交后切到「迁移记录」子页并选中首条，避免用户不知道下一步
        self.notebook.select(self.records_page)
        self._select_record_by_src(records[0]["src"])
        if messagebox.askyesno(tr("sw.msg.start_now_title"),
                               tr("sw.msg.start_now", count=len(records))):
            self.on_resume()

    def _select_record_by_src(self, src):
        want = os.path.normcase(os.path.abspath(src))
        for idx, rec in enumerate(self.records):
            if os.path.normcase(os.path.abspath(rec.get("src", ""))) == want:
                iid = str(idx)
                if self.tree.exists(iid):
                    self.tree.selection_set(iid)
                    self.tree.focus(iid)
                    self.tree.see(iid)
                break
