@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   DiskCleaner 构建脚本 v2.0
echo ============================================
echo.
echo 请选择构建方式：
echo.
echo   [1] Embeddable Python 便携包  (推荐)
echo       不编译、不解压到 %%TEMP%%、AV 误报率最低
echo       适合 Trend Micro / UniAccessAgent 等企业安全环境
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

rem ============ Embeddable Python ============

:build_embeddable
echo.
echo ============================================
echo   方式 1: Embeddable Python 便携包
echo ============================================
echo.

echo [1/5] 检查 Python 环境 ...
where python >nul 2>nul
if errorlevel 1 goto :no_python
python --version
echo.

echo [2/5] 准备目录 ...
set "DEST=dist\DiskCleaner-portable"
if exist "%DEST%" rmdir /s /q "%DEST%"
mkdir "%DEST%\python-embed" 2>nul
echo 目录就绪: %DEST%
echo.

echo [3/5] 下载 Python 3.10.11 embeddable ...
set "EMBED_URL=https://www.python.org/ftp/python/3.10.11/python-3.10.11-embed-amd64.zip"
set "EMBED_ZIP=%TEMP%\python-3.10.11-embed-amd64.zip"
if not exist "%EMBED_ZIP%" (
    python -c "import urllib.request; urllib.request.urlretrieve('%EMBED_URL%', r'%EMBED_ZIP%'); print('下载完成')" || goto :download_failed
) else (
    echo 已存在，跳过下载。
)
python -c "import zipfile; zipfile.ZipFile(r'%EMBED_ZIP%').extractall(r'%DEST%\python-embed'); print('解压完成')" || goto :extract_failed
echo.

echo [4/5] 集成 tkinter (从系统 Python 拷贝) ...
for /f "delims=" %%p in ('python -c "import sys; print(sys.prefix)"') do set "SYS_PY=%%p"
echo 系统 Python: %SYS_PY%

rem 找 DLLs 目录
if exist "%SYS_PY%\DLLs" (set "DLLS=%SYS_PY%\DLLs") else (
    if exist "%SYS_PY%\Lib\DLLs" (set "DLLS=%SYS_PY%\Lib\DLLs") else (
        set "DLLS=%SYS_PY%")
)
echo DLLs: %DLLS%

rem 拷 tkinter C 扩展
copy /y "%DLLS%\_tkinter.pyd" "%DEST%\python-embed\" >nul 2>nul
copy /y "%DLLS%\tcl86t.dll" "%DEST%\python-embed\" >nul 2>nul
copy /y "%DLLS%\tk86t.dll" "%DEST%\python-embed\" >nul 2>nul

rem 拷 tcl/tk 资源目录
if exist "%SYS_PY%\tcl" (
    xcopy "%SYS_PY%\tcl" "%DEST%\python-embed\tcl\" /e /i /q /y >nul 2>nul
) else if exist "%SYS_PY%\Lib\tcl" (
    xcopy "%SYS_PY%\Lib\tcl" "%DEST%\python-embed\tcl\" /e /i /q /y >nul 2>nul
)

rem 拷 tkinter Python 包
if exist "%SYS_PY%\Lib\tkinter" (
    xcopy "%SYS_PY%\Lib\tkinter" "%DEST%\python-embed\Lib\tkinter\" /e /i /q /y >nul 2>nul
)

rem 修改 python310._pth：加路径 + 注释 import site
python -c ^
"p=r'%DEST%\python-embed\python310._pth';c=open(p,'rb').read().decode('utf-8');c=c.replace('.\r\n','.\r\n..\r\nLib\r\n').replace('import site','#import site');open(p,'wb').write(c.encode('utf-8'));print('_pth 配置完成')" || goto :pth_failed
echo.

echo [5/5] 拷贝项目文件 ...
copy /y "main.py" "%DEST%\" >nul
if not exist "%DEST%\src" xcopy "src" "%DEST%\src\" /e /i /q /y >nul
if not exist "%DEST%\data" (
    mkdir "%DEST%\data" 2>nul
    copy /y "data\settings.ini" "%DEST%\data\" >nul 2>nul
    copy /y "data\custom_targets.txt" "%DEST%\data\" >nul 2>nul
)
if exist "assets" xcopy "assets" "%DEST%\assets\" /e /i /q /y >nul 2>nul

rem ---- 定位 MinGW64 gcc（来自 Nuitka 缓存，若无则提示用户装 Nuitka）----
set "GCC="
for /f "delims=" %%p in ('dir /b /s "%LOCALAPPDATA%\Nuitka\Cache\downloads\gcc\*\mingw64\bin\gcc.exe" 2^>nul') do set "GCC=%%p"

if defined GCC (
    echo [6/6] 编译 DiskCleaner.exe 原生启动器 ...
    set "WINDRES=%GCC:gcc.exe=windres.exe%"
    "%WINDRES%" "launcher\launcher.rc" -O coff -o "launcher\launcher.res" 2>nul
    "%GCC%" -mwindows -O2 -o "%DEST%\DiskCleaner.exe" "launcher\launcher.c" "launcher\launcher.res" -luser32 -lkernel32 2>nul
    if exist "%DEST%\DiskCleaner.exe" (
        echo   DiskCleaner.exe 编译完成
    ) else (
        echo   [WARN] 启动器编译失败，将生成 DiskCleaner.bat 作为后备启动器
        goto :gen_bat
    )
) else (
    echo [6/6] 未检测到 MinGW64 gcc，生成 DiskCleaner.bat 作为启动器
    echo   如需 DiskCleaner.exe，先执行方式 2 安装 Nuitka（会自动下载 gcc）
    goto :gen_bat
)
goto :after_launcher

:gen_bat
(
echo @echo off
echo cd /d "%%~dp0"
echo set "TCL_LIBRARY=%%~dp0python-embed\tcl\tcl8.6"
echo set "TK_LIBRARY=%%~dp0python-embed\tcl\tk8.6"
echo start "" "python-embed\pythonw.exe" "main.py"
) > "%DEST%\DiskCleaner.bat"

:after_launcher
rem 打包 zip
if not exist "dist" mkdir dist
cd /d "%DEST%\.."
python -c "import zipfile,os; [os.remove(f) for f in ['DiskCleaner-portable.zip'] if os.path.exists(f)]; z=zipfile.ZipFile('DiskCleaner-portable.zip','w',zipfile.ZIP_DEFLATED); [z.write(os.path.join(r,f), os.path.relpath(os.path.join(r,f), '.')) for r,d,fs in os.walk('DiskCleaner-portable') for f in fs]; z.close(); print('zip 打包完成')" || goto :zip_failed
cd /d "%~dp0"

echo.
echo ============================================
echo   Embeddable 便携包构建成功！
echo ============================================
echo   产物: dist\DiskCleaner-portable.zip
echo   大小: 约 12 MB
echo.
echo   用户解压后双击 DiskCleaner.exe 即可启动，
echo   完全不依赖系统 Python，无需安装。
echo   首次运行会自动生成 data\ 配置目录和日志。
echo ============================================
pause
exit /b 0

rem ============ Nuitka ============

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
  --windows-file-version=1.0.0 ^
  --windows-product-version=1.0.0 ^
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

rem ============ PyInstaller ============

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

:pip_failed
echo [错误] pip 安装失败，请检查网络后重试。
pause
exit /b 1

:download_failed
echo [错误] Python embeddable 下载失败，请检查网络。
pause
exit /b 1

:extract_failed
echo [错误] zip 解压失败。
pause
exit /b 1

:pth_failed
echo [错误] _pth 配置失败。
pause
exit /b 1

:zip_failed
echo [错误] zip 打包失败。
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
