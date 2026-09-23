@echo off
REM Double-click to start the bridge. It lives in the tray; the window can be
REM closed without stopping it.
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" -m kite
