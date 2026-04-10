@echo off
setlocal

start "PaperReader Backend" cmd /k "conda activate research_tools && uvicorn backend.app.main:app --reload"
start "PaperReader Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

echo PaperReader is starting...
echo Backend:  http://127.0.0.1:8000
echo Frontend: http://127.0.0.1:5173
