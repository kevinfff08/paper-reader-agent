#!/usr/bin/env bash
# ============================================================
# PaperReader - One-click startup script (macOS / Linux)
# Optional: CLIProxyAPI proxy (if LLM_MODE=setup-token in .env)
# Mirrors start.bat for POSIX shells.
# ============================================================
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/"

# --- Check .env ---
if [ ! -f "${ROOT}.env" ]; then
    echo "[ERROR] .env file not found. Creating from .env.example ..."
    cp "${ROOT}.env.example" "${ROOT}.env"
    echo "[INFO] Please edit .env to configure your settings, then re-run this script."
    exit 1
fi

# --- Configuration is loaded by Python from the repository .env ---

# --- Activate conda environment in current shell for preflight check ---
if ! command -v conda >/dev/null 2>&1; then
    echo "[ERROR] conda not found. Please install conda and create the research_tools env."
    exit 1
fi
# `conda activate` is a shell function; make it available in this non-interactive shell.
# shellcheck disable=SC1091
source "$(conda info --base)/etc/profile.d/conda.sh"
if ! conda activate research_tools; then
    echo "[ERROR] Failed to activate conda env: research_tools"
    echo "Please ensure conda is installed and research_tools env exists."
    exit 1
fi
echo "[OK] conda env research_tools activated"
echo

# --- Proxy readiness is checked by the desktop entry point ---

# --- Build frontend (desktop app serves frontend/dist) ---
# Always rebuild so the window never serves a stale bundle after frontend edits.
# Set PAPERREADER_SKIP_BUILD=1 to skip when you know dist is already current.
cd "${ROOT}frontend" || exit 1
if [ ! -d "node_modules" ]; then
    echo "[BUILD] Installing frontend dependencies ..."
    if ! npm install; then
        echo "[ERROR] Dependency installation failed. Startup cancelled."
        exit 1
    fi
fi
if [ "${PAPERREADER_SKIP_BUILD:-0}" != "1" ]; then
    echo "[BUILD] Building frontend ..."
    if ! npm run build; then
        echo "[ERROR] Frontend build failed. Startup cancelled; old output will not be used."
        exit 1
    fi
fi
cd "${ROOT}" || exit 1
if [ ! -f "${ROOT}frontend/dist/index.html" ]; then
    echo "[ERROR] Frontend build output not found. Please check npm output above."
    exit 1
fi
echo "[OK] Frontend ready."
echo

# --- Launch the desktop app (in-process FastAPI + native WebView window) ---
echo "PaperReader is starting as a desktop app ..."
echo "Configuration and proxy readiness will be checked before opening the window."
echo
if ! python "${ROOT}desktop_app.py"; then
    echo "[ERROR] PaperReader startup or execution failed. See details above."
    exit 1
fi
