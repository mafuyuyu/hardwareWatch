@echo off
chcp 65001 >nul
cd /d "%~dp0"
python "%~dp0install_autostart.py"
pause
