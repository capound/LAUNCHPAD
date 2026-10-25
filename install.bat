@echo off
setlocal
cd /d "%~dp0"
title LAUNCHPAD setup
echo.
echo   LAUNCHPAD setup
echo   ---------------
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto nopython

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 goto oldpython

echo   Installing PySide6 - the window toolkit Launchpad uses...
%PY% -m pip install --user --upgrade PySide6
if errorlevel 1 goto pipfail

for /f "delims=" %%i in ('%PY% -c "import sys, os; p = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe'); print(p if os.path.exists(p) else sys.executable)"') do set "PYW=%%i"

echo.
echo   Starting Launchpad and adding a desktop shortcut...
start "" "%PYW%" "%~dp0launchpad.pyw" --install
echo   Done. Press Ctrl+Shift+Space any time to show or hide it.
echo.
timeout /t 6 >nul
exit /b 0

:nopython
echo   Python isn't installed.
echo   Get Python 3.10 or newer from https://www.python.org/downloads/
echo   and tick "Add python.exe to PATH" in the installer, then run this again.
pause
exit /b 1

:oldpython
echo   Launchpad needs Python 3.10 or newer. Update Python, then run this again.
pause
exit /b 1

:pipfail
echo   Installing PySide6 failed. Check your internet connection and try again.
pause
exit /b 1
