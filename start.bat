@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

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

REM --- Load .env into current environment ---
for /f "usebackq tokens=1,* delims==" %%A in ("%ROOT%.env") do (
    set "key=%%A"
    set "value=%%B"
    if defined key (
        echo !key! | findstr /r "^[ ]*#" >nul && (
            REM skip comment lines
        ) || (
            for /f "tokens=* delims= " %%K in ("!key!") do set "key=%%K"
            if defined key set "!key!=!value!"
        )
    )
)

if not defined LLM_PROVIDER set "LLM_PROVIDER=openai"
if not defined LLM_MODE set "LLM_MODE=api-key"
if not defined LLM_PROXY_URL set "LLM_PROXY_URL=http://localhost:8317"

set "ACTIVE_LLM_KEY=CLAUDE_API_KEY"
if /I "%LLM_PROVIDER%"=="openai" set "ACTIVE_LLM_KEY=OPENAI_API_KEY"

echo ============================================
echo   PaperReader - Local Reading Workbench
echo   LLM Provider: %LLM_PROVIDER%
echo   LLM Mode: %LLM_MODE%
echo ============================================
echo.

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

REM --- Start CLIProxyAPI if setup-token mode ---
if /I "%LLM_MODE%"=="setup-token" (
    echo [PROXY] Starting CLIProxyAPI on localhost:8317 ...
    if not exist "C:\cliproxyapi\cli-proxy-api.exe" (
        echo [ERROR] cli-proxy-api.exe not found at C:\cliproxyapi\cli-proxy-api.exe
        echo         Please make sure CLIProxyAPI is installed at C:\cliproxyapi\
        pause
        exit /b 1
    )
    start "CLIProxyAPI" cmd /c "C:\cliproxyapi\cli-proxy-api.exe --config C:\cliproxyapi\config.yaml 2>&1"
    timeout /t 2 /nobreak >nul
    echo [OK] CLIProxyAPI proxy started. Proxy URL: %LLM_PROXY_URL%
    echo.
) else (
    echo [PROXY] Skipping proxy (api-key mode, using %ACTIVE_LLM_KEY% directly)
    echo.
)

REM --- Ensure frontend build exists (desktop app serves frontend/dist) ---
if not exist "%ROOT%frontend\dist\index.html" (
    echo [BUILD] frontend\dist not found. Building frontend ...
    pushd "%ROOT%frontend"
    call npm install
    call npm run build
    popd
    if not exist "%ROOT%frontend\dist\index.html" (
        echo [ERROR] Frontend build failed. Please check npm output above.
        pause
        exit /b 1
    )
    echo [OK] Frontend built.
    echo.
)

REM --- Launch the desktop app (in-process FastAPI + native WebView window) ---
echo PaperReader is starting as a desktop app ...
echo Backend (in-process): http://127.0.0.1:8000
echo.
python "%ROOT%desktop_app.py"
