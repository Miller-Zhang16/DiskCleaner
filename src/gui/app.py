# -*- coding: utf-8 -*-
"""主窗口：磁盘概览、标签页容器、状态栏与日志面板，并统一调度后台任务。"""

import os
import shutil
import tkinter as tk
from tkinter import messagebox, ttk

from ..core.cleaner import PROTECTED_PATHS, default_skip_paths, delete_tree_contents, execute_target, unlink_file
from ..core.runtime import is_admin, relaunch_as_admin
from ..utils.fmt import fmt_size
from ..utils.taskrunner import LANE_BATCH, LANE_SCAN, PRIORITY_CLEAN, TaskRunner
from ..version import TITLE, VERSION
from .browse_tab import BrowseTab
from .large_files_tab import LargeFilesTab
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

        self.runner = TaskRunner(root)
        self.runner.error_sink = self.logger.warning

        self._build_ui()

        # 注册后台通道：浏览用 fast/scan 通道，估算与清理用 batch 通道
        self.runner.register("browse", self.browse_tab.handle, lane=LANE_SCAN)
        self.runner.register("large_files", self.large_files_tab.handle, lane=LANE_SCAN)
        self.runner.register("suggest", self.suggest_tab.handle, lane=LANE_BATCH)
        self.runner.register("clean", self.handle_clean, lane=LANE_BATCH)

        logger.set_ui_sink(self.log_line)
        logger.info("程序启动完成。版本 v%s，当前权限：%s"
                    % (VERSION, "管理员模式" if self.admin else "普通模式"))

        # 启动后异步加载：先加载目录树，再估算清理项空间
        root.after(200, self.browse_tab.load_root)
        root.after(600, self.suggest_tab.reestimate)

    # ---------------- 界面构建 ----------------

    def _build_ui(self):
        self.root.title(TITLE)
        self.root.geometry(self.config.window_geometry)
        self.root.minsize(900, 600)

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", rowheight=22)

        self._build_overview()

        bottom = ttk.Frame(self.root)
        bottom.pack(side="bottom", fill="x")
        self.progress = ttk.Progressbar(bottom, mode="indeterminate", length=150)
        self.progress.pack(side="left", padx=8, pady=4)
        self.status = ttk.Label(bottom, text="就绪", anchor="w")
        self.status.pack(side="left", fill="x", expand=True, padx=8)

        log_frame = ttk.LabelFrame(self.root, text="运行日志")
        log_frame.pack(side="bottom", fill="x", padx=8, pady=(0, 4))
        self.log_text = tk.Text(log_frame, height=6, wrap="none", state="disabled")
        self.log_text.pack(side="left", fill="both", expand=True)
        log_sb = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        log_sb.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=log_sb.set)

        notebook = ttk.Notebook(self.root)
        notebook.pack(side="top", fill="both", expand=True, padx=8, pady=8)

        self.browse_tab = BrowseTab(notebook, self.runner, self)
        self.large_files_tab = LargeFilesTab(notebook, self.runner, self)
        self.suggest_tab = SuggestTab(notebook, self.runner, self, self.targets)
        self.settings_tab = SettingsTab(notebook, self.runner, self)
        notebook.add(self.browse_tab, text="  磁盘浏览  ")
        notebook.add(self.large_files_tab, text="  大文件  ")
        notebook.add(self.suggest_tab, text="  清理建议  ")
        notebook.add(self.settings_tab, text="  设置  ")

    def _build_overview(self):
        top = ttk.LabelFrame(self.root, text="C 盘状态")
        top.pack(side="top", fill="x", padx=8, pady=(8, 0))

        bar = ttk.Frame(top)
        bar.pack(fill="x", padx=8, pady=(6, 2))
        self.disk_canvas = tk.Canvas(bar, height=26, highlightthickness=0,
                                     background="#f0f0f0")
        self.disk_canvas.pack(side="left", fill="x", expand=True)
        self.disk_canvas.bind("<Configure>", lambda _e: self._draw_disk())

        btn_bar = ttk.Frame(top)
        btn_bar.pack(fill="x", padx=8, pady=(2, 6))
        ttk.Button(btn_bar, text="刷新磁盘信息", command=self.refresh_disk).pack(side="left")
        ttk.Button(btn_bar, text="重新加载配置", command=self.reload_config).pack(side="left", padx=6)
        self.elev_btn = ttk.Button(btn_bar, text="以管理员身份重启", command=self.on_elevate)
        self.elev_btn.pack(side="left", padx=6)
        if self.admin:
            self.elev_btn.state(["disabled"])
        ttk.Label(btn_bar, foreground="#888",
                  text="日志：data/logs/diskcleaner.log").pack(side="right")

        self.disk_total = self.disk_used = self.disk_free = 0
        self.refresh_disk()

    # ---------------- 磁盘概览 ----------------

    def refresh_disk(self):
        try:
            total, used, free = shutil.disk_usage("C:\\")
        except OSError as e:
            self.logger.error("读取磁盘信息失败：%s" % e)
            return
        self.disk_total, self.disk_used, self.disk_free = total, used, free
        self._draw_disk()

    def _draw_disk(self):
        c = self.disk_canvas
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w <= 1:
            w, h = 700, 26
        total = self.disk_total or 1
        frac = max(0.0, min(1.0, self.disk_used / total))
        color = "#4caf50"
        if frac > 0.9:
            color = "#e53935"
        elif frac > 0.75:
            color = "#fb8c00"
        c.create_rectangle(0, 0, w, h, fill="#e0e0e0", outline="#c8c8c8")
        c.create_rectangle(0, 0, int(w * frac), h, fill=color, outline="")
        c.create_text(10, h // 2, anchor="w", fill="#1a1a1a",
                      text="已用 %s / %s  （%.0f%%）    可用 %s" % (
                          fmt_size(self.disk_used), fmt_size(self.disk_total),
                          frac * 100, fmt_size(self.disk_free)))

    # ---------------- 清理执行 ----------------

    def run_cleanup(self, selected):
        if self.running:
            messagebox.showinfo("请稍候", "已有清理任务正在执行。")
            return
        self.begin_busy()
        self.runner.submit(
            "clean", lambda g, ev, sel=list(selected): self._job_clean_targets(g, ev, sel),
            priority=PRIORITY_CLEAN)

    def _job_clean_targets(self, gen, ev, selected):
        total_freed = 0
        total_deleted = 0
        all_skipped = []
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
            if msg:
                self.runner.emit("clean", gen, "log", "  %s 提示：%s" % (t["name"], msg))
        self.runner.emit("clean", gen, "clean_done", {
            "freed": total_freed, "deleted": total_deleted, "skipped": all_skipped,
            "cancelled": ev.is_set(), "refresh": None, "title": "一键清理"})

    def run_delete(self, path, kind):
        """删除浏览页选中的单个文件/目录（需二次确认）。"""
        norm = os.path.normcase(os.path.abspath(path)).rstrip("\\")
        if norm in {p.rstrip("\\") for p in PROTECTED_PATHS}:
            messagebox.showwarning("已阻止", "该路径属于系统关键目录，禁止删除：\n%s" % path)
            return
        if kind == "dir":
            msg = "将删除该目录及其全部内容：\n%s" % path
        else:
            msg = "将删除该文件：\n%s" % path
        if not messagebox.askyesno("确认删除", msg + "\n\n此操作不可恢复，确定继续吗？"):
            return
        if self.running:
            messagebox.showinfo("请稍候", "已有清理任务正在执行。")
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
            "title": "删除 %s" % path})

    def handle_clean(self, kind, payload):
        if kind == "log":
            self.log_line(payload)
        elif kind == "clean_done":
            self.end_busy()
            self.skipped_total = payload["skipped"]
            lines = ["%s 完成。" % payload.get("title", "清理"),
                     "实际释放（估算）：%s，删除 %d 项"
                     % (fmt_size(payload["freed"]), payload["deleted"])]
            if payload["cancelled"]:
                lines.append("（任务被中断，结果可能不完整）")
            if payload["skipped"]:
                lines.append("跳过 %d 项（被占用或无权限），示例：" % len(payload["skipped"]))
                for sp, err in payload["skipped"][:5]:
                    lines.append("  - %s → %s" % (sp, err))
            self.logger.info("；".join(lines))
            messagebox.showinfo("清理结果", "\n".join(lines))
            if payload.get("refresh"):
                self.browse_tab.reload_node(payload["refresh"])
            self.suggest_tab.refresh_sizes()

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
        messagebox.showinfo("配置", "已重新加载配置文件。")

    def on_elevate(self):
        if self.admin:
            return
        ok, code = relaunch_as_admin()
        if ok:
            self.logger.info("已请求以管理员身份重新启动，正在退出当前进程…")
            self.root.after(300, self.root.destroy)
            return
        if code == "cancelled":
            messagebox.showinfo("已取消", "你取消了管理员授权，程序继续以普通模式运行。")
            self.logger.info("用户取消了提权请求。")
        elif code == "already":
            pass
        else:
            messagebox.showwarning("提权失败", "无法以管理员身份启动：%s" % code)
            self.logger.error("提权失败：%s" % code)

    # ---------------- 状态 / 日志 ----------------

    def begin_busy(self):
        self.running = True
        self.progress.start(60)

    def end_busy(self):
        self.running = False
        self.progress.stop()

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
