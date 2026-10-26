@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
set "RUNNER="
where py >nul 2>nul
if not errorlevel 1 set "RUNNER=py -3"
if not defined RUNNER (
  where python >nul 2>nul
  if not errorlevel 1 set "RUNNER=python"
)
if defined RUNNER (
  %RUNNER% sync_rime.py
) else (
  echo 未找到 Python 3。请安装 Python，或在命令行中运行 python sync_rime.py。
)
echo.
pause
