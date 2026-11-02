# DiskCleaner

> A Windows C: drive cleanup assistant — visualize disk usage, safely clean temporary files, classify files, and apply cleanup suggestions with one click. Download, double-click, run. No Python installation required.

**Languages:** [English](#-english) · [中文](#-中文)

---

# 🇬🇧 English

## 📖 Introduction

**DiskCleaner** is a C: drive cleanup tool for Windows. It provides disk usage visualization, automatic
temporary file cleanup, file classification, cleanup suggestions, and one-click cleanup through a GUI.
Download, double-click, and run — no Python environment needed.

- Platform: Windows 10 / 11
- Tech stack: Python 3.8+ (standard library + tkinter only, **no third-party runtime dependencies**)
- Distribution: source project + one-click build script + packaged `DiskCleaner.exe`

---

## 🎯 Core Features

### 1. Disk Usage Visualization
- The top bar shows C: drive **total / used / free** plus a usage bar (turns orange above 75%, red above 90%)
- The **Disk Browser** tab displays a tree where you can drill down into every folder and file size
- **Lazy loading**: children are read only when a folder is expanded, and sizes are computed asynchronously,
  so the UI never freezes on disk I/O
- Click the **Size** column to compute any folder on demand; when the scan budget is hit, a `≥` prefix marks
  the value as a lower bound

### 2. File Classification
Items are classified by path rules plus file extension, and color-coded in the list:

| Category | Scope |
|----------|-------|
| System files | `C:\Windows`, `System Volume Information`, `pagefile.sys` / `hiberfil.sys`, etc. |
| Application files | `Program Files`, `Program Files (x86)`, `ProgramData`, `AppData` |
| Data files | `Documents` / `Pictures` / `Videos` / `Music` / `Desktop` / `Downloads` / `OneDrive` |
| Cache & temp | Various `Temp`, `Prefetch`, browser caches, `SoftwareDistribution\Download`, WER, crash dumps |
| Recycle Bin | `$Recycle.Bin` |
| Other | Anything not matching the rules above |

> Classification is for reference only. User data folders such as Desktop, Documents, and Downloads are
> **never** marked as "cleanable".

### 3. Automatic Temp File Cleanup
18 built-in **conservative and safe** cleanup targets can be selected and executed directly. Targets that
require administrator privileges trigger a UAC prompt from the system when you click
"Restart as Administrator".

### 4. Cleanup Suggestions + One-Click Apply
Each cleanup target shows its **estimated reclaimable space, category, risk level, and description**.
Clicking "Apply Suggestions" auto-selects every built-in safe target, asks for confirmation once, executes
them in a single pass, then reports the actual space freed and any skipped files.

### 5. Administrator Privileges
- In normal mode, targets requiring administrator privileges are greyed out with a hint
- "Restart as Administrator" elevates via `ShellExecuteW(runas)`. If the user cancels the UAC prompt, the app
  keeps running in normal mode instead of crashing

### 6. Large-File Deletability Assessment
Every large file found in the **Large Files** tab carries a verdict — **Blocked / Risky / Cleanable / Keep** —
plus a reason, a safe way to free space, and a copy-ready command. Files marked *Blocked* (e.g. `pagefile.sys`,
`hiberfil.sys`, `WinSxS`) have direct deletion disabled; double-click a row to see the full assessment.

### 7. Cleanup History and Failure Details
- Each cleanup is appended to `data/history.jsonl` (capped by `history_max_records`)
- The result dialog lists every failed item with its path and reason (in use / access denied / missing),
  and double-clicking a row copies the path
- **View Cleanup History** (result dialog or Settings) reopens past runs and their failure details

### 8. Directory Migration (copy + junction)
The **Migrate** tab moves a big folder to another drive and leaves a junction at the original path, so programs
keep working unchanged. The flow is a three-stage idempotent state machine:
`copy → verify → delete source → create junction`. It is resumable after an interruption, and undo is allowed
only while the source data is still intact. Safety checks reject system directories, reparse points inside the
source, same-drive targets, and insufficient free space. Migration records are persisted in
`data/migrations.json`.

### 9. Bilingual UI (zh_CN / en_US)
All interface chrome (tabs, buttons, menus, column headers, dialog titles and messages) is resolved through a
language pack; switch the language in **Settings → Interface** (restart to apply). Long-form cleanup advice in
`file_advice` stays in Chinese.

### 10. Duplicate File Finder
The **Duplicates** tab finds byte-identical files with a three-stage strategy — group by size, compare head/tail
fingerprints (BLAKE2b), then confirm with full SHA-256 — so a scan never reads a whole file twice. Results are
grouped, each group keeps its **earliest modified copy**, and "Delete Extra Copies" removes the rest through the
normal cleanup pipeline (progress, failure details, history). System folders, reparse points, hard links and the
app's own directory are skipped; the scan respects time and entry budgets and reports when results may be
incomplete.

### 11. Disk Usage Trend Forecast
A daily usage snapshot is written to `data/growth.json` (one entry per day, up to 120 entries). The overview card
shows the average daily growth over the last 30 days and how many days remain until the drive is full. With fewer
than two days of data it says a trend is still being collected instead of guessing.

---

## 📁 Project Structure

```
C_improve/
├── main.py                     # Entry point
├── build.bat                   # Local one-click build (three modes)
├── CHANGELOG.md                # Changelog (maintained by the release script)
├── requirements.txt            # Build-time dependencies (none at runtime)
├── requirements-dev.txt        # Dev / CI dependencies (ruff)
├── pyproject.toml              # ruff configuration
├── README.md
├── LICENSE
├── .gitignore
├── assets/
│   └── icon.ico                # App icon (window + exe resource)
├── launcher/                   # Native C launcher source
│   ├── launcher.c              # Spawns python-embed\pythonw.exe
│   └── launcher.rc             # Icon and version info resource
├── scripts/
│   ├── build_portable.py       # Portable build (shared by local and CI)
│   ├── check_version.py        # VERSION / CHANGELOG / tag consistency check
│   └── release.py              # Version bump + CHANGELOG + tag
├── .github/workflows/
│   ├── ci.yml                  # Checks: ruff / compile / imports / version consistency
│   └── release.yml             # Builds and publishes a Release on tag push
├── data/
│   ├── settings.ini            # Configuration (editable in Notepad)
│   ├── custom_targets.txt      # Custom cleanup directories
│   └── logs/                   # Runtime logs (created on first run)
└── src/
    ├── version.py              # Version and app metadata (single source of truth)
    ├── core/                   # Core logic (no GUI dependency, independently testable)
    │   ├── runtime.py          # App root, admin detection, self-elevation
    │   ├── scanner.py          # Directory size scanning (lazy / budgeted)
    │   ├── classify.py         # File classification
    │   ├── targets.py          # Cleanup target table and size estimation
    │   ├── cleaner.py          # Deletion executor (whitelist checks / fault tolerance)
    │   ├── recycle.py          # Recycle Bin Shell API wrapper
    │   ├── file_advice.py      # Large-file deletability assessment and advice
    │   ├── history.py          # Cleanup history (JSONL, capped records)
    │   ├── duplicates.py       # Duplicate finder (size → fingerprint → SHA-256)
    │   ├── growth.py           # Daily usage snapshots and fill-up forecast
    │   └── migrator.py         # Directory migration state machine + junction handling
    ├── gui/                    # Presentation layer
    │   ├── app.py              # Main window, disk overview, task scheduling
    │   ├── theme.py            # Shared palette, fonts and card style helpers
    │   ├── browse_tab.py       # Disk browser tab
    │   ├── large_files_tab.py  # Large files tab (assessment + advice)
    │   ├── duplicates_tab.py   # Duplicate finder tab
    │   ├── suggest_tab.py      # Cleanup suggestions tab
    │   ├── migrate_tab.py      # Directory migration tab
    │   ├── settings_tab.py     # Settings tab
    │   ├── result_dialog.py    # Cleanup result dialog (failure details)
    │   └── history_dialog.py   # Cleanup history dialog
    ├── locales/                # UI language packs
    │   ├── zh_CN.py            # Simplified Chinese
    │   └── en_US.py            # English
    └── utils/                  # Shared utilities
        ├── fmt.py              # Size formatting, path and file attribute helpers
        ├── logger.py           # Rotating log (file + UI echo)
        ├── config.py           # Configuration I/O
        ├── i18n.py             # `tr()` lookup with zh_CN fallback
        └── taskrunner.py       # Background scheduler (lanes + priorities + generations)
```

---

## 🚀 Usage

### Launch

```bash
# Run from source
python main.py

# Or double-click the packaged executable
DiskCleaner.exe
```

### Interface Overview

```
┌──────────────────────────────────────────────────────────┐
│ C: drive: Used ███████░░░░ 312G/500G   Free 188G          │
│ [Refresh Disk] [Reload Config] [Restart as Administrator] │
├──────────────────────────────────────────────────────────┤
│ [Browse] [Large Files] [Duplicates] [Suggestions] [Migrate] [Settings] │
│   Disk Browser: lazy tree, drill down to inspect usage    │
│   Large Files: top-N biggest files on the drive           │
│   Duplicates: find and clean byte-identical copies        │
│   Suggestions: tick targets + [Apply][Clean Selected]     │
│   Settings: edit settings.ini from the GUI                │
├──────────────────────────────────────────────────────────┤
│ Status bar / progress bar                                 │
├──────────────────────────────────────────────────────────┤
│ Runtime log (also written to data/logs/diskcleaner.log)   │
└──────────────────────────────────────────────────────────┘
```

### Disk Browser Operations

| Action | Description |
|--------|-------------|
| Expand a folder | Drill into subfolders/files; the first few folders compute sizes automatically |
| Click the "Size" column | Compute that folder's size on demand (shows "computing…") |
| Right-click → Open in Explorer | Reveal the selected item in its parent folder |
| Right-click → Compute Size | Same as clicking the Size column |
| Right-click → Delete… | Delete the selected file/folder (confirmation required; critical system paths are blocked) |
| Right-click → Copy Full Path | Copy the absolute path to the clipboard |

### Cleanup Suggestions Operations

| Action | Description |
|--------|-------------|
| Click the "Select" column | Toggle whether a target participates in cleanup (persisted to settings.ini) |
| Apply Suggestions | Select all built-in safe targets and run them |
| Clean Selected | Run only the currently ticked targets |
| Re-estimate | Recompute the reclaimable space of every target |

### Migrate Tab Operations

| Action | Description |
|--------|-------------|
| Check and Estimate | Validate source/target and estimate the size (no data is moved) |
| Start Migration | Run copy → verify → delete source → create junction |
| Stop | Interrupt at a safe boundary; resume later from the record |
| Resume / Retry | Continue from the last completed stage |
| Undo Migration | Remove the target copy (only while the source is still intact) |
| Open Target / Remove Record | Open the target folder / drop the record (data is kept) |

### Cleanup History

Open it from the result dialog or the Settings tab. Double-click a record for details; "Clear History" removes
all records. The number of kept records is controlled by `history_max_records`.

---

## ⚙️ Configuration

### settings.ini

Located at `data/settings.ini` (created automatically on first run):

```ini
[General]
scan_budget_seconds = 6      ; Time budget per directory scan (s). Larger = more accurate but slower
scan_budget_entries = 200000 ; Entry budget per directory scan
temp_min_age_hours = 24      ; Only clean temp files older than this many hours
auto_size_limit = 150        ; Max number of subfolders auto-sized when expanding a folder
large_files_top_n = 200      ; Max number of largest files returned by the big-file scan
large_files_min_mb = 100     ; Only report files at least this large (MB, 0 = no filter)
history_max_records = 200    ; Max cleanup history records kept in data/history.jsonl
duplicates_min_mb = 1        ; Ignore duplicate candidates smaller than this (MB)
duplicates_budget_seconds = 60 ; Time budget per duplicate scan (s)
language = zh_CN             ; UI language: zh_CN / en_US (restart required)
log_level = INFO             ; DEBUG / INFO / WARNING / ERROR
log_max_bytes = 1048576      ; Max size of one log file before rotation
log_backup_count = 3         ; Number of rotated logs to keep
window_geometry = 1120x740   ; Window size (saved on exit)
confirm_before_clean = true  ; Ask for confirmation before cleaning

[Targets]
; Selection state of each cleanup target, true = selected by default
user_temp = true
win_temp = true
recycle = false
...
```

### custom_targets.txt

Located at `data/custom_targets.txt`. One absolute path per line adds **custom cleanup directories**:

```
# Lines starting with # are comments
C:\Temp\MyAppCache
```

Only the **contents** of the directory are deleted; the directory itself is preserved.

---

## 📝 Logging

Logs are written to `data/logs/diskcleaner.log`, rotating at 1 MB × 3 files, and are echoed to the log panel
at the bottom of the window:

```
[2026-10-20 13:05:12] [INFO] Application started. Version v1.0.0, privileges: Administrator
[2026-10-20 13:05:20] [INFO] Cleanup started: User temp files …
[2026-10-20 13:05:24] [INFO] [User temp files] Cleaning C:\Users\me\AppData\Local\Temp: freed 2.2 GB, deleted 1834 items
[2026-10-20 13:05:25] [INFO] One-click cleanup finished.; Freed (estimated): 3.9 GB, deleted 2911 items
```

---

## 🔧 Advanced Features

### Custom Cleanup Directories
Append your own cache folders to `data/custom_targets.txt` (useful for in-house applications). Restart the
app and they appear at the bottom of the cleanup suggestions list.

### Reload Configuration
After editing `settings.ini`, click "Reload Config" in the UI to apply changes without restarting.

### High DPI Support
DPI awareness is enabled at startup (`SetProcessDpiAwareness`), so the UI stays crisp on high-DPI displays.

### Background Task Model
Disk scanning and deletion both run on background worker threads and communicate with the main thread via
a generation counter plus a result queue. The scheduler has **two lanes** — `interactive` (disk browsing)
and `batch` (size estimation / cleanup) — each consumed by its own thread. Within a lane, work is ordered by
**priority** (directory listing > user cleanup > directory scan > size estimation), so expanding folders and
starting a cleanup respond immediately instead of queueing behind bulk estimation jobs. Clicking
"Re-estimate" cancels all stale jobs in that lane, keeping the UI responsive.

---

## 🛡️ Security Notes

### Never Cleaned
The following are **never** offered as cleanup targets and cannot be deleted via the context menu:

- `hiberfil.sys`, `pagefile.sys`, `swapfile.sys` (use `powercfg /h off` if needed)
- `WinSxS` (use `DISM /StartComponentCleanup` if needed)
- `C:\Windows\Installer`, `System32`
- The `$Recycle.Bin` directory itself, and shadow copies
- User data folders such as Desktop / Documents / Downloads (listed only as high-risk optional targets in
  Cleanup Suggestions, unchecked by default)

### Deletion Safety Mechanisms

1. **Whitelist path validation**: before deleting, `realpath` + `commonpath` verify the target lies inside
   the cleanup root, blocking prefix bypasses such as `C:\Windows\Temp2`
2. **Never descend into reparse points**: junctions / symlinks are unlinked only, never traversed — the
   single largest source of accidental deletion
3. **Per-item fault tolerance**: read-only files have the attribute cleared and are retried; files locked by
   another process (winerror 32) are retried briefly then added to the "skipped" list; permission errors are
   skipped without aborting the whole run
4. **Self exclusion**: the application's own directory is never included in any cleanup scope
5. **Temp file age filter**: `%TEMP%` only removes files older than the configured age (24 hours by default),
   avoiding deletion of files currently in use

### Freed Space Accounting
"Actual freed" is the **sum of `st_size` for successfully deleted files**, not the difference in free disk
space (which would be polluted by background system writes). The value is therefore an estimate, and the UI
labels it as such.

---

## 🐛 FAQ

### Some cleanup targets are greyed out and not clickable
**Cause**: Those targets require administrator privileges.
**Fix**: Click "Restart as Administrator" and choose "Yes" in the UAC dialog.

### A folder size shows `≥ 12.3 GB`
**Cause**: The folder exceeds the `scan_budget_seconds` / `scan_budget_entries` budget and the scan stopped early.
**Fix**: This is a **lower bound** — actual usage may be larger. For an exact value, raise the budget in
`settings.ini` and retry.

### Cleanup reports "skipped N items (in use or no permission)"
**Cause**: Those files are held by another program, or the current privileges are insufficient.
**Fix**: Close the program using them (browser, Office, etc.) and retry, or run as administrator.

### I have to sign in to websites again after clearing browser caches
**Cause**: This app only clears the `Cache` / `Code Cache` / `GPUCache` / `Service Worker\CacheStorage`
subfolders. It **never** touches cookies, bookmarks, passwords, or history. If a re-login is required, that
is the browser's own policy.

### Log files grow too large
**Fix**: Lower `log_max_bytes` / `log_backup_count` in `settings.ini`, or delete old files under `data/logs/`.

---

## 📋 Build Instructions

### Requirements
- Windows 10 / 11
- Python 3.10 (the portable package embeds an embeddable interpreter of the **same version** — versions must match)
- Optional: MinGW gcc (to compile the native launcher; falls back to a `.bat` launcher when missing)

### Three Build Modes

```bash
build.bat
```

| Mode | Output | Notes |
|------|--------|-------|
| 1. Embeddable portable | `dist/DiskCleaner-portable.zip` | **Recommended**, best compatibility with enterprise security software |
| 2. Nuitka | `dist/DiskCleaner-nuitka.zip` | Compiled to native machine code, 7-8 MB |
| 3. PyInstaller | `dist/DiskCleaner.exe` | Extracts to `%TEMP%` at runtime, may be blocked |

Mode 1 simply calls `scripts/build_portable.py` — **the same script used by CI releases**, so local builds
match official Releases exactly.

```bash
# Or call the script directly (identical to CI behavior)
python scripts/build_portable.py
```

Build pipeline: download embeddable interpreter → integrate tkinter → configure `_pth` → copy sources and
config → compile the `DiskCleaner.exe` launcher → pack the zip.

---

## 🔄 Maintenance and Release

### Single Source of Version
The version lives only in `VERSION` inside `src/version.py`. The window title, exe file version, and Release
title all derive from it, so they can never fall out of sync.

### Daily Development Flow

```bash
git checkout -b fix/scan-budget      # 1. Create a branch
#   ... edit code ...
python -m ruff check .               # 2. Local check (same rules as CI)
git commit -am "fix: correct scan budget boundary"
git push origin fix/scan-budget      # 3. Push; CI runs automatically
```

Once merged into `main`, CI runs: ruff lint → syntax compile → module imports → version/CHANGELOG consistency.

### Releasing a New Version (one command)

```bash
python scripts/release.py patch -m "Fix timeout when scanning large folders" --push
```

The script automatically:

1. Bumps `VERSION` (`patch` / `minor` / `major`)
2. Inserts a `## [x.y.z] - date` entry into `CHANGELOG.md`
3. Runs `git commit` + `git tag -a vX.Y.Z`
4. With `--push`, pushes the commit and tag → **GitHub Actions builds the portable package and publishes a Release**

Omit `--push` to have the script print the commands for you to run manually.

Show the current version:

```bash
python scripts/release.py --show
```

### What CI Does

| Workflow | Trigger | Action |
|----------|---------|--------|
| `ci.yml` | Push to `main`, pull request, manual | ruff lint, compile check, import check, version/CHANGELOG consistency |
| `release.yml` | Push a `v*` tag, manual | Verify tag matches version → build portable package → create GitHub Release and upload the zip |

> Release artifacts live on the Releases page. Users just download `DiskCleaner-portable.zip` and extract it —
> no local build required.

---

## 📄 License

Released under the [MIT License](LICENSE).

---

## 📞 Support

- Check `data/logs/diskcleaner.log` for detailed runtime information
- See the "Configuration" section of this document for all settings
- See [CHANGELOG.md](CHANGELOG.md) for version history

---

*Last updated: 2026-11-02*

---

# 🇨🇳 中文

## 📖 简介

**DiskCleaner** 是一个 Windows 平台的 C 盘空间清理工具，提供磁盘占用可视化、自动清理临时文件、
文件分类、清理建议与一键清理等功能，并以 GUI 形式呈现，下载后双击即可使用，无需安装 Python 环境。

- 运行环境：Windows 10 / 11
- 技术栈：Python 3.8+（仅标准库 + tkinter，**运行时无第三方依赖**）
- 交付形态：源码工程 + 一键构建脚本 + 打包好的 `DiskCleaner.exe`

---

## 🎯 核心功能

### 1. 磁盘占用可视化
- 顶部实时显示 C 盘「总量 / 已用 / 可用」与占用比例条（超过 75% 变橙、超过 90% 变红）
- 「磁盘浏览」页以树形结构逐级展开查看每个目录与文件的大小
- 采用**懒加载**：展开某目录时才读取其子项并异步计算大小，界面不会因磁盘 IO 卡死
- 单击「大小」列可对任意目录按需计算；受扫描预算限制时显示 `≥` 表示估算下界

### 2. 文件分类
按路径规则 + 扩展名自动分类，并在列表中以颜色区分：

| 分类 | 涵盖范围 |
|------|----------|
| 系统文件 | `C:\Windows`、`System Volume Information`、`pagefile.sys` / `hiberfil.sys` 等 |
| 软件文件 | `Program Files`、`Program Files (x86)`、`ProgramData`、`AppData` |
| 数据文件 | `Documents` / `Pictures` / `Videos` / `Music` / `Desktop` / `Downloads` / `OneDrive` |
| 缓存临时 | 各类 `Temp`、`Prefetch`、浏览器缓存、`SoftwareDistribution\Download`、WER、崩溃转储等 |
| 回收站 | `$Recycle.Bin` |
| 其他 | 未命中以上规则的项目 |

> 分类仅用于辅助判断，**不会**把桌面、文档、下载等用户数据目录标记为「可清理」。

### 3. 自动清理临时文件
内置 18 个「保守且安全」的清理项，可直接勾选执行；需要管理员权限的项会在点击
「以管理员身份重启」时由系统自行弹出 UAC 授权。

### 4. 清理建议 + 一键采用建议
每个清理项都会显示**预估可释放空间、分类、风险等级与说明**；
点击「一键采用建议」会自动勾选全部内置推荐的安全项，二次确认后一次性执行，
并汇报实际释放空间与被跳过的文件。

### 5. 管理员权限
- 普通模式下，需要管理员权限的清理项会置灰并给出提示
- 点击「以管理员身份重启」通过 `ShellExecuteW(runas)` 触发 UAC；用户取消授权时程序继续以普通模式运行，不会崩溃

### 6. 大文件可删性评估
「大文件」页为每个文件给出**禁止删除 / 高风险 / 可清理 / 建议保留**结论，并附原因、安全释放方式与
可一键复制的命令。判定为「禁止删除」的文件（如 `pagefile.sys`、`hiberfil.sys`、`WinSxS`）会禁用直接删除；
双击条目可查看完整评估。

### 7. 清理历史与失败明细
- 每次清理写入 `data/history.jsonl`，按 `history_max_records` 上限自动淘汰旧记录
- 结果对话框逐项列出失败路径与原因（被占用 / 无权限 / 已不存在），双击可复制路径
- 「查看清理历史」（结果对话框或设置页）可回看历次清理及其失败明细

### 8. 目录迁移（复制 + 目录链接）
「迁移」页把大目录搬到其他盘，并在原路径建立 junction，程序仍按原路径照常访问。流程为三阶段幂等状态机：
`复制 → 校验 → 删除源 → 建链接`，中断后可续跑；仅在源数据仍完整时允许撤销。
安全校验会拒绝系统目录、源目录内的重解析点、同盘目标与空间不足的情况；迁移记录保存在
`data/migrations.json`。

### 9. 中英双语界面（zh_CN / en_US）
全部界面元素（标签页、按钮、菜单、列头、对话框标题与提示）均通过语言包解析；在
**设置 → 界面** 中切换语言（重启后生效）。`file_advice` 的长文建议保持中文。

### 10. 重复文件查找
「重复文件」页用三层策略找出内容完全相同的文件：先按大小分组，再比较首尾指纹（BLAKE2b），
最后用 SHA-256 全量确认，因此单个文件不会被重复读取。结果按组展示，每组**保留最早修改的一份**，
「删除选中组的额外副本」走正常清理流程（进度、失败明细、历史记录一致）。
扫描会跳过系统关键目录、重解析点、硬链接与程序自身目录，并受时间与条目预算限制，超限时明确提示结果可能不完整。

### 11. 磁盘占用趋势预测
每天写入一条磁盘占用快照到 `data/growth.json`（同日覆盖，最多 120 条）。概览卡片显示最近 30 天的
日均增长量，以及按此速度还有多少天写满。数据不足 2 天时只提示「正在记录」，不做推测。

---

## 📁 项目结构

```
C_improve/
├── main.py                     # 程序入口
├── build.bat                   # 本地一键构建（三种方式可选）
├── CHANGELOG.md                # 更新日志（随版本递增自动维护）
├── requirements.txt            # 打包所需依赖（运行时无依赖）
├── requirements-dev.txt        # 开发/CI 依赖（ruff）
├── pyproject.toml              # ruff 代码规范配置
├── README.md
├── LICENSE
├── .gitignore
├── assets/
│   └── icon.ico                # 应用图标（窗口 + exe 资源）
├── launcher/                   # 原生 C 启动器源码
│   ├── launcher.c              # 拉起 python-embed\pythonw.exe
│   └── launcher.rc             # 图标与版本信息资源
├── scripts/
│   ├── build_portable.py       # 便携包构建（本地与 CI 共用同一入口）
│   ├── check_version.py        # 版本号 / CHANGELOG / tag 一致性校验
│   └── release.py              # 版本递增 + CHANGELOG + 打 tag
├── .github/workflows/
│   ├── ci.yml                  # 提交检查：ruff / 编译 / 导入 / 版本一致性
│   └── release.yml             # 打 tag 自动构建并发布 Release
├── data/
│   ├── settings.ini            # 配置文件（可用记事本编辑）
│   ├── custom_targets.txt      # 自定义清理目录
│   └── logs/                   # 运行日志（首次运行生成）
└── src/
    ├── version.py              # 版本号与应用元信息（唯一版本来源）
    ├── core/                   # 核心逻辑（无 GUI 依赖，可独立测试）
    │   ├── runtime.py          # 应用根目录、管理员判定、自我提权
    │   ├── scanner.py          # 目录大小扫描（懒加载 / 预算控制）
    │   ├── classify.py         # 文件分类
    │   ├── targets.py          # 清理目标表与空间估算
    │   ├── cleaner.py          # 删除执行器（白名单校验 / 容错删除）
    │   ├── recycle.py          # 回收站 Shell API 封装
    │   ├── file_advice.py      # 大文件可删性评估与清理建议
    │   ├── history.py          # 清理历史（JSONL，按上限淘汰）
    │   ├── duplicates.py       # 重复文件查找（大小 → 指纹 → SHA-256）
    │   ├── growth.py           # 磁盘占用每日快照与写满预测
    │   └── migrator.py         # 目录迁移状态机 + junction 处理
    ├── gui/                    # 界面层
    │   ├── app.py              # 主窗口、磁盘概览、任务调度
    │   ├── theme.py            # 统一配色、字体与卡片样式工具
    │   ├── browse_tab.py       # 磁盘浏览页
    │   ├── large_files_tab.py  # 大文件页（可删性评估）
    │   ├── duplicates_tab.py   # 重复文件页
    │   ├── suggest_tab.py      # 清理建议页
    │   ├── migrate_tab.py      # 目录迁移页
    │   ├── settings_tab.py     # 设置页
    │   ├── result_dialog.py    # 清理结果对话框（失败明细）
    │   └── history_dialog.py   # 清理历史对话框
    ├── locales/                # 界面语言包
    │   ├── zh_CN.py            # 简体中文
    │   └── en_US.py            # 英文
    └── utils/                  # 通用工具
        ├── fmt.py              # 体积格式化、路径与文件属性工具
        ├── logger.py           # 滚动日志（文件 + 界面回显）
        ├── config.py           # 配置读写
        ├── i18n.py             # `tr()` 查表与 zh_CN 回退
        └── taskrunner.py       # 后台任务调度（三通道 + 优先级 + 世代号）
```

---

## 🚀 使用说明

### 启动

```bash
# 源码运行
python main.py

# 或直接双击打包好的可执行文件
DiskCleaner.exe
```

### 界面总览

```
┌──────────────────────────────────────────────────────────┐
│ C 盘状态：已用 ███████░░░░ 312G/500G   可用 188G          │
│ [刷新磁盘信息] [重新加载配置] [以管理员身份重启]           │
├──────────────────────────────────────────────────────────┤
│ [ 磁盘浏览 ] [ 大文件 ] [ 重复文件 ] [ 清理建议 ] [ 迁移 ] [ 设置 ]        │
│   磁盘浏览：树形懒加载，逐级展开查看占用                   │
│   大文件：扫描整盘最大的 N 个文件                          │
│   重复文件：查找并清理内容完全相同的副本                   │
│   清理建议：勾选清理项 + [一键采用建议][清理选中项]         │
│   设置：在界面内编辑 settings.ini 配置                     │
├──────────────────────────────────────────────────────────┤
│ 状态栏 / 进度条                                           │
├──────────────────────────────────────────────────────────┤
│ 运行日志（同时写入 data/logs/diskcleaner.log）             │
└──────────────────────────────────────────────────────────┘
```

### 磁盘浏览页操作

| 操作 | 说明 |
|------|------|
| 展开目录 | 逐级查看子目录/文件占用，前若干个目录自动计算大小 |
| 单击「大小」列 | 对该目录按需计算大小（显示「计算中…」） |
| 右键 → 在资源管理器中打开位置 | 定位到选中项所在目录 |
| 右键 → 计算该项大小 | 同单击大小列 |
| 右键 → 删除此项… | 删除选中文件/目录（需二次确认；系统关键目录会被拦截） |
| 右键 → 复制完整路径 | 复制选中项绝对路径到剪贴板 |

### 清理建议页操作

| 操作 | 说明 |
|------|------|
| 单击「勾选」列 | 切换该项是否参与清理（选择会被保存到 settings.ini） |
| 一键采用建议 | 勾选全部内置推荐的安全项并执行 |
| 清理选中项 | 只执行当前勾选的项目 |
| 重新估算 | 重新计算各项可释放空间 |

### 迁移页操作

| 操作 | 说明 |
|------|------|
| 检查并计算体积 | 校验源/目标路径并估算体积（不移动任何数据） |
| 开始迁移 | 复制 → 校验 → 删除源目录 → 建立目录链接 |
| 停止 | 在安全边界中断，稍后可从迁移记录续跑 |
| 继续 / 重试 | 从上次完成的阶段继续 |
| 撤销迁移 | 删除目标副本（仅限源目录尚未删除时） |
| 打开目标位置 / 从列表移除 | 打开目标目录 / 只删除记录（数据保留） |

### 清理历史

可从结果对话框或设置页打开；双击记录查看详情，「清空历史」删除全部记录。
保留条数由 `history_max_records` 控制。

---

## ⚙️ 配置文件

### settings.ini

位于 `data/settings.ini`（首次运行自动生成）：

```ini
[General]
scan_budget_seconds = 6      ; 单次目录扫描的时间预算（秒），越大越精确但越慢
scan_budget_entries = 200000 ; 单次目录扫描的条目预算
temp_min_age_hours = 24      ; 临时文件仅清理该小时数之前的项目
auto_size_limit = 150        ; 展开目录时自动计算大小的子目录数量上限
large_files_top_n = 200      ; 大文件扫描返回的结果数上限
large_files_min_mb = 100     ; 大文件扫描仅统计不小于该 MB 数的文件（0 表示不过滤）
history_max_records = 200    ; 清理历史保留条数上限（data/history.jsonl）
duplicates_min_mb = 1        ; 重复文件扫描仅统计不小于该 MB 数的文件
duplicates_budget_seconds = 60 ; 单次重复文件扫描的时间预算（秒）
language = zh_CN             ; 界面语言：zh_CN / en_US（重启后生效）
log_level = INFO             ; DEBUG / INFO / WARNING / ERROR
log_max_bytes = 1048576      ; 单份日志最大字节数，超出后滚动
log_backup_count = 3         ; 保留的历史日志份数
window_geometry = 1120x740   ; 窗口尺寸（退出时自动保存）
confirm_before_clean = true  ; 清理前是否二次确认

[Targets]
; 各清理项的勾选状态，true 表示默认勾选
user_temp = true
win_temp = true
recycle = false
...
```

### custom_targets.txt

位于 `data/custom_targets.txt`，每行一个绝对路径，用于添加**自定义清理目录**：

```
# 以 # 开头为注释
C:\Temp\MyAppCache
```

程序只删除目录**内部**的内容，保留目录本身。

---

## 📝 日志文件

日志位于 `data/logs/diskcleaner.log`，按 1MB × 3 份滚动，同时回显到界面底部日志面板：

```
[2026-10-20 13:05:12] [INFO] 程序启动完成。版本 v1.0.0，当前权限：管理员模式
[2026-10-20 13:05:20] [INFO] 开始清理：用户临时文件 …
[2026-10-20 13:05:24] [INFO] [用户临时文件] 清理 C:\Users\me\AppData\Local\Temp：释放 2.2 GB，删除 1834 项
[2026-10-20 13:05:25] [INFO] 一键清理 完成。；实际释放（估算）：3.9 GB，删除 2911 项
```

---

## 🔧 高级功能

### 自定义清理目录
在 `data/custom_targets.txt` 中追加你的缓存目录（常用于自研程序），重启程序后即会出现在清理建议列表底部。

### 重新加载配置
修改 `settings.ini` 后，点击界面上的「重新加载配置」，无需重启即可生效。

### 高 DPI 适配
程序启动时自动开启 DPI 感知（`SetProcessDpiAwareness`），在高分屏下界面不发虚。

### 后台任务模型
磁盘扫描与删除都在后台工作线程执行，通过「世代号 + 结果队列」与主线程通信。
调度器内置**两条通道**：`interactive`（磁盘浏览）与 `batch`（空间估算 / 清理），
分别由独立线程消费；通道内部再按**优先级**调度（读取目录子项 > 用户清理 > 目录扫描 > 空间估算），
因此展开目录查看占用、点击清理都能立刻响应，而不会被大批量估算任务阻塞；
点击「重新估算」会取消该通道内的全部过期任务，界面始终保持响应。

---

## 🛡️ 安全说明

### 绝不清理的系统关键项
以下内容**不会**作为可清理项出现，也不允许通过右键删除：

- `hiberfil.sys`、`pagefile.sys`、`swapfile.sys`（如需处理请用 `powercfg /h off`）
- `WinSxS`（如需清理请用 `DISM /StartComponentCleanup`）
- `C:\Windows\Installer`、`System32`
- `$Recycle.Bin` 目录本身、卷影副本
- 桌面 / 文档 / 下载等用户数据目录（仅在「清理建议」中作为高风险可选项列出，默认不勾选）

### 删除安全机制

1. **白名单路径校验**：删除前用 `realpath` + `commonpath` 校验目标落在待清理根目录内，拦截 `C:\Windows\Temp2` 这类前缀绕过
2. **不深入重解析点**：遇到 junction / symlink 只删除链接本身，绝不深入链接目标（这是误删的最大来源）
3. **逐项容错**：只读文件先去掉只读属性再重试；被占用（winerror 32）短重试后记入「跳过清单」；无权限直接跳过，不中断整体流程
4. **明确排除自身**：程序所在目录永不纳入清理范围
5. **临时文件时长过滤**：`%TEMP%` 只清理超过设定时长（默认 24 小时）的文件，避免误删正在使用的文件

### 释放空间统计口径
「实际释放」按**成功删除文件的 `st_size` 之和**统计，而不是磁盘可用空间的前后差值
（后者会被系统后台写入污染）。因此该数值为估算值，界面会明确标注。

---

## 🐛 常见问题

### 问题：某些清理项是灰色的，点不动
**原因**：该项需要管理员权限。
**解决**：点击「以管理员身份重启」，在 UAC 对话框中点击「是」。

### 问题：扫描目录时显示 `≥ 12.3 GB`
**原因**：该目录体积过大，超过了 `scan_budget_seconds` / `scan_budget_entries` 预算，提前结束。
**解决**：这是**下界**，说明实际占用可能更大。如需精确值，可调大 `settings.ini` 中的预算后重试。

### 问题：清理时提示「跳过 N 项（被占用或无权限）」
**原因**：这些文件正被其它程序使用，或当前权限不足。
**解决**：关闭占用该文件的程序（例如浏览器、Office）后重试，或以管理员身份运行。

### 问题：清理浏览器缓存后需要重新登录网站
**原因**：本程序只清理 `Cache` / `Code Cache` / `GPUCache` / `Service Worker\CacheStorage` 这几个缓存子目录，
**不会**触碰 Cookie、书签、密码与历史记录。若确实需要重新登录，属于浏览器自身策略。

### 问题：日志文件太大
**解决**：`settings.ini` 中调小 `log_max_bytes` / `log_backup_count`，或直接删除 `data/logs/` 下的旧日志。

---

## 📋 构建说明

### 环境要求
- Windows 10 / 11
- Python 3.10（便携包会内嵌**同版本**的 embeddable 解释器，版本必须一致）
- 可选：MinGW gcc（用于编译原生启动器；缺失时自动降级为 `.bat` 启动器）

### 三种构建方式

```bash
build.bat
```

| 方式 | 产物 | 说明 |
|------|------|------|
| 1. Embeddable 便携包 | `dist/DiskCleaner-portable.zip` | **推荐**，与企业安全软件兼容性最好 |
| 2. Nuitka | `dist/DiskCleaner-nuitka.zip` | 编译为原生机器码，体积 7-8 MB |
| 3. PyInstaller | `dist/DiskCleaner.exe` | 运行时解压到 `%TEMP%`，可能被拦截 |

方式 1 只是调用 `scripts/build_portable.py`——**CI 发布用的也是这个脚本**，因此本地构建产物与官方 Release 完全一致。

```bash
# 也可直接调用脚本（CI 与本地行为一致）
python scripts/build_portable.py
```

构建流程：下载 embeddable 解释器 → 集成 tkinter → 配置 `_pth` → 拷贝源码与配置 → 编译 `DiskCleaner.exe` 启动器 → 打包 zip。

---

## 🔄 维护与发布

### 版本号唯一来源

版本号只存在于 `src/version.py` 的 `VERSION`，窗口标题、exe 文件版本、Release 标题都由此派生，避免多处不同步。

### 日常开发流程

```bash
git checkout -b fix/scan-budget      # 1. 开分支改代码
#   ... 修改代码 ...
python -m ruff check .               # 2. 本地自检（与 CI 同一规则）
git commit -am "fix: 修正扫描预算边界"
git push origin fix/scan-budget      # 3. 推送，CI 自动检查
```

合并到 `main` 后，CI 会跑：ruff 规范检查 → 语法编译 → 模块导入 → 版本号与 CHANGELOG 一致性。

### 发布新版本（一条命令）

```bash
python scripts/release.py patch -m "修复大目录扫描超时" --push
```

脚本自动完成：

1. 递增 `VERSION`（`patch` / `minor` / `major` 三选一）
2. 在 `CHANGELOG.md` 插入 `## [x.y.z] - 日期` 条目
3. `git commit` + `git tag -a vX.Y.Z`
4. `--push` 推送提交与 tag → **GitHub Actions 自动构建便携包并发布 Release**

不想自动推送时省略 `--push`，脚本会打印需要手动执行的命令。

查看当前版本：

```bash
python scripts/release.py --show
```

### CI 会做什么

| 工作流 | 触发条件 | 动作 |
|--------|----------|------|
| `ci.yml` | 推送到 `main`、提交 PR、手动 | ruff 检查、编译检查、导入检查、版本/CHANGELOG 一致性校验 |
| `release.yml` | 推送 `v*` tag、手动 | 校验 tag 与版本号一致 → 构建便携包 → 创建 GitHub Release 并上传 zip |

> 发布产物挂在 Release 页面，用户下载 `DiskCleaner-portable.zip` 解压即可，无需自行构建。

---

## 📄 License（许可证）

本项目基于 [MIT License](LICENSE) 开源。

---

## 📞 支持

- 查看日志文件 `data/logs/diskcleaner.log` 获取详细运行信息
- 详细配置说明见本文档「配置文件」章节
- 历史版本变更见 [CHANGELOG.md](CHANGELOG.md)

---

*Last updated: 2026-11-02*