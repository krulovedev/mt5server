@echo off
cd /d %~dp0
echo Starting MT5 Monitor Server...
python server.py
pause