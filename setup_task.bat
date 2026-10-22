@echo off
REM ============================================================
REM 一键注册 Windows 任务计划程序
REM 请以管理员权限运行此脚本
REM ============================================================

set TASK_NAME=ZhihuFinanceAnalyst
set PROJECT_DIR=D:\zhihu-finance-analyst
set SCRIPT=%PROJECT_DIR%\scripts\run_daily.bat

echo 正在注册任务计划：%TASK_NAME%
echo 执行时间：每日 23:30
echo 脚本路径：%SCRIPT%
echo.

schtasks /delete /tn "%TASK_NAME%" /f 2>nul

schtasks /create ^
  /tn "%TASK_NAME%" ^
  /tr "\"%SCRIPT%\"" ^
  /sc daily ^
  /st 23:30 ^
  /ru "%USERNAME%" ^
  /rl HIGHEST ^
  /f

if %ERRORLEVEL% EQU 0 (
    echo.
    echo 任务计划注册成功！
    echo    任务名称：%TASK_NAME%
    echo    每日 23:30 自动执行
    echo.
    echo 管理命令：
    echo   查看：schtasks /query /tn "%TASK_NAME%"
    echo   立即运行：schtasks /run /tn "%TASK_NAME%"
    echo   删除：schtasks /delete /tn "%TASK_NAME%" /f
) else (
    echo.
    echo 注册失败，请确保以管理员权限运行此脚本
)

pause
