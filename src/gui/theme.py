# -*- coding: utf-8 -*-
"""统一视觉主题：调色板、字体、ttk 样式与卡片辅助。

设计取舍：
    - 只使用 tkinter/ttk 自带能力（clam 主题 + 样式配置 + Canvas 绘制），
      不引入任何第三方 UI 依赖，保持「零运行时依赖」的交付约束；
    - 颜色集中在此模块，界面代码不再散落硬编码色值；
    - 卡片用 tk.Frame + 1px 细边框模拟，表格与按钮统一蓝灰配色。
"""

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# ---------------- 调色板 ----------------

BG = "#F4F6FB"          # 应用底色
CARD = "#FFFFFF"        # 卡片底色
BORDER = "#E4E9F2"      # 细边框
TEXT = "#1F2937"        # 主文字
MUTED = "#6B7280"       # 次要文字
FAINT = "#9AA5B4"       # 禁用文字

PRIMARY = "#2563EB"     # 主色（操作按钮 / 进度条）
PRIMARY_DARK = "#1D4ED8"
PRIMARY_SOFT = "#DBEAFE"  # 选中 / 悬停浅底

SUCCESS = "#059669"
SUCCESS_BG = "#ECFDF5"
WARN = "#B45309"
WARN_BG = "#FEF3C7"
DANGER = "#DC2626"
DANGER_BG = "#FEE2E2"
NEUTRAL_BG = "#F1F5F9"

SIDEBAR = "#FFFFFF"

FAMILY = "Segoe UI"     # 由 apply() 按系统可用字体覆盖


def font(size=10, bold=False):
    """返回与主题一致的字体元组，供 ttk 样式与 tk 控件共用。"""
    return (FAMILY, size, "bold") if bold else (FAMILY, size)


def _pick_family(root):
    families = set(tkfont.families(root))
    for name in ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "Arial"):
        if name in families:
            return name
    return "TkDefaultFont"


def card(parent):
    """白色卡片容器：1px 边框 + 单行留白由调用方控制。"""
    return tk.Frame(parent, background=CARD, bd=0,
                    highlightbackground=BORDER, highlightthickness=1)


def autowrap(label, margin=6):
    """让长说明文字随控件宽度自动换行，避免窗口变窄时右侧被裁切。"""
    def _on_config(event):
        label.configure(wraplength=max(240, event.width - margin))

    label.bind("<Configure>", _on_config)
    return label


