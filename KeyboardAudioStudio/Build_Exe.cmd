@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo First run Start_Recorder.cmd once to install the app dependencies.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt "pyinstaller>=6.10,<7"
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --onedir --name KeyboardAudioStudio --collect-all sounddevice --collect-all _sounddevice_data --collect-all imageio_ffmpeg keyboard_audio_studio.py
if errorlevel 1 goto failed
echo.
echo Built: dist\KeyboardAudioStudio\KeyboardAudioStudio.exe
echo Keep the ENTIRE dist\KeyboardAudioStudio folder together when moving the app.
explorer "dist\KeyboardAudioStudio"
pause
exit /b 0
:failed
echo Build failed. Read the error above.
pause
exit /b 1
