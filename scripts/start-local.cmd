@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0manage-local.ps1" start %*
exit /b %errorlevel%
