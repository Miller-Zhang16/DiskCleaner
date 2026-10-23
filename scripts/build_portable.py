# -*- coding: utf-8 -*-
"""构建 Embeddable Python 便携包（本地与 CI 共用的唯一构建入口）。

用法：
    python scripts/build_portable.py

产物：
    dist/DiskCleaner-portable/           便携目录
    dist/DiskCleaner-portable.zip        分发包（对外发布用此文件）

设计要点：
    - 不把 Python 编译成 exe（PyInstaller 运行时解压到 %TEMP%，易被企业安全软件拦截）
    - 用原生 C 启动器 DiskCleaner.exe 拉起 python-embed\\pythonw.exe
    - 找不到 C 编译器时自动降级为 DiskCleaner.bat 启动器，构建不中断
"""

import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
PORTABLE = os.path.join(DIST, "DiskCleaner-portable")
ZIP_PATH = os.path.join(DIST, "DiskCleaner-portable.zip")
CACHE = os.path.join(DIST, ".cache")

sys.path.insert(0, ROOT)
from src.utils.config import DEFAULTS  # noqa: E402

# 便携包内嵌的解释器版本必须与本机构建解释器一致，否则 _tkinter.pyd 的 ABI 不兼容
EMBED_VERSION = "%d.%d.%d" % sys.version_info[:3]
EMBED_URL = (
    "https://www.python.org/ftp/python/%s/python-%s-embed-amd64.zip"
    % (EMBED_VERSION, EMBED_VERSION)
)

TCL_DIRS = [
    os.path.join("tcl", "tcl8.6"),
    os.path.join("tcl", "tk8.6"),
]


def log(msg):
    print(msg, flush=True)


def fail(msg):
    print("[错误] " + msg, file=sys.stderr, flush=True)
    sys.exit(1)


def prepare_dir():
    """清空并重建产物目录（保留缓存，避免重复下载 10MB 解释器）。"""
    if os.path.isdir(PORTABLE):
        shutil.rmtree(PORTABLE, ignore_errors=True)
    os.makedirs(os.path.join(PORTABLE, "python-embed"), exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)
    log("[1/6] 目录就绪: %s" % PORTABLE)


def download_embed():
    """下载（或复用缓存的）Python embeddable 压缩包。"""
    name = "python-%s-embed-amd64.zip" % EMBED_VERSION
    target = os.path.join(CACHE, name)
    if os.path.isfile(target) and os.path.getsize(target) > 1024 * 1024:
        log("[2/6] 复用缓存: %s" % name)
    else:
        log("[2/6] 下载 %s ..." % EMBED_URL)
        try:
            urllib.request.urlretrieve(EMBED_URL, target)
        except Exception as exc:
            fail("下载失败：%s\n      请确认 %s 存在可用的 embeddable 包。" % (exc, EMBED_VERSION))
    log("      解压到 python-embed ...")
    with zipfile.ZipFile(target) as zf:
        zf.extractall(os.path.join(PORTABLE, "python-embed"))


def copy_tkinter():
    """从当前解释器拷贝 tkinter 所需的三类资源（C 扩展 / tcl 资源 / Python 包）。"""
    log("[3/6] 集成 tkinter ...")
    prefix = sys.prefix
    dll_dirs = [os.path.join(prefix, "DLLs"), os.path.join(prefix, "Lib", "DLLs"), prefix]

    dest = os.path.join(PORTABLE, "python-embed")
    copied = 0
    for fname in ("_tkinter.pyd", "tcl86t.dll", "tk86t.dll", "zlib.dll"):
        for d in dll_dirs:
            src = os.path.join(d, fname)
            if os.path.isfile(src):
                shutil.copy2(src, dest)
                copied += 1
                break

    if copied < 3:
        fail("未找到 tkinter 的 C 扩展，请确认当前 Python 安装了 tkinter（官方安装包默认包含）。")

    for rel in ("tcl", os.path.join("Lib", "tcl")):
        src = os.path.join(prefix, rel)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dest, "tcl"), dirs_exist_ok=True)
            break
    else:
        fail("未找到 tcl 资源目录。")

    src = os.path.join(prefix, "Lib", "tkinter")
    if os.path.isdir(src):
        shutil.copytree(src, os.path.join(dest, "Lib", "tkinter"), dirs_exist_ok=True)
    else:
        fail("未找到 tkinter Python 包。")

    # 只保留运行必需的两个 tcl 版本目录，去掉 tzdata 等冗余
    tcl_root = os.path.join(dest, "tcl")
    if os.path.isdir(tcl_root):
        for entry in os.listdir(tcl_root):
            if entry not in ("tcl8.6", "tk8.6"):
                path = os.path.join(tcl_root, entry)
                shutil.rmtree(path, ignore_errors=True) if os.path.isdir(path) else None
    for rel in TCL_DIRS:
        if not os.path.isdir(os.path.join(dest, rel)):
            fail("tcl 目录缺失：%s" % rel)


def patch_pth():
    """配置 python*._pth：加入项目根与 Lib，并注释 import site。"""
    log("[4/6] 配置 _pth ...")
    embed = os.path.join(PORTABLE, "python-embed")
    candidates = [f for f in os.listdir(embed) if f.endswith("._pth")]
    if not candidates:
        fail("python-embed 中未找到 ._pth 文件。")
    path = os.path.join(embed, candidates[0])
    with open(path, "rb") as fh:
        text = fh.read().decode("utf-8")
    text = text.replace("\r\n", "\n")
    if "..\n" not in text:
        text = text.replace(".\n", ".\n..\nLib\n", 1)
    text = text.replace("import site", "#import site")
    with open(path, "wb") as fh:
        fh.write(text.encode("utf-8"))
    log("      %s 配置完成" % candidates[0])


