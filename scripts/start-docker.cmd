@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0manage-docker.ps1" start
exit /b %errorlevel%
