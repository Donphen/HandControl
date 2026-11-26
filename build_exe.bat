@echo off
REM Builds HandControl.exe. Needs Python 3.10, 3.11 or 3.12 (64-bit) from python.org.
setlocal
cd /d "%~dp0"

py -3.12 -m venv .venv 2>nul || py -3.11 -m venv .venv 2>nul || py -3.10 -m venv .venv
if errorlevel 1 (
  echo Could not create a virtual environment. Install Python 3.10-3.12 first.
  pause & exit /b 1
)
call .venv\Scripts\activate.bat

python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller || (pause & exit /b 1)

pyinstaller --noconfirm --onefile --noconsole --name HandControl ^
  --collect-all mediapipe --hidden-import pystray._win32 hand_control.py || (pause & exit /b 1)

echo.
echo Done. Your program is at: %cd%\dist\HandControl.exe
pause
