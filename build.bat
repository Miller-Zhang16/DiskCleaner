@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   DiskCleaner 构建脚本 v3.0
echo ============================================
echo.
echo 请选择构建方式：
echo.
echo   [1] Embeddable Python 便携包  (推荐)
echo       不编译、不解压到 %%TEMP%%，AV 误报率最低
echo       适合 Trend Micro / UniAccessAgent 等企业安全环境
echo       与 CI 发布使用同一脚本，本地可复现官方产物
echo.
echo   [2] Nuitka 原生 C 编译  (高级)
echo       Python 编译为原生机器码，体积小，AV 误报率低
echo       需要 C 编译器（自动下载 MinGW64）
echo.
echo   [3] PyInstaller 单文件 exe
echo       传统方案，运行时解压到 %%TEMP%%，
echo       可能被企业安全软件拦截
echo.
set /p choice="请输入选项 [1/2/3]: "

if "%choice%"=="1" goto :build_embeddable
if "%choice%"=="2" goto :build_nuitka
if "%choice%"=="3" goto :build_pyinstaller
echo 无效选项，退出。
pause
exit /b 1

rem ============ 方式 1: 便携包（委托给 Python 构建脚本）============

:build_embeddable
echo.
where python >nul 2>nul
if errorlevel 1 goto :no_python

rem 读取当前版本号
set "VER="
for /f "delims=" %%v in ('python scripts\release.py --show 2^>nul') do set "VER=%%v"
if defined VER echo 当前版本: %VER%
echo.

python scripts\build_portable.py
if errorlevel 1 goto :build_failed

echo.
echo   用户解压后双击 DiskCleaner.exe 即可启动，
echo   完全不依赖系统 Python，无需安装。
echo.
pause
exit /b 0

rem ============ 方式 2: Nuitka ============

:build_nuitka
echo.
echo ============================================
echo   方式 2: Nuitka 原生 C 编译
echo ============================================
echo.

echo [1/4] 检查 Python 环境 ...
where python >nul 2>nul
if errorlevel 1 goto :no_python
python --version
echo.

echo [2/4] 检查/安装 Nuitka ...
python -c "import nuitka" >nul 2>nul
if errorlevel 1 (
    echo 未检测到 Nuitka，正在安装 ...
    python -m pip install nuitka ordered-set || goto :pip_failed
)
python -m nuitka --version
echo.

echo [3/4] 开始 Nuitka onefile 编译 (首次运行会自动下载 MinGW64) ...
echo.
set "VER="
for /f "delims=" %%v in ('python scripts\release.py --show 2^>nul') do set "VER=%%v"
if not defined VER set "VER=1.0.0"

set "NUITKA_ICON="
if exist "assets\icon.ico" set "NUITKA_ICON=--windows-icon-from-ico=assets\icon.ico"
python -m nuitka --assume-yes-for-downloads ^
  --enable-plugin=tk-inter ^
  --onefile ^
  --windows-console-mode=disable ^
  --output-dir=build ^
  --output-filename=DiskCleaner.exe ^
  --windows-product-name=DiskCleaner ^
  --windows-file-description="C 盘清理助手" ^
  --windows-file-version=%VER% ^
  --windows-product-version=%VER% ^
  --include-data-files=data\settings.ini=data\settings.ini ^
  --include-data-files=data\custom_targets.txt=data\custom_targets.txt ^
  %NUITKA_ICON% ^
  main.py
if errorlevel 1 goto :nuitka_failed
echo.

echo [4/4] 整理产物 ...
if exist "build\DiskCleaner.exe" (
    if not exist "dist" mkdir dist
    move /y "build\DiskCleaner.exe" "dist\DiskCleaner.exe" >nul 2>nul
    cd /d dist
    python -c "import zipfile; z=zipfile.ZipFile('DiskCleaner-nuitka.zip','w',zipfile.ZIP_DEFLATED); z.write('DiskCleaner.exe'); z.close(); print('zip 打包完成')"
    cd /d "%~dp0"
)

echo.
echo ============================================
echo   Nuitka 编译成功！
echo ============================================
echo   产物: dist\DiskCleaner-nuitka.zip
echo   单 exe 体积约 7-8 MB
echo.
echo   Python 代码已编译为原生机器码，
echo   AV 误报率远低于 PyInstaller。
echo   首次运行在 exe 同目录生成 data\ 。
echo ============================================
pause
exit /b 0

rem ============ 方式 3: PyInstaller ============

:build_pyinstaller
echo.
echo ============================================
echo   方式 3: PyInstaller 单文件 exe
echo ============================================
echo.

echo [1/3] 检查 Python 环境 ...
where python >nul 2>nul
if errorlevel 1 goto :no_python
python --version
echo.

echo [2/3] 检查/安装 PyInstaller ...
python -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
    echo 未检测到 PyInstaller，正在安装 ...
    python -m pip install --upgrade pyinstaller || goto :pip_failed
)
echo PyInstaller 已安装。
echo.

echo [3/3] 开始打包 ...
echo.
set "PYINST_ICON="
if exist "assets\icon.ico" set "PYINST_ICON=--icon=assets\icon.ico"
set "PYINST_DATA="
if exist "data\settings.ini" set "PYINST_DATA=--add-data data;data"
python -m PyInstaller --clean --noconfirm --onefile --windowed --name DiskCleaner ^
  %PYINST_ICON% %PYINST_DATA% main.py
if errorlevel 1 goto :pyinst_failed

echo.
echo ============================================
echo   PyInstaller 构建成功！
echo ============================================
echo   产物: dist\DiskCleaner.exe
echo.
echo   注意: 此方式运行时解压到 %%TEMP%%，
echo   可能被企业安全软件拦截。
echo ============================================
pause
exit /b 0

rem ============ 错误处理 ============

:no_python
echo [错误] 未找到 python，请先安装 Python 3.10+ 并勾选 "Add to PATH"。
pause
exit /b 1

:build_failed
echo [错误] 便携包构建失败，请查看上方错误信息。
pause
exit /b 1

:pip_failed
echo [错误] pip 安装失败，请检查网络后重试。
pause
exit /b 1

:nuitka_failed
echo [错误] Nuitka 编译失败，请查看上方错误信息。
pause
exit /b 1

:pyinst_failed
echo [错误] PyInstaller 打包失败。
pause
exit /b 1
