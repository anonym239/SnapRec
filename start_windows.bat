@echo off
rem SnapRec starten (Quellcode-Version). Fehlt Python, wird es automatisch installiert.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_windows.ps1" %*
if errorlevel 1 pause
