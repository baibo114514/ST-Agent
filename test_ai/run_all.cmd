@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0.."

set "AI_TEST_ENV_FILE=%~dp0.env.local"
if exist "%AI_TEST_ENV_FILE%" (
    for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%AI_TEST_ENV_FILE%") do (
        if not "%%A"=="" set "%%A=%%B"
    )
) else (
    echo [WARN] Local test config was not found: %AI_TEST_ENV_FILE%
    echo [WARN] Copy test_ai\.env.example to test_ai\.env.local first.
)

where uv >nul 2>nul
if errorlevel 1 (
    echo [ERROR] uv was not found. Install uv and add it to PATH first.
    exit /b 1
)

echo [INFO] Running ST-Agent module 2 AI tests...
uv run --with-requirements test_ai\requirements.txt python -m pytest test_ai\scripts -v --tb=short -p no:cacheprovider --strict-markers
set "test_exit_code=%errorlevel%"

if not "%test_exit_code%"=="0" (
    echo [ERROR] AI tests failed. Review the failed case output above.
) else (
    echo [OK] All AI tests passed.
)

exit /b %test_exit_code%