def write_default_settings(dest_ini):
    """生成出厂默认 settings.ini。

    不直接拷贝开发目录里的配置文件：那里积累了开发者的窗口尺寸、
    清理项勾选历史等本机状态，随包分发会让用户拿到非初始状态。
    窗口尺寸这类运行时状态交由程序首次退出时写入。
    """
    lines = ["[General]"]
    for key, val in DEFAULTS.items():
        if key == "window_geometry":
            continue  # 运行时状态，不写入出厂配置，由程序按默认值处理
        lines.append("%s = %s" % (key, val))
    with open(dest_ini, "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write("\n".join(lines) + "\n")


def copy_project():
    """拷贝程序本体、源码、配置模板与图标。"""
    log("[5/6] 拷贝项目文件 ...")
    shutil.copy2(os.path.join(ROOT, "main.py"), PORTABLE)
    shutil.copytree(
        os.path.join(ROOT, "src"),
        os.path.join(PORTABLE, "src"),
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    data_dir = os.path.join(PORTABLE, "data")
    os.makedirs(data_dir, exist_ok=True)
    write_default_settings(os.path.join(data_dir, "settings.ini"))
    # custom_targets.txt 是纯模板注释文件，可直接拷贝
    src = os.path.join(ROOT, "data", "custom_targets.txt")
    if os.path.isfile(src):
        shutil.copy2(src, data_dir)
    if os.path.isdir(os.path.join(ROOT, "assets")):
        shutil.copytree(os.path.join(ROOT, "assets"), os.path.join(PORTABLE, "assets"))


def find_gcc():
    """按优先级查找 C 编译器：Nuitka 缓存（多层目录）→ PATH。"""
    roots = [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Nuitka"),
        os.path.join(os.environ.get("APPDATA", ""), "Nuitka"),
    ]
    for root in roots:
        if not os.path.isdir(root):
            continue
        for base, dirs, files in os.walk(root):
            if os.path.basename(base) == "bin" and "gcc.exe" in files:
                return os.path.join(base, "gcc.exe")
    return shutil.which("gcc")


def make_launcher():
    """编译原生 C 启动器；无编译器时降级为 .bat。"""
    log("[6/6] 生成启动器 ...")
    gcc = find_gcc()
    if gcc:
        windres = os.path.join(os.path.dirname(gcc), "windres.exe")
        res = os.path.join(ROOT, "launcher", "launcher.res")
        exe = os.path.join(PORTABLE, "DiskCleaner.exe")
        try:
            if os.path.isfile(windres):
                subprocess.run(
                    [windres, os.path.join(ROOT, "launcher", "launcher.rc"), "-O", "coff", "-o", res],
                    check=True, capture_output=True,
                )
            subprocess.run(
                [gcc, "-mwindows", "-O2", "-o", exe,
                 os.path.join(ROOT, "launcher", "launcher.c"), res,
                 "-luser32", "-lkernel32"],
                check=True, capture_output=True,
            )
            if os.path.isfile(exe):
                log("      DiskCleaner.exe 编译完成 (%d KB)" % (os.path.getsize(exe) // 1024))
                if os.path.isfile(res):
                    os.remove(res)
                return
        except subprocess.CalledProcessError as exc:
            log("      [警告] 启动器编译失败，降级为 .bat：%s" % (exc.stderr or b"").decode("utf-8", "ignore")[:200])
    else:
        log("      [警告] 未找到 gcc，降级为 .bat 启动器")

    bat = os.path.join(PORTABLE, "DiskCleaner.bat")
    with open(bat, "w", encoding="utf-8") as fh:
        fh.write(
            "@echo off\r\n"
            "cd /d \"%~dp0\"\r\n"
            "set \"TCL_LIBRARY=%~dp0python-embed\\tcl\\tcl8.6\"\r\n"
            "set \"TK_LIBRARY=%~dp0python-embed\\tcl\\tk8.6\"\r\n"
            "start \"\" \"python-embed\\pythonw.exe\" \"main.py\"\r\n"
        )
    log("      DiskCleaner.bat 生成完成")


def make_zip():
    """打包分发包，排除字节码缓存与运行日志。"""
    if os.path.isfile(ZIP_PATH):
        os.remove(ZIP_PATH)
    count = 0
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for base, dirs, files in os.walk(PORTABLE):
            dirs[:] = [d for d in dirs if d != "__pycache__" and d != "logs"]
            for f in files:
                if f.endswith(".pyc"):
                    continue
                full = os.path.join(base, f)
                zf.write(full, os.path.relpath(full, DIST))
                count += 1
    return count


def main():
    if os.name != "nt":
        fail("便携包构建仅支持 Windows。")

    log("=" * 46)
    log("  DiskCleaner 便携包构建")
    log("  内嵌 Python: %s" % EMBED_VERSION)
    log("=" * 46)

    prepare_dir()
    download_embed()
    copy_tkinter()
    patch_pth()
    copy_project()
    make_launcher()
    count = make_zip()

    size_mb = os.path.getsize(ZIP_PATH) / 1024 / 1024
    launcher = "DiskCleaner.exe" if os.path.isfile(os.path.join(PORTABLE, "DiskCleaner.exe")) else "DiskCleaner.bat"
    log("")
    log("=" * 46)
    log("  构建成功")
    log("=" * 46)
    log("  产物  : %s" % ZIP_PATH)
    log("  大小  : %.2f MB（%d 个文件）" % (size_mb, count))
    log("  启动器: %s" % launcher)
    log("=" * 46)


if __name__ == "__main__":
    main()
