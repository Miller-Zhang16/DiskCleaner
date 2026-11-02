# 更新日志

本文件记录 DiskCleaner 的所有重要变更。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 新增

+- 大文件可删性评估：为每个大文件给出「禁止删除 / 高风险 / 可清理 / 建议保留」结论、原因、安全释放方式与可复制的参考命令
+- 清理结果对话框：逐项展示失败明细（路径 + 原因），支持双击复制路径
+- 清理历史：每次清理写入 `data/history.jsonl`，按 `history_max_records` 上限淘汰，支持查看详情与清空
+- 目录迁移：把 C 盘大目录复制到其他盘并建立 junction，三阶段幂等状态机、可续跑、可撤销，迁移记录持久化
+- 中英双语界面：新增 i18n 引擎与 `zh_CN` / `en_US` 语言包，设置页可切换语言（重启生效）
+- 界面重设计：左侧导航 + 卡片式概览 + 折叠日志面板，新增 `theme.py` 统一配色与样式
+- 重复文件查找：大小分组 → 首尾指纹 → SHA-256 三层确认，按组展示并保留最早副本，可一键删除额外副本
+- 磁盘占用趋势：每日快照写入 `data/growth.json`，概览卡片显示日均增长与写满预测

### 变更

+- 设置页新增「界面」「重复文件」分组与「查看清理历史」入口；`settings.ini` 新增 `history_max_records`、`language`、`duplicates_min_mb`、`duplicates_budget_seconds`
+- 新增 `tests/test_migrator.py`、`tests/test_history.py`、`tests/test_duplicates.py`、`tests/test_growth.py`，覆盖迁移状态机、历史裁剪、重复文件比对与趋势预测

## [1.0.0] - 2026-10-20

### 新增

- 磁盘可视化浏览：懒加载目录树，逐项显示目录/文件占用，支持按大小排序
- 18 项内置保守清理目标，默认勾选 12 项安全项，风险等级用颜色区分
- 文件分类：系统文件 / 软件文件 / 数据文件 / 缓存临时 / 回收站 / 其他
- 一键采纳清理建议，清理前二次确认，需管理员权限的操作自动 UAC 提权
- 自定义清理目录（`data/custom_targets.txt`）
- 原生 C 启动器 `DiskCleaner.exe`，规避企业安全软件对 PyInstaller 产物的拦截
- 日志轮转（1 MB × 3 份）、INI 配置持久化
- 白名单保护：系统目录、重解析点、程序自身路径均不会被删除
