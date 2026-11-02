# -*- coding: utf-8 -*-
"""界面文案的语言包引擎。

设计取舍：
    - 只做「界面骨架」的国际化（标签页、按钮、菜单、列头、对话框标题与提示）；
    - 清理项名称 / 分类 / 可删性评估等业务内容属于数据，不在语言包内；
    - 语言包按文件分目录存放（``src/locales/zh_CN.py`` / ``en_US.py``），
      新增语言只需新增一个模块，无需改代码；
    - 缺失的键回退到简体中文，再回退到键名本身，保证界面不会出现空白；
    - 切换语言在下次启动时生效（Tk 控件在创建时就固定了文案）。
"""

import importlib

LANGUAGES = {
    "zh_CN": "简体中文",
    "en_US": "English",
}

DEFAULT_LANGUAGE = "zh_CN"

_current = DEFAULT_LANGUAGE
_cache = {}


def _load(code):
    if code not in _cache:
        try:
            mod = importlib.import_module("src.locales." + code)
            _cache[code] = getattr(mod, "MESSAGES", {}) or {}
        except ImportError:
            _cache[code] = {}
    return _cache[code]


def set_language(code):
    """设置当前语言；未知语言回退到简体中文。"""
    global _current
    _current = code if code in LANGUAGES else DEFAULT_LANGUAGE


def get_language():
    return _current


def tr(key, **kwargs):
    """取某条界面文案，支持 ``{name}`` 占位符格式化。"""
    text = _load(_current).get(key)
    if text is None:
        text = _load(DEFAULT_LANGUAGE).get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text
