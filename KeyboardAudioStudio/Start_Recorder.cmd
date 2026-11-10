@echo off
setlocal
cd /d "%~dp0"
if exist "dist\KeyboardAudioStudio\KeyboardAudioStudio.exe" (
    start "" "dist\KeyboardAudioStudio\KeyboardAudioStudio.exe"
    exit /b
)
if exist ".venv\Scripts\python.exe" goto deps
py -3.12 --version >nul 2>&1
if not errorlevel 1 (
    py -3.12 -m venv .venv
    goto created
)
py -3 --version >nul 2>&1
if not errorlevel 1 (
    py -3 -m venv .venv
    goto created
)
python --version >nul 2>&1
if not errorlevel 1 (
    python -m venv .venv
    goto created
)
echo Install Python 3.12 64-bit from https://www.python.org/downloads/windows/
echo Include the Python launcher and Tcl/Tk. Then double-click this file again.
pause
exit /b 1
:created
if not exist ".venv\Scripts\python.exe" goto failed
:deps
if exist ".venv\recorder-ready" goto run
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -c "import numpy, sounddevice, xlsxwriter, imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"
if errorlevel 1 goto failed
type nul > ".venv\recorder-ready"
:run
".venv\Scripts\python.exe" keyboard_audio_studio.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo.
echo Startup failed. Read the error above. Check your Python installation and internet connection.
pause
exit /b 1
