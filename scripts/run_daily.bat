@echo off
setlocal

set PROJECT_DIR=D:\zhihu-finance-analyst
set PYTHON_HOME=C:\Users\chenzhilin\AppData\Local\Programs\Python\Python311

set PATH=%PYTHON_HOME%;%PATH%

cd /d "%PROJECT_DIR%"
if errorlevel 1 exit /b 1

.venv\Scripts\python.exe main.py 2>> "%PROJECT_DIR%\output\logs\task_stderr.log"

endlocal
exit /b %ERRORLEVEL%
