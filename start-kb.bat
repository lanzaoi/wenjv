@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "ROOT=%CD%"
set "VENV_PY=%ROOT%\venv\Scripts\python.exe"
set "VENV_ACT=%ROOT%\venv\Scripts\activate.bat"
set "BACKEND_PORT=8000"
set "FRONTEND_PORT=8501"
set "ENV_FILE=%USERPROFILE%\.config\inquisitive\backend.env"

echo.
echo ========================================
echo   Personal KB launcher
echo   ROOT=%ROOT%
echo ========================================
echo.

if not exist "%VENV_PY%" (
  echo [ERROR] venv python not found:
  echo   %VENV_PY%
  echo Create venv then: pip install -e .
  pause
  exit /b 1
)

"%VENV_PY%" -c "import uvicorn, streamlit, fastapi" 1>nul 2>nul
if errorlevel 1 (
  echo [INFO] installing deps: pip install -e .
  "%VENV_PY%" -m pip install -e .
  if errorlevel 1 (
    echo [ERROR] pip install failed
    pause
    exit /b 1
  )
)

if exist "%ENV_FILE%" (
  echo [OK] config: %ENV_FILE%
) else (
  echo [WARN] missing config file:
  echo   %ENV_FILE%
  echo Fill Provider keys before cloud demo.
)

echo.
echo [1/2] start backend http://127.0.0.1:%BACKEND_PORT%
start "KB-Backend" cmd /k cd /d "%ROOT%" ^& call "%VENV_ACT%" ^& title KB-Backend ^& "%VENV_PY%" -m uvicorn backend.main:app --host 127.0.0.1 --port %BACKEND_PORT% --log-level info

timeout /t 3 /nobreak >nul

echo [2/2] start frontend http://127.0.0.1:%FRONTEND_PORT%
start "KB-Frontend" cmd /k cd /d "%ROOT%" ^& call "%VENV_ACT%" ^& title KB-Frontend ^& set STREAMLIT_BROWSER_GATHER_USAGE_STATS=false ^& set STREAMLIT_SERVER_HEADLESS=true ^& "%VENV_PY%" -m streamlit run frontend\app.py --server.port %FRONTEND_PORT% --server.address 127.0.0.1

timeout /t 4 /nobreak >nul

echo Opening browser...
start "" "http://127.0.0.1:%FRONTEND_PORT%"
start "" "http://127.0.0.1:%BACKEND_PORT%/redoc"

echo.
echo Done. Keep KB-Backend and KB-Frontend windows open.
echo Stop: close those two windows or run stop-kb.bat
echo Config: %ENV_FILE%
echo.
pause
endlocal
