@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0\.."

where uv >nul 2>nul
if errorlevel 1 (
    echo [ERROR] uv was not found. Install uv and retry.
    exit /b 1
)

echo Running tests...
uv run --with-requirements test/requirements.txt python -m pytest test/scripts -v --tb=short -p no:cacheprovider
set TEST_EXIT_CODE=%ERRORLEVEL%

if not "%TEST_EXIT_CODE%"=="0" (
    echo.
    echo Tests failed. Review the output above.
    exit /b %TEST_EXIT_CODE%
)

echo.
exit /b 0
