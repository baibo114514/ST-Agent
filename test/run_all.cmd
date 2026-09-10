@echo off
setlocal
cd /d "%~dp0.."
uv run --with-requirements test\requirements.txt python -m pytest -q test
exit /b %errorlevel%
