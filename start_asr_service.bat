@echo off
rem ============================================================
rem  CxKitty transcription service (out-of-process ASR model)
rem  Start this FIRST, then run one or more main.py instances with
rem  "transcript.mode: service" in their config to share one model.
rem  Equivalent command:
rem    poetry run python -m transcript.server
rem  Extra args are forwarded, e.g.:
rem    start_asr_service.bat --port 8765 --token my-secret
rem ============================================================
cd /d "%~dp0"
echo [CxKitty] starting transcription service (Ctrl+C to stop)
poetry run python -m transcript.server %*
pause