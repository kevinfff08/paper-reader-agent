@echo off
chcp 65001 >nul 2>&1
setlocal

REM ============================================================
REM PaperReader - One-click startup script (Windows)
REM Optional: CLIProxyAPI proxy (if LLM_MODE=setup-token in .env)
REM ============================================================

set "ROOT=%~dp0"

REM --- Check .env ---
if not exist "%ROOT%.env" (
    echo [ERROR] .env file not found. Creating from .env.example ...
    copy "%ROOT%.env.example" "%ROOT%.env" >nul
    echo [INFO] Please edit .env to configure your settings, then re-run this script.
    pause
    exit /b 1
)

REM --- Configuration is loaded by Python from the repository .env ---

REM --- Activate conda environment in current shell for preflight check ---
call conda activate research_tools
if errorlevel 1 (
    echo [ERROR] Failed to activate conda env: research_tools
    echo Please ensure conda is installed and research_tools env exists.
    pause
    exit /b 1
)
echo [OK] conda env research_tools activated
echo.

REM --- Proxy readiness is checked by the desktop entry point ---

REM --- Build frontend (desktop app serves frontend/dist) ---
REM Always rebuild so the window never serves a stale bundle after frontend edits.
REM Set PAPERREADER_SKIP_BUILD=1 to skip when you know dist is already current.
pushd "%ROOT%frontend"
if errorlevel 1 exit /b 1
if not exist "node_modules" (
    echo [BUILD] Installing frontend dependencies ...
    call npm install
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed. Startup cancelled.
        popd
        pause
        exit /b 1
    )
)
if /I not "%PAPERREADER_SKIP_BUILD%"=="1" (
    echo [BUILD] Building frontend ...
    call npm run build
    if errorlevel 1 (
        echo [ERROR] Frontend build failed. Startup cancelled; old output will not be used.
        popd
        pause
        exit /b 1
    )
)
popd
if not exist "%ROOT%frontend\dist\index.html" (
    echo [ERROR] Frontend build output not found. Please check npm output above.
    pause
    exit /b 1
)
echo [OK] Frontend ready.
echo.

REM --- Launch the desktop app (in-process FastAPI + native WebView window) ---
echo PaperReader is starting as a desktop app ...
echo Configuration and proxy readiness will be checked before opening the window.
echo.
python "%ROOT%desktop_app.py"
if errorlevel 1 (
    echo [ERROR] PaperReader startup or execution failed. See details above.
    pause
    exit /b 1
)
