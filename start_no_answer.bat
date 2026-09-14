@echo off
rem ============================================================
rem  CxKitty launcher: start with config(no_answer).yml
rem  (watch video / document points and transcribe, no auto-answering)
rem  Equivalent command:
rem    poetry run python main.py -C "config(no_answer).yml"
rem  Multi-config docs: docs/configuration.md
rem ============================================================
cd /d "%~dp0"
set "CONFIG_FILE=config(no_answer).yml"

if not exist "%CONFIG_FILE%" goto missing

echo [CxKitty] using config: %CONFIG_FILE%
poetry run python main.py -C "%CONFIG_FILE%"
pause
exit /b 0

:missing
echo [ERROR] config file not found: %CONFIG_FILE%
echo Please copy config.yml.example to %CONFIG_FILE% and edit it, then run again.
pause
exit /b 1
