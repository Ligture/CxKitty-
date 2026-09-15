@echo off
rem ============================================================
rem  CxKitty launcher: start with the default config.yml
rem  Use start_no_answer.bat to start with config.no_answer.yml
rem  Equivalent command: poetry run python main.py
rem ============================================================
cd /d "%~dp0"
poetry run python main.py
pause
