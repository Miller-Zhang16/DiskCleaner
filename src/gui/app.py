# -*- coding: utf-8 -*-
"""主窗口：磁盘概览、标签页容器、状态栏与日志面板，并统一调度后台任务。"""

import os
import shutil
import tkinter as tk
from tkinter import messagebox, ttk

from ..core.cleaner import PROTECTED_PATHS, default_skip_paths, delete_tree_contents, execute_target, unlink_file
from ..core.growth import GrowthStore
from ..core.history import History
from ..core.migrator import MigrationStore
from ..core.runtime import data_dir, is_admin, relaunch_as_admin
from ..utils.fmt import fmt_size
from ..utils.i18n import tr
from ..utils.taskrunner import LANE_BATCH, LANE_SCAN, PRIORITY_CLEAN, TaskRunner
from ..version import VERSION
from . import theme
from .browse_tab import BrowseTab
from .duplicates_tab import DuplicatesTab
from .history_dialog import HistoryDialog
from .large_files_tab import LargeFilesTab
from .migrate_tab import MigrateTab
from .result_dialog import ResultDialog
from .settings_tab import SettingsTab
from .suggest_tab import SuggestTab


class CleanupApp:
    """应用主窗口。"""

    def __init__(self, root, config, logger, targets):
        self.root = root
        self.config = config
        self.logger = logger
        self.targets = targets
        self.admin = is_admin()
        self.running = False
        self.skipped_total = []
        self.history = History(os.path.join(data_dir(), "history.jsonl"),
                              config.history_max_records)
        self.migrations = MigrationStore(os.path.join(data_dir(), "migrations.json"))
        self.growth = GrowthStore(os.path.join(data_dir(), "growth.json"))

        self.runner = TaskRunner(root)
        self.runner.error_sink = self.logger.warning

        self._build_ui()

        # 注册后台通道：浏览用 fast/scan 通道，估算与清理用 batch 通道
        self.runner.register("browse", self.browse_tab.handle, lane=LANE_SCAN)
        self.runner.register("large_files", self.large_files_tab.handle, lane=LANE_SCAN)
        self.runner.register("duplicates", self.duplicates_tab.handle, lane=LANE_SCAN)
        self.runner.register("suggest", self.suggest_tab.handle, lane=LANE_BATCH)
        self.runner.register("clean", self.handle_clean, lane=LANE_BATCH)
        self.runner.register("migrate", self.migrate_tab.handle, lane=LANE_BATCH)

        logger.set_ui_sink(self.log_line)
        logger.info("程序启动完成。版本 v%s，当前权限：%s"
                    % (VERSION, "管理员模式" if self.admin else "普通模式"))

        # 启动后异步加载：先加载目录树，再估算清理项空间
        root.after(200, self.browse_tab.load_root)
        root.after(600, self.suggest_tab.reestimate)

    # ---------------- 界面构建 ----------------

    def _build_ui(self):
        theme.apply(self.root)
        self.root.title(tr("app.title", version=VERSION))
        self.root.geometry(self.config.window_geometry)
        self.root.minsize(1000, 640)

        shell = tk.Frame(self.root, background=theme.BG)
        shell.pack(fill="both", expand=True)

        sidebar = tk.Frame(shell, background=theme.SIDEBAR, width=212)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        tk.Frame(shell, background=theme.BORDER, width=1).pack(side="left", fill="y")

        main = tk.Frame(shell, background=theme.BG)
        main.pack(side="left", fill="both", expand=True)

        self.current_tab = "browse"
        self._build_sidebar(sidebar)
        self._build_overview(main)
        self._build_status(main)
        self._build_log(main)

        self.content = tk.Frame(main, background=theme.BG)
        self.content.pack(fill="both", expand=True, padx=18, pady=(14, 0))
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)

        self.browse_tab = BrowseTab(self.content, self.runner, self)
        self.large_files_tab = LargeFilesTab(self.content, self.runner, self)
        self.duplicates_tab = DuplicatesTab(self.content, self.runner, self)
        self.suggest_tab = SuggestTab(self.content, self.runner, self, self.targets)
        self.migrate_tab = MigrateTab(self.content, self.runner, self)
        self.settings_tab = SettingsTab(self.content, self.runner, self)
        self.tabs = {
            "browse": self.browse_tab,
            "large_files": self.large_files_tab,
            "duplicates": self.duplicates_tab,
            "suggest": self.suggest_tab,
            "migrate": self.migrate_tab,
            "settings": self.settings_tab,
        }
        for tab in self.tabs.values():
            tab.grid(row=0, column=0, sticky="nsew")
        self.show_tab("browse")

    # ---------------- 左侧导航 ----------------

    def _build_sidebar(self, parent):
        brand = tk.Frame(parent, background=theme.SIDEBAR)
        brand.pack(fill="x", padx=18, pady=(22, 6))

        logo = tk.Canvas(brand, width=38, height=38, background=theme.SIDEBAR,
                        highlightthickness=0)
        logo.pack(side="left")
        logo.create_oval(0, 0, 38, 38, fill=theme.PRIMARY, outline="")
        logo.create_text(19, 19, text="C", fill="#FFFFFF", font=theme.font(15, True))

        title_box = tk.Frame(brand, background=theme.SIDEBAR)
        title_box.pack(side="left", padx=(10, 0))
        tk.Label(title_box, text=tr("app.brand"), background=theme.SIDEBAR,
                 foreground=theme.TEXT, font=theme.font(12, True),
                 anchor="w").pack(fill="x")
        tk.Label(title_box, text=tr("app.brand_sub", version=VERSION),
                 background=theme.SIDEBAR, foreground=theme.MUTED,
                 font=theme.font(9), anchor="w").pack(fill="x")

        tk.Label(parent, text=tr("app.nav.section"), background=theme.SIDEBAR,
                 foreground=theme.FAINT, font=theme.font(9),
                 anchor="w").pack(fill="x", padx=20, pady=(18, 4))

        self.nav_items = {}
        for key, icon in (("browse", "▤"), ("large_files", "▥"),
                          ("duplicates", "⧉"), ("suggest", "✦"),
                          ("migrate", "⇄"), ("settings", "⚙")):
            self._nav_item(parent, key, icon, tr("app.tab." + key).strip())

    def _nav_item(self, parent, key, icon, text):
        item = tk.Frame(parent, background=theme.SIDEBAR, cursor="hand2")
        item.pack(fill="x", padx=10, pady=1)
        accent = tk.Frame(item, background=theme.SIDEBAR, width=3)
        accent.pack(side="left", fill="y")
        icon_lbl = tk.Label(item, text=icon, background=theme.SIDEBAR,
                            foreground=theme.MUTED, font=theme.font(12),
                            width=3, cursor="hand2")
        icon_lbl.pack(side="left", padx=(6, 0))
        text_lbl = tk.Label(item, text=text, background=theme.SIDEBAR,
                            foreground=theme.TEXT, font=theme.font(10),
                            anchor="w", cursor="hand2")
        text_lbl.pack(side="left", fill="x", expand=True, pady=10)

        for w in (item, icon_lbl, text_lbl):
            w.bind("<Button-1>", lambda _e, k=key: self.show_tab(k))
            w.bind("<Enter>", lambda _e, k=key: self._nav_hover(k, True))
            w.bind("<Leave>", lambda _e, k=key: self._nav_hover(k, False))
        self.nav_items[key] = {"frame": item, "accent": accent,
                               "icon": icon_lbl, "text": text_lbl}

    def _nav_hover(self, key, entering):
        if key == self.current_tab:
            return
        bg = theme.NEUTRAL_BG if entering else theme.SIDEBAR
        it = self.nav_items[key]
        it["frame"].configure(background=bg)
        it["icon"].configure(background=bg)
        it["text"].configure(background=bg)

    def show_tab(self, key):
        """切换右侧内容区，并同步导航高亮。"""
        if key not in self.tabs:
            return
        self.current_tab = key
        self.tabs[key].tkraise()
        for k, it in self.nav_items.items():
            active = k == key
            bg = theme.PRIMARY_SOFT if active else theme.SIDEBAR
            it["frame"].configure(background=bg)
            it["icon"].configure(background=bg, foreground=(
                theme.PRIMARY if active else theme.MUTED))
            it["text"].configure(background=bg, foreground=(
                theme.PRIMARY_DARK if active else theme.TEXT))
            it["accent"].configure(
                background=theme.PRIMARY if active else theme.SIDEBAR)

    # ---------------- 磁盘概览 ----------------

    def _build_overview(self, parent):
        outer = tk.Frame(parent, background=theme.BG)
        outer.pack(side="top", fill="x", padx=18, pady=(16, 0))
        card = theme.card(outer)
        card.pack(fill="x")
        inner = tk.Frame(card, background=theme.CARD)
        inner.pack(fill="x", padx=18, pady=(14, 16))

        head = tk.Frame(inner, background=theme.CARD)
        head.pack(fill="x")
        tk.Label(head, text=tr("app.disk_title"), background=theme.CARD,
                 foreground=theme.TEXT, font=theme.font(13, True)).pack(side="left")

        mode_text = tr("app.mode.admin") if self.admin else tr("app.mode.normal")
        mode_bg = theme.SUCCESS_BG if self.admin else theme.NEUTRAL_BG
        mode_fg = theme.SUCCESS if self.admin else theme.MUTED
        tk.Label(head, text=mode_text, background=mode_bg, foreground=mode_fg,
                 font=theme.font(9), padx=8, pady=2).pack(side="left", padx=10)

        self.elev_btn = ttk.Button(head, text=tr("app.btn.elevate"),
                                   style="Ghost.TButton", command=self.on_elevate)
        self.elev_btn.pack(side="right", padx=(8, 0))
        ttk.Button(head, text=tr("app.btn.reload_config"), style="Ghost.TButton",
                   command=self.reload_config).pack(side="right", padx=(8, 0))
        ttk.Button(head, text=tr("app.btn.refresh_disk"), style="Accent.TButton",
                   command=self.refresh_disk).pack(side="right")
        if self.admin:
            self.elev_btn.state(["disabled"])

        stats = tk.Frame(inner, background=theme.CARD)
        stats.pack(fill="x", pady=(16, 0))
        for col in (0, 2, 4, 6):
            stats.columnconfigure(col, weight=1)

        self.stat_vars = {}
        for idx, (key, label) in enumerate((
                ("used", tr("app.stat.used")),
                ("free", tr("app.stat.free")),
                ("total", tr("app.stat.total")),
                ("percent", tr("app.stat.percent")))):
            block = tk.Frame(stats, background=theme.CARD)
            block.grid(row=0, column=idx * 2, sticky="ew")
            tk.Label(block, text=label, background=theme.CARD,
                     foreground=theme.MUTED, font=theme.font(9),
                     anchor="w").pack(fill="x")
            var = tk.StringVar(value="—")
            self.stat_vars[key] = var
            tk.Label(block, textvariable=var, background=theme.CARD,
                     foreground=theme.TEXT, font=theme.font(17, True),
                     anchor="w").pack(fill="x", pady=(2, 0))
            if idx < 3:
                tk.Frame(stats, background=theme.BORDER, width=1).grid(
                    row=0, column=idx * 2 + 1, sticky="ns", padx=14)

        self.disk_canvas = tk.Canvas(inner, height=10, background=theme.CARD,
                                     highlightthickness=0)
        self.disk_canvas.pack(fill="x", pady=(16, 0))
        self.disk_canvas.bind("<Configure>", lambda _e: self._draw_disk())

        self.disk_text = tk.Label(inner, background=theme.CARD,
                                  foreground=theme.MUTED, font=theme.font(9),
                                  anchor="w")
        self.disk_text.pack(fill="x", pady=(6, 0))

        self.growth_label = tk.Label(inner, background=theme.CARD,
                                     foreground=theme.FAINT, font=theme.font(9),
                                     anchor="w")
        self.growth_label.pack(fill="x", pady=(2, 0))
        tk.Label(inner, text=tr("app.log_path"), background=theme.CARD,
                 foreground=theme.FAINT, font=theme.font(9),
                 anchor="e").pack(fill="x", pady=(2, 0))

        self.disk_total = self.disk_used = self.disk_free = 0
        self.refresh_disk()

    # ---------------- 底部状态栏 / 日志 ----------------

    def _build_status(self, parent):
        wrap = tk.Frame(parent, background=theme.BG)
        wrap.pack(side="bottom", fill="x", padx=18, pady=(0, 12))
        tk.Frame(wrap, background=theme.BORDER, height=1).pack(fill="x")
        bar = tk.Frame(wrap, background=theme.BG)
        bar.pack(fill="x", pady=(7, 0))

        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=130)
        self.status = ttk.Label(bar, text=tr("app.status.ready"),
                                style="Muted.TLabel", anchor="w")
        self.status.pack(side="left", fill="x", expand=True, padx=10)

        self.log_btn = ttk.Button(bar, text=tr("app.btn.log_show"),
                                  style="Ghost.TButton", command=self.toggle_log)
        self.log_btn.pack(side="right")

    def _build_log(self, parent):
        self.log_visible = False
        self.log_wrap = tk.Frame(parent, background=theme.BG)
        card = theme.card(self.log_wrap)
        card.pack(fill="x")

        head = tk.Frame(card, background=theme.CARD)
        head.pack(fill="x", padx=12, pady=(8, 0))
        tk.Label(head, text=tr("app.log_frame"), background=theme.CARD,
                 foreground=theme.TEXT, font=theme.font(10, True)).pack(side="left")

        body = tk.Frame(card, background=theme.CARD)
        body.pack(fill="x", padx=12, pady=(4, 10))
        self.log_text = tk.Text(body, height=6, wrap="none", state="disabled",
                                background=theme.CARD, foreground=theme.MUTED,
                                relief="flat", borderwidth=0, highlightthickness=0,
                                font=theme.font(9), padx=0, pady=2)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_sb = ttk.Scrollbar(body, orient="vertical",
                               command=self.log_text.yview)
        log_sb.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=log_sb.set)

    def toggle_log(self, show=None):
        """折叠 / 展开底部运行日志。"""
        if show is None:
            show = not self.log_visible
        self.log_visible = show
        if show:
            # before=content：让日志面板优先获得高度，内容区自动收缩
            self.log_wrap.pack(side="bottom", fill="x", padx=18, pady=(0, 6),
                               before=self.content)
            self.log_btn.configure(text=tr("app.btn.log_hide"))
            self.log_text.see("end")
        else:
            self.log_wrap.pack_forget()
            self.log_btn.configure(text=tr("app.btn.log_show"))

    # ---------------- 磁盘概览数据 ----------------

    def refresh_disk(self):
        try:
            total, used, free = shutil.disk_usage("C:\\")
        except OSError as e:
            self.logger.error("读取磁盘信息失败：%s" % e)
            return
        self.disk_total, self.disk_used, self.disk_free = total, used, free
        percent = (used / total * 100) if total else 0
        self.stat_vars["used"].set(fmt_size(used))
        self.stat_vars["free"].set(fmt_size(free))
        self.stat_vars["total"].set(fmt_size(total))
        self.stat_vars["percent"].set("%.0f%%" % percent)
        self.disk_text.configure(text=tr(
            "app.disk_usage", used=fmt_size(used), total=fmt_size(total),
            percent="%.0f" % percent, free=fmt_size(free)))
        self._draw_disk()
        self._update_growth(self.growth.record(total, used))

    def _update_growth(self, stats):
        """把趋势统计转成一行提示（数据不足 2 天时只显示「正在记录」）。"""
        delta = stats.get("daily_delta")
        if delta is None:
            text = tr("app.growth.collecting")
        elif delta <= 0:
            text = tr("app.growth.stable", span=stats["days"],
                      free=fmt_size(stats["free"]))
        else:
            text = tr("app.growth.rising", span=stats["days"],
                      size=fmt_size(int(round(delta))),
                      days_left=max(1, stats["days_left"] or 1))
        self.growth_label.configure(text=text)

    def _draw_disk(self):
        c = self.disk_canvas
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w <= 1:
            w = 700
        if h <= 1:
            h = 10
        frac = max(0.0, min(1.0, self.disk_used / (self.disk_total or 1)))
        color = theme.PRIMARY
        if frac > 0.9:
            color = theme.DANGER
        elif frac > 0.75:
            color = theme.WARN
        r = min(h / 2.0, 5.0)
        self._round_rect(c, 0, 0, w, h, r, theme.BORDER)
        if frac > 0:
            self._round_rect(c, 0, 0, max(w * frac, 2 * r), h, r, color)

    @staticmethod
    def _round_rect(canvas, x1, y1, x2, y2, r, fill):
        """用两个椭圆 + 矩形拼出圆角条，避免引入第三方绘图库。"""
        r = max(1.0, min(r, (x2 - x1) / 2.0, (y2 - y1) / 2.0))
        canvas.create_oval(x1, y1, x1 + 2 * r, y2, fill=fill, outline="")
        canvas.create_oval(x2 - 2 * r, y1, x2, y2, fill=fill, outline="")
        canvas.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline="")

    # ---------------- 清理执行 ----------------

    def run_cleanup(self, selected):
        if self.running:
            messagebox.showinfo(tr("app.msg.busy_title"), tr("app.msg.busy"))
            return
        self.begin_busy()
        self.runner.submit(
            "clean", lambda g, ev, sel=list(selected): self._job_clean_targets(g, ev, sel),
            priority=PRIORITY_CLEAN)

    def _job_clean_targets(self, gen, ev, selected):
        total_freed = 0
        total_deleted = 0
        all_skipped = []
        results = []
        for t in selected:
            if ev.is_set():
                break
            self.runner.emit("clean", gen, "log", "开始清理：%s …" % t["name"])

            def logln(msg, g=gen):
                self.runner.emit("clean", g, "log", msg)

            freed, deleted, skipped, msg = execute_target(
                t, cancel=ev, log=logln, skip_paths=default_skip_paths())
            total_freed += freed
            total_deleted += deleted
            all_skipped.extend(skipped)
            results.append({
                "name": t["name"], "freed": freed,
                "deleted": deleted, "skipped": len(skipped)})
            if msg:
                self.runner.emit("clean", gen, "log", "  %s 提示：%s" % (t["name"], msg))
        self.runner.emit("clean", gen, "clean_done", {
            "freed": total_freed, "deleted": total_deleted, "skipped": all_skipped,
            "cancelled": ev.is_set(), "refresh": None, "title": tr("app.clean_title"),
            "results": results})

    def run_delete(self, path, kind):
        """删除浏览页选中的单个文件/目录（需二次确认）。"""
        norm = os.path.normcase(os.path.abspath(path)).rstrip("\\")
        if norm in {p.rstrip("\\") for p in PROTECTED_PATHS}:
            messagebox.showwarning(tr("app.msg.blocked_title"),
                                   tr("app.msg.blocked", path=path))
            return
        if kind == "dir":
            msg = tr("app.msg.confirm_delete_dir", path=path)
        else:
            msg = tr("app.msg.confirm_delete_file", path=path)
        if not messagebox.askyesno(tr("app.msg.confirm_delete"),
                                   msg + tr("app.msg.confirm_delete_notice")):
            return
        if self.running:
            messagebox.showinfo(tr("app.msg.busy_title"), tr("app.msg.busy"))
            return
        self.begin_busy()
        parent = os.path.dirname(path) or "C:\\"
        self.runner.submit(
            "clean", lambda g, ev, p=path, k=kind, pa=parent:
            self._job_delete_path(g, ev, p, k, pa),
            priority=PRIORITY_CLEAN)

    def _job_delete_path(self, gen, ev, path, kind, parent):
        if kind == "dir":
            freed, deleted, skipped, _ = delete_tree_contents(
                path, cancel=ev, skip_paths=default_skip_paths())
            try:
                os.rmdir(path)
            except OSError:
                pass
        else:
            size, err = unlink_file(path)
            freed = size or 0
            deleted = 1 if err is None else 0
            skipped = [] if err is None else [(path, err)]
        self.runner.emit("clean", gen, "clean_done", {
            "freed": freed, "deleted": deleted, "skipped": skipped,
            "cancelled": ev.is_set(), "refresh": parent,
            "title": tr("app.title.delete", path=path),
            "results": [{"name": path, "freed": freed,
                         "deleted": deleted, "skipped": len(skipped)}]})

    def run_delete_many(self, paths, title, on_done=None):
        """批量删除一组文件（重复文件页使用），复用清理通道与历史记录。"""
        if not paths:
            return
        if self.running:
            messagebox.showinfo(tr("app.msg.busy_title"), tr("app.msg.busy"))
            return
        self.begin_busy()
        self.runner.submit(
            "clean", lambda g, ev, ps=list(paths), t=title, cb=on_done:
            self._job_delete_many(g, ev, ps, t, cb),
            priority=PRIORITY_CLEAN)

    def _job_delete_many(self, gen, ev, paths, title, on_done):
        freed = 0
        deleted = 0
        skipped = []
        for path in paths:
            if ev.is_set():
                break
            size, err = unlink_file(path)
            if err is None:
                freed += size or 0
                deleted += 1
            else:
                skipped.append((path, err))
        self.runner.emit("clean", gen, "clean_done", {
            "freed": freed, "deleted": deleted, "skipped": skipped,
            "cancelled": ev.is_set(), "refresh": None, "title": title,
            "results": [{"name": title, "freed": freed,
                         "deleted": deleted, "skipped": len(skipped)}],
            "on_done": on_done})

    def handle_clean(self, kind, payload):
        if kind == "log":
            self.log_line(payload)
        elif kind == "clean_done":
            self.end_busy()
            self.skipped_total = payload["skipped"]

            # 写入清理历史（辅助功能，失败不影响结果展示）
            self.history.append({
                "title": payload.get("title", tr("app.clean_title")),
                "freed": payload["freed"],
                "deleted": payload["deleted"],
                "skipped": len(payload["skipped"]),
                "cancelled": payload["cancelled"],
                "results": payload.get("results", []),
                # 只存前 50 条失败项，避免历史文件膨胀
                "failures": [{"path": p, "error": str(e)}
                             for p, e in payload["skipped"][:50]],
            })

            lines = ["%s 完成。" % payload.get("title", "清理"),
                     "实际释放（估算）：%s，删除 %d 项"
                     % (fmt_size(payload["freed"]), payload["deleted"])]
            if payload["cancelled"]:
                lines.append("（任务被中断，结果可能不完整）")
            if payload["skipped"]:
                lines.append("跳过 %d 项（被占用或无权限）" % len(payload["skipped"]))
            self.logger.info("；".join(lines))

            # 退出前展示结果与失败明细（可逐项核对路径与原因）
            ResultDialog(self, payload, on_history=self.show_history)
            if payload.get("refresh"):
                self.browse_tab.reload_node(payload["refresh"])
            self.suggest_tab.refresh_sizes()
            callback = payload.get("on_done")
            if callable(callback):
                try:
                    callback(payload)
                except Exception as e:  # noqa: BLE001
                    self.logger.warning("清理后回调失败：%s" % e)

    def show_history(self):
        """打开清理历史窗口。"""
        HistoryDialog(self)

    # ---------------- 配置 / 提权 ----------------

    def reload_config(self):
        """重新从 settings.ini 载入配置并同步清理项勾选状态。"""
        self.config.reload()
        for t in self.targets:
            t["_checked"] = self.config.target_default(t["key"], t.get("default", False))
        self.suggest_tab.refresh_rows()
        self.settings_tab.load()
        self.refresh_disk()
        self.logger.info("已重新加载配置：%s" % self.config.path)
        messagebox.showinfo(tr("app.msg.config_title"), tr("app.msg.config_reloaded"))

    def on_elevate(self):
        if self.admin:
            return
        ok, code = relaunch_as_admin()
        if ok:
            self.logger.info("已请求以管理员身份重新启动，正在退出当前进程…")
            self.root.after(300, self.root.destroy)
            return
        if code == "cancelled":
            messagebox.showinfo(tr("app.msg.elevate_cancelled_title"),
                                tr("app.msg.elevate_cancelled"))
            self.logger.info("用户取消了提权请求。")
        elif code == "already":
            pass
        else:
            messagebox.showwarning(tr("app.msg.elevate_failed_title"),
                                   tr("app.msg.elevate_failed", code=code))
            self.logger.error("提权失败：%s" % code)

    # ---------------- 状态 / 日志 ----------------

    def begin_busy(self):
        self.running = True
        self.progress.pack(side="left", before=self.status)
        self.progress.start(60)

    def end_busy(self):
        self.running = False
        self.progress.stop()
        self.progress.pack_forget()

    def set_status(self, text):
        self.status.configure(text=text)

    def log_line(self, text):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", str(text).rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    @staticmethod
    def _geometry_valid(geometry):
        """窗口几何是否值得持久化。

        异常退出或未显示的窗口可能报告 1x1 这类尺寸，写入配置会让
        用户下次启动时窗口异常，因此只保存不小于最小尺寸的值。
        """
        try:
            size = geometry.split("+")[0]
            width, height = (int(v) for v in size.split("x"))
        except (AttributeError, ValueError):
            return False
        return width >= 900 and height >= 600

    def on_close(self):
        try:
            geometry = self.root.geometry()
            if self._geometry_valid(geometry):
                self.config.set_window_geometry(geometry)
            self.config.save()
        except Exception:  # noqa: BLE001
            pass
        self.logger.info("程序退出。")
        self.runner.stop()
        self.root.destroy()
