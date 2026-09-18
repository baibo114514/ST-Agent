@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0\.."

set "AI_TEST_ENV_FILE=%~dp0.env.local"
if exist "%AI_TEST_ENV_FILE%" (
    for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%AI_TEST_ENV_FILE%") do (
        if not "%%A"=="" set "%%A=%%B"
    )
) else (
    echo [WARN] Local test config was not found: %AI_TEST_ENV_FILE%
)

where uv >nul 2>nul
if errorlevel 1 (
    echo [ERROR] uv was not found. Install uv and retry.
    exit /b 1
)

echo Running tests...
uv run --with-requirements test_ai/requirements.txt python -m pytest test_ai/scripts -v --tb=short -p no:cacheprovider
set TEST_EXIT_CODE=%ERRORLEVEL%

if not "%TEST_EXIT_CODE%"=="0" (
    echo.
    echo Tests failed. Review the output above.
    exit /b %TEST_EXIT_CODE%
)

echo.
exit /b 0
