@echo off
setlocal
cd /d "%~dp0"
title Infinity setup

echo ================================================================
echo  Infinity setup
echo ================================================================
echo.

set "PYCMD="

rem --- 1. find a compatible Python: 3.12 first, then 3.13, then 3.11 ---------
where py >nul 2>&1
if errorlevel 1 goto :trypython
for %%V in (3.12 3.13 3.11) do call :trypy %%V
if defined PYCMD goto :havepython

:trypython
where python >nul 2>&1
if errorlevel 1 goto :nopython
python -c "import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] <= (3, 13) else 1)" >nul 2>&1
if errorlevel 1 goto :nopython
set "PYCMD=python"

:havepython
echo Using this Python:
%PYCMD% -c "import sys; print('  ' + sys.version.split()[0] + '  ' + sys.executable)"
echo.

rem --- 2. tkinter is needed for the code editor window -----------------------
%PYCMD% -c "import tkinter" >nul 2>&1
if errorlevel 1 echo [WARNING] This Python has no tkinter. Re-run the python.org installer and keep "tcl/tk and IDLE" ticked.

rem --- 3. virtual environment ------------------------------------------------
if exist ".venv\Scripts\python.exe" goto :venvexists
echo Creating the virtual environment .venv ...
%PYCMD% -m venv .venv
if errorlevel 1 goto :venverror
goto :install

:venvexists
echo The virtual environment .venv already exists, so it is reused.
echo If it was made with the wrong Python, delete the .venv folder and run setup.bat again.

:install
rem --- 4. packages -----------------------------------------------------------
echo.
echo Installing packages. This can take a few minutes the first time ...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :piperror
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :piperror

rem --- 5. Ollama model -------------------------------------------------------
echo.
where ollama >nul 2>&1
if errorlevel 1 goto :noollama
set "MODEL=qwen3.5:4b"
for /f "delims=" %%M in ('.venv\Scripts\python.exe doctor.py --print-model') do set "MODEL=%%M"
echo Pulling the Ollama model %MODEL% ...
ollama pull %MODEL%
goto :check

:noollama
echo [WARNING] Ollama was not found. Install it from https://ollama.com/download
echo           then run:  ollama pull qwen3.5:4b

:check
echo.
".venv\Scripts\python.exe" doctor.py
echo.
echo ================================================================
echo  Done. Start Infinity with:   run.bat
echo  Terminal mode:               run.bat --cli
echo ================================================================
pause
exit /b 0

:trypy
if defined PYCMD goto :eof
py -%1 -c "import sys" >nul 2>&1
if errorlevel 1 goto :eof
set "PYCMD=py -%1"
goto :eof

:nopython
echo [ERROR] No compatible Python found. Infinity needs Python 3.11, 3.12 or 3.13.
echo.
echo   Easiest fix:   winget install --id Python.Python.3.12 -e
echo   or download:   https://www.python.org/downloads/windows/
echo   Tick "Add python.exe to PATH" and keep "tcl/tk and IDLE" ticked.
echo   Then close this window, open a new one and run setup.bat again.
pause
exit /b 1

:venverror
echo [ERROR] Could not create the virtual environment .venv
pause
exit /b 1

:piperror
echo.
echo [ERROR] Installing the packages failed. Read the red text above.
echo   Common causes: no internet, or a 32-bit or too-new Python.
echo   Run:  .venv\Scripts\python.exe doctor.py   to see what is wrong.
pause
exit /b 1
