# -*- coding: utf-8 -*-
"""一致性校验：版本号 ↔ CHANGELOG ↔ git tag。

用法：
    python scripts/check_version.py              校验 VERSION 已写入 CHANGELOG
    python scripts/check_version.py --tag v1.2.3 同时校验 tag 与 VERSION 一致
"""

import argparse
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_FILE = os.path.join(ROOT, "src", "version.py")
CHANGELOG_FILE = os.path.join(ROOT, "CHANGELOG.md")
_VERSION_RE = re.compile(r'^VERSION\s*=\s*"([^"]+)"', re.MULTILINE)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="", help="期望的 git tag，例如 v1.2.3")
    args = parser.parse_args()

    with io.open(VERSION_FILE, encoding="utf-8") as fh:
        match = _VERSION_RE.search(fh.read())
    if not match:
        print("[错误] src/version.py 中未找到 VERSION")
        return 1
    version = match.group(1)

    with io.open(CHANGELOG_FILE, encoding="utf-8") as fh:
        changelog = fh.read()

    if "[%s]" % version not in changelog:
        print("[错误] CHANGELOG.md 缺少版本条目 [%s]" % version)
        return 1

    if args.tag:
        tag_version = args.tag[1:] if args.tag.startswith("v") else args.tag
        if tag_version != version:
            print("[错误] tag %s 与 VERSION %s 不一致" % (args.tag, version))
            return 1

    print("版本校验通过：%s" % version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
