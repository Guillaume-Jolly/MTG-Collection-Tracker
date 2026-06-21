@echo off
setlocal

if not defined HOST set HOST=0.0.0.0
if not defined PORT set PORT=8000

echo Starting MTG Collection Tracker on http://%HOST%:%PORT%
echo Local link: http://localhost:%PORT%
echo Stop with Ctrl+C.

python run_mvp.py --host %HOST% --port %PORT%
