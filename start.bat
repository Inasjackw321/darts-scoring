@echo off
setlocal EnableDelayedExpansion
title AI Vision Dart Scorer
cd /d "%~dp0"

echo ============================================
echo   AI Vision Dart Scorer - starting up
echo ============================================
echo.

REM ---- 1. Python -------------------------------------------------------
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not on your PATH.
    echo         Install Python 3.10+ from https://python.org and tick
    echo         "Add python.exe to PATH" during setup.
    goto :fail
)

REM ---- 2. Virtual environment -----------------------------------------
if not exist "venv\Scripts\activate.bat" (
    echo [setup] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 goto :fail
    REM Force a dependency install on a fresh venv.
    if exist "venv\requirements.hash" del /q "venv\requirements.hash"
)
call venv\Scripts\activate.bat

REM ---- 3. Dependencies, only when requirements.txt changed -------------
set "REQ_HASH="
for /f "skip=1 tokens=1" %%H in ('certutil -hashfile requirements.txt SHA256 ^| findstr /r "^[0-9a-f]"') do (
    if not defined REQ_HASH set "REQ_HASH=%%H"
)
set "OLD_HASH="
if exist "venv\requirements.hash" set /p OLD_HASH=<venv\requirements.hash

if not "!REQ_HASH!"=="!OLD_HASH!" (
    echo [setup] Installing/updating dependencies...
    python -m pip install --upgrade pip >nul
    python -m pip install -r requirements.txt
    if errorlevel 1 goto :fail
    echo !REQ_HASH!>venv\requirements.hash
) else (
    echo [ok] Dependencies already up to date.
)

REM ---- 4. Ollama check (optional - only /verify needs it) --------------
curl -s -m 3 http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
    echo [warn] Ollama is not responding on http://localhost:11434
    echo        Scoring still works - only the AI double-check needs it.
    echo        Start Ollama, then run:  ollama pull llama3.2-vision
) else (
    curl -s -m 3 http://localhost:11434/api/tags | findstr /i "llama3.2-vision" >nul
    if errorlevel 1 (
        echo [warn] Model 'llama3.2-vision' is not pulled yet. Run:
        echo            ollama pull llama3.2-vision
    ) else (
        echo [ok] Ollama is running with llama3.2-vision.
    )
)

REM ---- 5. LAN address --------------------------------------------------
set "LANIP="
for /f "tokens=2 delims=:" %%A in ('ipconfig ^| findstr /c:"IPv4 Address"') do (
    if not defined LANIP set "LANIP=%%A"
)
set "LANIP=!LANIP: =!"
if "!LANIP!"=="" set "LANIP=127.0.0.1"

echo.
echo ============================================
echo   Open this on your phone:
echo       http://!LANIP!:8000
echo   (or enter that address in the app's Settings tab)
echo ============================================
echo.
echo   Windows Firewall may ask to allow Python on the first run.
echo   Tick "Private networks" or the phone will not be able to connect.
echo.

start "" http://localhost:8000/

REM ---- 6. Server -------------------------------------------------------
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
goto :eof

:fail
echo.
echo Startup failed - see the message above.
pause
exit /b 1
