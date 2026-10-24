@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 sync_rime.py
  goto done
)
where python >nul 2>nul
if not errorlevel 1 (
  python sync_rime.py
  goto done
)
echo 未找到 Python 3。请安装 Python，或在命令行中运行 python sync_rime.py。
:done
echo.
pause
