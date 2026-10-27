@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-windows.ps1"
if errorlevel 1 (
  echo Installation failed. Read the message above.
) else (
  echo Installation complete. Open start.bat to launch.
)
pause
