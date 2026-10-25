@echo off
rem Optional: turn Launchpad into a single Launchpad.exe that doesn't need Python installed.
setlocal
cd /d "%~dp0"
set "PY=py -3"
where py >nul 2>nul || set "PY=python"

%PY% -m pip install --user --upgrade pyinstaller PySide6
if errorlevel 1 goto fail
%PY% -m PyInstaller --noconfirm --onefile --windowed --name Launchpad ^
    --icon launchpad.ico --add-data "launchpad.ico;." launchpad.pyw
if errorlevel 1 goto fail

echo.
echo Built: %~dp0dist\Launchpad.exe
echo Run it once, then use Settings - Create desktop shortcut.
pause
exit /b 0

:fail
echo Build failed - see the messages above.
pause
exit /b 1
