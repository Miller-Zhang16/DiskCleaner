# 更新日志

本文件记录 DiskCleaner 的所有重要变更。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

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
