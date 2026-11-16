@echo off
chcp 65001 >nul
cd /d "%~dp0"
where pythonw >nul 2>&1
if errorlevel 1 (
  echo 未找到 pythonw.exe，请先安装 Python 3.8+ 并勾选 Add to PATH。
  pause
  exit /b 1
)
start "" pythonw "%~dp0run.pyw"