def apply(root):
    """安装全局主题；必须在构建界面之前调用。"""
    global FAMILY
    FAMILY = _pick_family(root)
    root.configure(background=BG)

    # 下拉框弹出列表由经典 Tk 绘制，需要单独设定配色
    root.option_add("*TCombobox*Listbox.background", CARD)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", PRIMARY_SOFT)
    root.option_add("*TCombobox*Listbox.selectForeground", PRIMARY_DARK)
    root.option_add("*TCombobox*Listbox.font", font(10))

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", font=font(10), background=BG, foreground=TEXT,
                    bordercolor=BORDER, focuscolor=PRIMARY,
                    lightcolor=CARD, darkcolor=BORDER)
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=CARD)
    style.configure("Card.TLabel", background=CARD, foreground=TEXT)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED)
    style.configure("CardMuted.TLabel", background=CARD, foreground=MUTED)
    style.configure("Title.TLabel", background=CARD, foreground=TEXT,
                    font=font(13, bold=True))
    style.configure("Stat.TLabel", background=CARD, foreground=TEXT,
                    font=font(18, bold=True))

    # 按钮：默认是白底次级按钮，Accent 为主操作，Ghost 为文字型操作
    style.configure("TButton", background=CARD, foreground=TEXT,
                    bordercolor=BORDER, lightcolor=CARD, darkcolor=BORDER,
                    relief="flat", padding=(12, 7), font=font(10))
    style.map("TButton",
              background=[("active", NEUTRAL_BG), ("pressed", BORDER),
                          ("disabled", CARD)],
              foreground=[("disabled", FAINT)])
    style.configure("Accent.TButton", background=PRIMARY, foreground="#FFFFFF",
                    bordercolor=PRIMARY, lightcolor=PRIMARY, darkcolor=PRIMARY,
                    relief="flat", padding=(12, 7), font=font(10, bold=True))
    style.map("Accent.TButton",
              background=[("active", PRIMARY_DARK), ("pressed", PRIMARY_DARK),
                          ("disabled", "#93B4F5")],
              foreground=[("disabled", "#FFFFFF")])
    style.configure("Ghost.TButton", background=CARD, foreground=PRIMARY,
                    bordercolor=BORDER, lightcolor=CARD, darkcolor=BORDER,
                    relief="flat", padding=(10, 6))
    style.map("Ghost.TButton",
              background=[("active", PRIMARY_SOFT), ("pressed", PRIMARY_SOFT),
                          ("disabled", CARD)],
              foreground=[("active", PRIMARY_DARK), ("disabled", FAINT)])
    style.configure("Danger.TButton", background=CARD, foreground=DANGER,
                    bordercolor=BORDER, lightcolor=CARD, darkcolor=BORDER)
    style.map("Danger.TButton",
              background=[("active", DANGER_BG), ("disabled", CARD)],
              foreground=[("disabled", FAINT)])

    # 表格：白底、行高 30、浅灰表头、蓝色选中
    style.configure("Treeview", background=CARD, fieldbackground=CARD,
                    foreground=TEXT, bordercolor=BORDER, borderwidth=0,
                    rowheight=30, font=font(10))
    style.map("Treeview",
              background=[("selected", PRIMARY_SOFT)],
              foreground=[("selected", PRIMARY_DARK)])
    style.configure("Treeview.Heading", background="#F8FAFC", foreground=MUTED,
                    bordercolor=BORDER, relief="flat", padding=(8, 7),
                    font=font(10, bold=True))
    style.map("Treeview.Heading",
              background=[("active", "#EEF2F8"), ("pressed", "#EEF2F8")])
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

    # 输入框 / 下拉框
    style.configure("TEntry", fieldbackground=CARD, foreground=TEXT,
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                    insertcolor=TEXT, padding=(8, 6))
    style.map("TEntry", bordercolor=[("focus", PRIMARY)])
    style.configure("TCombobox", fieldbackground=CARD, background=CARD,
                    foreground=TEXT, arrowcolor=MUTED, bordercolor=BORDER,
                    lightcolor=CARD, darkcolor=CARD, padding=(8, 5))
    style.map("TCombobox", bordercolor=[("focus", PRIMARY)])

    # 滚动条 / 进度条
    for orient in ("Vertical", "Horizontal"):
        style.configure(orient + ".TScrollbar", background="#CBD5E1",
                        troughcolor=BG, bordercolor=BG, arrowcolor=MUTED,
                        lightcolor="#CBD5E1", darkcolor="#CBD5E1",
                        relief="flat")
        style.map(orient + ".TScrollbar",
                  background=[("active", "#94A3B8")])
    style.configure("TProgressbar", troughcolor=BORDER, background=PRIMARY,
                    bordercolor=BORDER, lightcolor=PRIMARY, darkcolor=PRIMARY,
                    thickness=6)
    style.configure("TSeparator", background=BORDER)

    # 分组框：白底卡片式
    style.configure("TLabelframe", background=BG, bordercolor=BORDER,
                    borderwidth=1, relief="solid")
    style.configure("TLabelframe.Label", background=BG, foreground=TEXT,
                    font=font(10, bold=True))
    style.configure("Card.TLabelframe", background=CARD, bordercolor=BORDER,
                    borderwidth=1, relief="solid")
    style.configure("Card.TLabelframe.Label", background=CARD, foreground=TEXT,
                    font=font(10, bold=True))

    style.configure("TCheckbutton", background=BG, foreground=TEXT)
    style.map("TCheckbutton", background=[("active", BG)],
              foreground=[("disabled", FAINT)])
    style.configure("Card.TCheckbutton", background=CARD, foreground=TEXT)
    style.map("Card.TCheckbutton", background=[("active", CARD)])

    return style
