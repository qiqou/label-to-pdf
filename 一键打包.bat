@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title 一键打包 快递单转PDF

:: ============================================================
::  一键打包脚本
::  双击运行，自动装依赖 + 打包成 exe
:: ============================================================

set "SELF=%~dp0"

echo ╔═══════════════════════════════════════════╗
echo ║       快递单转PDF — 一键打包工具          ║
echo ╚═══════════════════════════════════════════╝
echo.
echo  本脚本将：
echo    1. 检查 Python 环境
echo    2. 安装依赖（PySide6 + qdarkstyle + pyinstaller）
echo    3. 打包成单一 exe 文件
echo    4. 告诉你 exe 在哪
echo.

:: ============================================================
::  1. 检查 Python
:: ============================================================
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 没找到 Python！
    echo  请先安装 Python 3.10+，安装时勾选「Add Python to PATH」
    echo  下载地址：https://www.python.org/downloads/
    pause
    exit /b 1
)

python -c "import sys; v=sys.version_info; assert v.major==3 and v.minor>=8, '需 Python 3.8+'"
if %errorlevel% neq 0 (
    echo [错误] Python 版本太旧，需要 3.8 或更高
    pause
    exit /b 1
)

echo  ✓ Python 环境就绪
echo.

:: ============================================================
::  2. 安装依赖
:: ============================================================
echo  [1/3] 安装 PySide6 ...
pip install PySide6 -q
if %errorlevel% neq 0 (
    echo [错误] PySide6 安装失败，尝试用 pip3 ...
    pip3 install PySide6 -q
    if %errorlevel% neq 0 (
        echo [错误] 还是装不上。试试手动跑：pip install PySide6
        pause
        exit /b 1
    )
)
echo  ✓ PySide6 安装完成

echo  [2/3] 安装 qdarkstyle ...
pip install qdarkstyle -q
echo  ✓ qdarkstyle 安装完成

echo  [3/3] 安装 pyinstaller ...
pip install pyinstaller -q
echo  ✓ pyinstaller 安装完成
echo.

:: ============================================================
::  3. 打包
:: ============================================================
echo  ⏳ 正在打包，持续时间 1-3 分钟...
echo.

pyinstaller --onefile --windowed --name "快递单转PDF" --noconfirm --distpath "%SELF%打包完成" "%SELF%main.py" 2>&1

if %errorlevel% neq 0 (
    echo [错误] 打包失败！请检查 main.py 是否存在
    echo  确保 main.py 和本打包脚本在同一文件夹
    pause
    exit /b 1
)

:: ============================================================
::  4. 完成
:: ============================================================
echo.
echo ╔═══════════════════════════════════════════╗
echo ║        打包成功！                         ║
echo ║                                          ║
echo ║  exe 文件：                               ║
echo ║  %SELF%打包完成\快递单转PDF.exe           ║
echo ║                                          ║
echo ║  使用方式：                               ║
echo ║  1. 把 exe 复制到 ImageMagick exe 同目录  ║
echo ║  2. 双击运行                             ║
echo ║  3. 加桌面快捷方式更方便                  ║
echo ╚═══════════════════════════════════════════╝
echo.
echo  临时文件（build 文件夹、spec 文件）可以删除。
echo.

start "" "%SELF%打包完成"
pause
