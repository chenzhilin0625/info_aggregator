@echo off
chcp 65001 > nul
REM ============================================================
REM A股日报 - 手动执行（控制台可见输出，执行完后不自动关闭）
REM 双击即可运行
REM ============================================================
setlocal

set PROJECT_DIR=D:\zhihu-finance-analyst
set PYTHON=%PROJECT_DIR%\.venv\Scripts\python.exe

cd /d "%PROJECT_DIR%"

echo.
echo ╔══════════════════════════════════════════════╗
echo ║       A股日报 - 手动执行                      ║
echo ╚══════════════════════════════════════════════╝
echo.

REM 如果没有传参，默认生成昨天的报告
if "%~1"=="" (
    echo 未指定日期，默认生成昨天的报告...
    echo.
    for /f "tokens=2 delims==" %%i in ('wmic os get localdatetime /format:list 2^>nul') do (
        set DT=%%i
        goto :run
    )
    :run
    REM 计算昨天日期
    set TODAY=%DT:~0,4%-%DT:~4,2%-%DT:~6,2%
    echo 今天: %TODAY%
    echo 提示：用昨天的日期去抓取（知乎关注流回溯）
    echo.
    echo ══════════════════════════════════════════════
    echo  按 Enter 开始执行，或关闭窗口取消...
    echo ══════════════════════════════════════════════
    pause > nul
    echo.
    echo 正在执行...
    echo.
    "%PYTHON%" main.py
) else (
    echo 指定日期: %~1
    echo.
    echo ══════════════════════════════════════════════
    echo  按 Enter 开始执行，或关闭窗口取消...
    echo ══════════════════════════════════════════════
    pause > nul
    echo.
    echo 正在执行...
    echo.
    "%PYTHON%" main.py --date %~1
)

echo.
echo ══════════════════════════════════════════════
echo.
if %ERRORLEVEL% EQU 0 (
    echo  ✅ 执行成功！
) else (
    echo  ❌ 执行失败，退出码：%ERRORLEVEL%
)
echo.
echo  报告位置：output\reports\
echo  日志位置：output\logs\
echo.
echo ══════════════════════════════════════════════
echo  按任意键关闭窗口...
pause > nul

endlocal
