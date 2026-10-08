@echo off
setlocal
cd /d "%~dp0"
title ChatArchive - Local Workspace
echo ChatArchive is starting. Keep this window open while using the tool.
echo.
if not exist "%~dp0app.py" goto incomplete
if not exist "%~dp0web\index.html" goto incomplete
if not exist "%~dp0relationship.py" goto incomplete
if exist "%~dp0.venv\Scripts\python.exe" goto venv
where py.exe >nul 2>&1
if errorlevel 1 goto python
py -3.12 -c "import sys; sys.exit(0)" >nul 2>&1
if errorlevel 1 goto python
py -3.12 -u "%~dp0app.py" %*
goto finished
:venv
"%~dp0.venv\Scripts\python.exe" -u "%~dp0app.py" %*
goto finished
:python
where python.exe >nul 2>&1
if errorlevel 1 goto missing
python.exe -u "%~dp0app.py" %*
goto finished
:incomplete
echo Required program files are missing.
echo Extract the ENTIRE ZIP first, then run start.cmd from ChatArchiveTool.
echo For an upgrade, merge the upgrade files into the original tool folder.
pause
exit /b 1
:missing
echo Python was not found. This source package requires Windows Python 3.12 x64.
echo Install Python with the launcher or PATH option, then run this file again.
pause
exit /b 1
:finished
if not errorlevel 1 exit /b 0
echo.
echo Startup failed. Read the error above. If available, details are in logs\startup.log.
pause
exit /b 1
