# -*- coding: utf-8 -*-
"""版本递增与发布辅助脚本。

用法：
    python scripts/release.py --show                    查看当前版本
    python scripts/release.py patch -m "修复 xxx"       递增补丁号并提交打 tag
    python scripts/release.py minor -m "新增 xxx"       递增次版本号
    python scripts/release.py major -m "重构 xxx"       递增主版本号
    python scripts/release.py patch -m "..." --push     提交后同时推送到远端

脚本会依次完成：
    1. 修改 src/version.py 中的 VERSION（版本号唯一来源）
    2. 在 CHANGELOG.md 顶部插入对应版本条目
    3. git commit + git tag -a vX.Y.Z
    4. 若带 --push，则推送提交与 tag（推送 tag 会触发 CI 自动发布）
"""

import argparse
import datetime
import io
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_FILE = os.path.join(ROOT, "src", "version.py")
CHANGELOG_FILE = os.path.join(ROOT, "CHANGELOG.md")

_VERSION_RE = re.compile(r'^VERSION\s*=\s*"([^"]+)"', re.MULTILINE)


def read_version():
    with io.open(VERSION_FILE, encoding="utf-8") as fh:
        match = _VERSION_RE.search(fh.read())
    if not match:
        sys.exit("[错误] 无法从 src/version.py 读取 VERSION")
    return match.group(1)


def write_version(new_version):
    with io.open(VERSION_FILE, encoding="utf-8") as fh:
        text = fh.read()
    text = _VERSION_RE.sub('VERSION = "%s"' % new_version, text, count=1)
    with io.open(VERSION_FILE, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def bump(version, part):
    try:
        major, minor, patch = (int(x) for x in version.split(".")[:3])
    except ValueError:
        sys.exit("[错误] 现有版本号不是 MAJOR.MINOR.PATCH 格式：%s" % version)
    if part == "major":
        return "%d.0.0" % (major + 1)
    if part == "minor":
        return "%d.%d.0" % (major, minor + 1)
    return "%d.%d.%d" % (major, minor, patch + 1)


def update_changelog(new_version, message):
    """在 Unreleased 段之后插入新版本条目。"""
    today = datetime.date.today().isoformat()
    entry = "## [%s] - %s\n\n### 变更\n\n- %s\n\n" % (new_version, today, message)

    if not os.path.isfile(CHANGELOG_FILE):
        with io.open(CHANGELOG_FILE, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("# 更新日志\n\n" + entry)
        return

    with io.open(CHANGELOG_FILE, encoding="utf-8") as fh:
        text = fh.read()
    if "## [Unreleased]" in text:
        head, _, tail = text.partition("## [Unreleased]\n")
        text = head + "## [Unreleased]\n\n" + entry + tail.lstrip("\n")
    else:
        head, _, tail = text.partition("\n\n")
        text = head + "\n\n" + entry + tail.lstrip("\n")
    with io.open(CHANGELOG_FILE, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def git(*args, **kwargs):
    result = subprocess.run(["git", "-C", ROOT] + list(args), capture_output=True, text=True)
    if result.returncode != 0 and not kwargs.get("allow_fail"):
        sys.exit("[错误] git %s 失败：\n%s" % (" ".join(args), result.stderr.strip()))
    return result


def main():
    parser = argparse.ArgumentParser(description="DiskCleaner 版本发布辅助脚本")
    parser.add_argument("part", nargs="?", choices=["patch", "minor", "major"], help="递增哪一位")
    parser.add_argument("-m", "--message", default="常规更新", help="变更说明，写入 CHANGELOG")
    parser.add_argument("--push", action="store_true", help="提交后推送到远端（触发 CI 发布）")
    parser.add_argument("--show", action="store_true", help="只打印当前版本号")
    args = parser.parse_args()

    if args.show or not args.part:
        print(read_version())
        return

    old = read_version()
    new = bump(old, args.part)
    tag = "v" + new

    existing = git("tag", "--list", tag).stdout.strip()
    if existing:
        sys.exit("[错误] tag %s 已存在，请先删除或换一个版本号。" % tag)

    write_version(new)
    update_changelog(new, args.message)
    print("版本号: %s -> %s" % (old, new))
    print("CHANGELOG.md 已插入 %s 条目" % new)

    git("add", VERSION_FILE, CHANGELOG_FILE)
    git("commit", "-m", "chore(release): %s" % tag)
    git("tag", "-a", tag, "-m", "DiskCleaner %s" % tag)
    print("已提交并创建 tag: %s" % tag)

    if args.push:
        git("push", "origin", "main")
        git("push", "origin", tag)
        print("已推送，CI 将自动构建并发布 Release。")
    else:
        print("")
        print("下一步推送（会触发 CI 自动发布）：")
        print("    git push origin main && git push origin %s" % tag)


if __name__ == "__main__":
    main()
