# -*- coding: utf-8 -*-
"""磁盘浏览页：树形懒加载查看各目录/文件占用大小。

交互约定：
    - 展开某目录时才读取其子项，并对前 ``auto_size_limit`` 个子目录异步计算大小；
    - 单击「大小」列可对任意目录按需计算大小；
    - 右键菜单：打开位置 / 计算大小 / 删除此项 / 复制路径；
    - 通过队列回传结果，界面永不因磁盘 IO 卡死。
"""

import os
import tkinter as tk
from tkinter import messagebox, ttk

from ..core.classify import CATEGORY_COLORS, classify
from ..core.scanner import list_dir_children, scan_dir_size
from ..utils.fmt import dir_of, fmt_size
from ..utils.taskrunner import (LANE_FAST, LANE_SCAN,
                                PRIORITY_LIST, PRIORITY_SCAN)


class BrowseTab(ttk.Frame):
    """磁盘浏览页。"""

    def __init__(self, master, runner, app):
        super().__init__(master)
        self.runner = runner
        self.app = app

        self.node_kind = {}    # iid(路径) -> "dir" / "file" / "link"
        self.node_state = {}   # iid -> "new" / "loading" / "loaded"
        self._ph_seq = 0
        self._root_path = "C:\\"

        self._build()

    # ---------------- 构建界面 ----------------

    def _build(self):
        hint = ttk.Frame(self)
        hint.pack(fill="x", padx=6, pady=(6, 2))
        ttk.Label(
            hint, foreground="#555",
            text="展开目录逐级查看占用；目录大小按需计算（受扫描预算限制，显示“≥”表示估算下界）。"
                 "右键可打开位置 / 计算大小 / 删除所选。").pack(side="left")

        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True, padx=6, pady=6)

        cols = ("size", "type", "category")
        self.tree = ttk.Treeview(wrap, columns=cols, show="tree headings",
                                 selectmode="browse")
        self.tree.heading("#0", text="名称")
        self.tree.heading("size", text="大小")
        self.tree.heading("type", text="类型")
        self.tree.heading("category", text="分类")
        self.tree.column("#0", width=420, anchor="w")
        self.tree.column("size", width=130, anchor="e")
        self.tree.column("type", width=70, anchor="center")
        self.tree.column("category", width=100, anchor="center")

        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(wrap, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        for cat, color in CATEGORY_COLORS.items():
            self.tree.tag_configure("cat_" + cat, background=color)
        self.tree.tag_configure("link", foreground="#8a6d00")

        self.tree.bind("<<TreeviewOpen>>", self._on_open)
        self.tree.bind("<Button-3>", self._on_right_click)
        self.tree.bind("<ButtonRelease-1>", self._on_click)

        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="在资源管理器中打开位置", command=self._open_location)
        self.menu.add_command(label="计算该项大小", command=self._calc_size)
        self.menu.add_separator()
        self.menu.add_command(label="删除此项…", command=self._delete_selected)
        self.menu.add_command(label="复制完整路径", command=self._copy_path)

    # ---------------- 载入根节点 ----------------

    def load_root(self):
        """插入 C:\\ 根节点并异步读取其子项。"""
        root_path = self._root_path
        if self.tree.exists(root_path):
            return
        self.tree.insert("", "end", iid=root_path, text=root_path,
                         values=("计算中…", "目录", "系统文件"),
                         tags=("cat_系统文件",), open=False)
        self.node_kind[root_path] = "dir"
        self.node_state[root_path] = "loading"
        self._insert_placeholder(root_path)
        self._submit_list(root_path)

    # ---------------- 任务 ----------------

    def _submit_list(self, path):
        self.runner.submit("browse",
                           lambda g, ev, p=path: self._job_list(g, ev, p),
                           priority=PRIORITY_LIST, lane=LANE_FAST)

    def _job_list(self, gen, ev, parent_iid):
        dirs, files = list_dir_children(parent_iid)
        self.runner.emit("browse", gen, "children", (parent_iid, dirs, files))

    def _submit_size(self, path):
        def job(gen, ev, p=path):
            budget_s = self.app.config.scan_budget_seconds
            budget_e = self.app.config.scan_budget_entries
            b, trunc, _ = scan_dir_size(p, budget_seconds=budget_s,
                                        budget_entries=budget_e, cancel=ev)
            self.runner.emit("browse", gen, "size", (p, b, trunc))
        self.runner.submit("browse", job, priority=PRIORITY_SCAN, lane=LANE_SCAN)

    # ---------------- 结果处理 ----------------

    def handle(self, kind, payload):
        if kind == "children":
            self._on_children(payload)
        elif kind == "size":
            self._on_size(payload)
        elif kind == "log":
            self.app.logger.warning(payload)

    def _on_children(self, payload):
        parent_iid, dirs, files = payload
        self._remove_placeholder(parent_iid)
        self.node_state[parent_iid] = "loaded"
        limit = self.app.config.auto_size_limit
        queued = 0
        for name, full, _size, link in dirs:
            self._insert_entry(parent_iid, name, full, "dir", None, link)
            if not link and queued < limit:
                self._submit_size(full)
                queued += 1
        for name, full, size, link in files:
            self._insert_entry(parent_iid, name, full, "file", size, link)
        if queued:
            self.app.set_status("正在计算 %d 个子目录大小…" % queued)
        else:
            self.app.set_status("目录 %s 读取完成" % parent_iid)

    def _on_size(self, payload):
        iid, size, trunc = payload
        if not self.tree.exists(iid):
            return
        values = list(self.tree.item(iid, "values"))
        if not values:
            return
        values[0] = fmt_size(size) + (" ≥" if trunc else "")
        self.tree.item(iid, values=values)
        self.app.set_status("目录大小更新：%s = %s" % (iid, values[0]))

    # ---------------- 节点操作 ----------------

    def _insert_placeholder(self, parent_iid):
        # Tcl 字符串不能含 NUL，因此使用合成 iid 而不是拼接路径
        self._ph_seq += 1
        ph = "__placeholder_%d__" % self._ph_seq
        self.tree.insert(parent_iid, "end", iid=ph, text="正在读取…")

    def _remove_placeholder(self, parent_iid):
        for child in self.tree.get_children(parent_iid):
            if child.startswith("__placeholder_"):
                self.tree.delete(child)

    def _insert_entry(self, parent_iid, name, full, kind, size, link):
        if link:
            # 重解析点：只展示，不深入、不算大小、不可展开
            size_str = fmt_size(size) if size is not None else "—"
            self.tree.insert(parent_iid, "end", iid=full, text=name,
                             values=(size_str, "链接", "其他"), tags=("link",))
            self.node_kind[full] = "link"
            self.node_state[full] = "loaded"
            return

        category = classify(full)
        if kind == "dir":
            self.tree.insert(parent_iid, "end", iid=full, text=name,
                             values=("计算中…", "目录", category),
                             tags=("cat_" + category,))
            self.node_kind[full] = "dir"
            self.node_state[full] = "new"
            self._insert_placeholder(full)
        else:
            self.tree.insert(parent_iid, "end", iid=full, text=name,
                             values=(fmt_size(size), "文件", category),
                             tags=("cat_" + category,))
            self.node_kind[full] = "file"
            self.node_state[full] = "loaded"

    def reload_node(self, path):
        """清空并重新读取某个目录节点。"""
        if not self.tree.exists(path):
            return
        for child in self.tree.get_children(path):
            self.tree.delete(child)
        self.node_state[path] = "loading"
        self._insert_placeholder(path)
        self.tree.item(path, open=True)
        self._submit_list(path)

    # ---------------- 交互 ----------------

    def _on_open(self, _event=None):
        iid = self.tree.focus()
        if not iid:
            return
        if self.node_state.get(iid) in ("loaded", "loading"):
            return
        if self.node_kind.get(iid) != "dir":
            return
        self.node_state[iid] = "loading"
        self._submit_list(iid)

    def _on_click(self, event):
        if self.tree.identify_column(event.x) != "#1":
            return
        iid = self.tree.identify_row(event.y)
        if not iid or self.node_kind.get(iid) != "dir":
            return
        values = list(self.tree.item(iid, "values"))
        if values and values[0] == "计算中…":
            return  # 已在队列中
        values[0] = "计算中…"
        self.tree.item(iid, values=values)
        self._submit_size(iid)

    def _on_right_click(self, event):
        iid = self.tree.identify_row(event.y)
        if iid:
            self.tree.selection_set(iid)
            self.tree.focus(iid)
            self.menu.tk_popup(event.x_root, event.y_root)

    def _selected_path(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

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

    def _calc_size(self):
        path = self._selected_path()
        if not path or self.node_kind.get(path) != "dir":
            return
        values = list(self.tree.item(path, "values"))
        values[0] = "计算中…"
        self.tree.item(path, values=values)
        self._submit_size(path)

    def _delete_selected(self):
        path = self._selected_path()
        if not path:
            return
        self.app.run_delete(path, self.node_kind.get(path) or "file")
