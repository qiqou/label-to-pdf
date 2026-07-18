@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title 快递单批量转PDF v2

:: ==== 调试：去掉下面的 rem 可看错误信息 ====
rem @echo on
rem pause

:: =====================================================================
::  首次设置区 — 改完保存，之后双击即用
:: =====================================================================
set "SHARPEN=0x3.0"           :: 锐化强度（0x3.0=中等）
set "FUZZ=5"                  :: 裁边灵敏度（5=连浅灰背景一起裁）
:: =====================================================================

set "SELF=%~dp0"
set "MAGICK=%SELF%ImageMagick-7.1.1-29-Q16-HDRI-x64-static.exe"
set "TODAY=%DATE:~0,4%%DATE:~5,2%%DATE:~8,2%"

if not exist "%MAGICK%" (
    echo ╔══════════════════════════════════╗
    echo ║   [错误] 找不到 ImageMagick！    ║
    echo ║   请把脚本和 exe 放一起          ║
    echo ╚══════════════════════════════════╝
    pause & exit /b 1
)

:: =====================================================================
::  第一步：选面单尺寸
:: =====================================================================
cls
echo ╔══════════════════════════════════════════╗
echo ║         快递单批量转PDF v2               ║
echo ║    优化：自动裁边+黑白+裁切+合并         ║
echo ╚══════════════════════════════════════════╝
echo.
echo  请选择面单尺寸（热敏打印机建议 203 DPI）：
echo.
echo     [1] 标准快递面单  100×150mm  @203DPI  (800×1200)
echo     [2] 小号面单       76×130mm  @203DPI  (608×1040)
echo     [3] 自定义尺寸
echo     [4] 保持原图尺寸，不缩放
echo.
set /p "SIZE_CHOICE=请输入数字 (1-4)，默认 1："
if "!SIZE_CHOICE!"=="" set SIZE_CHOICE=1

if "!SIZE_CHOICE!"=="1" set WIDTH=800 & set HEIGHT=1200 & set DPI=203
if "!SIZE_CHOICE!"=="2" set WIDTH=608 & set HEIGHT=1040 & set DPI=203
if "!SIZE_CHOICE!"=="3" (
    set /p "WIDTH=请输入宽度（像素）："
    set /p "HEIGHT=请输入高度（像素）："
    set /p "DPI=请输入分辨率（203 或 300）："
)
if "!SIZE_CHOICE!"=="4" set WIDTH=0 & set HEIGHT=0 & set DPI=203

:: =====================================================================
::  第二步：选输出模式
:: =====================================================================
echo.
echo  输出模式：
echo     [1] 每张图片单独输出 PDF
echo     [2] 合并成一个多页 PDF ← 推荐（一次打印全部）
echo.
set /p "MERGE_CHOICE=请输入数字 (1-2)，默认 2："
if "!MERGE_CHOICE!"=="" set MERGE_CHOICE=2
echo.

:: =====================================================================
::  第三步：扫描图片
:: =====================================================================
echo  正在扫描图片 ...

set COUNT=0
for /f "delims=" %%F in ('dir /b /on "%SELF%*.png" "%SELF%*.jpg" "%SELF%*.jpeg" "%SELF%*.bmp" "%SELF%*.webp" 2^>nul') do (
    set /a COUNT+=1
)
if !COUNT!==0 (
    echo   [没找到图片] 把图片放到本文件同目录下再运行。
    pause & exit /b 0
)
echo   找到 !COUNT! 张图片
echo.

:: =====================================================================
::  第四步：执行转化
:: =====================================================================

:: 构建 resize 参数（原图模式不加 -resize）
set RESIZE_ARGS=
if not "!WIDTH!"=="0" set "RESIZE_ARGS=-resize !WIDTH!x!HEIGHT!"

set "OUTDIR=%SELF%PDF输出_%TODAY%"
if not exist "!OUTDIR!" mkdir "!OUTDIR!"

:: ──── 模式A：每张单独 PDF ────
if not "!MERGE_CHOICE!"=="2" (

    set PROGRESS=0
    for /f "delims=" %%F in ('dir /b /on "%SELF%*.png" "%SELF%*.jpg" "%SELF%*.jpeg" "%SELF%*.bmp" "%SELF%*.webp" 2^>nul') do (
        set /a PROGRESS+=1
        echo [!PROGRESS!/!COUNT!] %%~nF ...
        "%MAGICK%" "%%F" ^
            -trim -fuzz !FUZZ!%% ^
            !RESIZE_ARGS! ^
            -unsharp !SHARPEN! ^
            -colorspace Gray ^
            -threshold 50%% ^
            -type Bilevel ^
            -density !DPI! -units PixelsPerInch ^
            "!OUTDIR!\%%~nF.pdf"
        if !errorlevel! equ 0 (echo   ✓ 完成) else (echo   ✗ 失败)
        echo.
    )
    goto finish
)

:: ──── 模式B：合并为多页 PDF ────
set "TMPDIR=%SELF%__tmp_%TODAY%"
if exist "!TMPDIR!" rmdir /s /q "!TMPDIR!"
mkdir "!TMPDIR!"

set PROGRESS=0
for /f "delims=" %%F in ('dir /b /on "%SELF%*.png" "%SELF%*.jpg" "%SELF%*.jpeg" "%SELF%*.bmp" "%SELF%*.webp" 2^>nul') do (
    set /a PROGRESS+=1
    echo [!PROGRESS!/!COUNT!] %%~nF ...
    "%MAGICK%" "%%F" ^
        -trim -fuzz !FUZZ!%% ^
        !RESIZE_ARGS! ^
        -unsharp !SHARPEN! ^
        -colorspace Gray ^
        -threshold 50%% ^
        -type Bilevel ^
        -density !DPI! -units PixelsPerInch ^
        "!TMPDIR!\%%~nF.png"
    if !errorlevel! equ 0 (echo   ✓ OK) else (echo   ✗ 失败)
    echo.
)

echo  正在合并为一个 PDF ...
echo.
"%MAGICK%" "!TMPDIR!\*.png" -adjoin "!OUTDIR!\全部面单.pdf"
if !errorlevel! equ 0 (
    echo   ✓ 合并完成 → 全部面单.pdf（共 !COUNT! 页）
) else (
    echo   ✗ 合并失败，请检查是否有图片处理出错
)

rmdir /s /q "!TMPDIR!"

:: =====================================================================
::  完成
:: =====================================================================
:finish
echo.
echo ╔═══════════════════════════════════════════╗
echo ║     全部完成！                            ║
echo ║     输出目录：!OUTDIR!   ║
echo ╚═══════════════════════════════════════════╝
start "" "!OUTDIR!"
echo.
pause
endlocal
