@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if not errorlevel 1 (
  python "%~dp0wunderwaffe_scanner.py"
  if errorlevel 1 pause
  exit /b %errorlevel%
)

where python3 >nul 2>nul
if not errorlevel 1 (
  python3 "%~dp0wunderwaffe_scanner.py"
  if errorlevel 1 pause
  exit /b %errorlevel%
)

where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%~dp0wunderwaffe_scanner.py"
  if errorlevel 1 pause
  exit /b %errorlevel%
)

echo Python was not found. Install Python 3.10+ from https://www.python.org/downloads/
echo Make sure to check "Add Python to PATH" during setup.
pause
exit /b 1
