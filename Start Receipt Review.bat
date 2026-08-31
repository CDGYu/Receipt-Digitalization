@echo off
setlocal EnableExtensions

REM ===========================================================================
REM  Receipt Review -- one-click launcher
REM
REM  Double-click this file to start the whole system:
REM    - the FIRST time on a new computer, it sets itself up (creates an
REM      isolated environment and installs what it needs -- needs internet once),
REM    - the queue (Redis), the worker, and the review website all start,
REM    - the FIRST time, it asks you to create a sign-in account (once only),
REM    - your browser opens at the review screen.
REM
REM  Keep the window that appears OPEN while you work. Close it (or press
REM  Ctrl-C in it) to stop everything cleanly.
REM
REM  The only thing you must install yourself is Python (3.11 or newer). This
REM  file checks for it and tells you where to get it if it is missing.
REM ===========================================================================

REM Run from the folder this file lives in, whatever the working directory was.
cd /d "%~dp0"

REM --- 1. Find a Python to bootstrap with -------------------------------------
REM Prefer the Windows 'py' launcher (picks a sane version), then 'python'.
set "PYEXE="
where py >nul 2>nul && set "PYEXE=py"
if not defined PYEXE (
    where python >nul 2>nul && set "PYEXE=python"
)

if not defined PYEXE (
    echo(
    echo   Could not find Python on this computer.
    echo   Install Python 3.11 or newer from https://www.python.org/downloads/
    echo   and be sure to tick "Add Python to PATH" during setup, then run this
    echo   file again.
    echo(
    pause
    exit /b 1
)

REM --- 2. Provision the isolated environment (fast no-op after first run) ------
"%PYEXE%" "scripts\bootstrap.py"
if errorlevel 1 goto setup_failed

REM --- 3. Launch, using the environment's own Python --------------------------
set "VENVPY=.venv\Scripts\python.exe"
if not exist "%VENVPY%" goto no_venv

echo Starting Receipt Review...
echo(

"%VENVPY%" "scripts\launch_app.py"
if errorlevel 1 goto app_failed

goto done

:setup_failed
echo(
echo   Setup did not finish. The lines above explain why.
echo   The most common cause on first run is no internet connection.
echo(
pause
exit /b 1

:no_venv
echo(
echo   The environment is missing its Python at %VENVPY%.
echo   Delete the .venv folder and run this file again to rebuild it.
echo(
pause
exit /b 1

:app_failed
echo(
echo   Receipt Review stopped with a problem.
echo   The lines above explain what happened.
echo(
pause
exit /b 1

:done
endlocal
exit /b 0
