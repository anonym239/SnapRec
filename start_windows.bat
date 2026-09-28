@echo off
cd /d "%~dp0"
if not exist .venv (
  echo Erster Start: Pakete werden installiert ...
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install -q -r requirements.txt
)
start "" .venv\Scripts\pythonw snaprec.py %*
