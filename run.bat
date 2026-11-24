@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto :nosetup
".venv\Scripts\python.exe" main.py %*
exit /b %errorlevel%

:nosetup
echo The virtual environment .venv was not found. Run setup.bat first.
pause
exit /b 1
