@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "ROOT=%CD%"
set "VENV_PY=%ROOT%\venv\Scripts\python.exe"
set "VENV_ACT=%ROOT%\venv\Scripts\activate.bat"
set "HELPER=%ROOT%\start\kb_launcher.py"
set "RUNTIME_ENV=%ROOT%\start\kb_runtime.env"
set "BACKEND_HOST=127.0.0.1"
set "BACKEND_PORT_START=8000"
set "FRONTEND_PORT=5173"
set "CONF_DIR="
for /f "usebackq delims=" %%i in (`"%VENV_PY%" -c "import sys; sys.path.insert(0, r'%ROOT%'); from start.kb_launcher import get_config_dir; print(get_config_dir())"`) do set "CONF_DIR=%%i"
if not defined CONF_DIR (
  set "CONF_DIR=%USERPROFILE%\.config\wenjv"
  if not exist "%CONF_DIR%\backend.env" if not exist "%CONF_DIR%\wenjv.db" if not exist "%CONF_DIR%\inquisitive.db" (
    if exist "%USERPROFILE%\.config\inquisitive\inquisitive.db" set "CONF_DIR=%USERPROFILE%\.config\inquisitive"
    if exist "%USERPROFILE%\.config\inquisitive\backend.env" set "CONF_DIR=%USERPROFILE%\.config\inquisitive"
  )
)
set "ENV_FILE=%CONF_DIR%\backend.env"
set "FE_ENV=%CONF_DIR%\frontend.env"
set "WEB_DIR=%ROOT%\web"

echo.
echo ========================================
echo   Personal KB launcher (Vue SPA)
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

if not exist "%HELPER%" (
  echo [ERROR] missing helper:
  echo   %HELPER%
  pause
  exit /b 1
)

if not exist "%WEB_DIR%\package.json" (
  echo [ERROR] Vue app missing: %WEB_DIR%
  pause
  exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
  echo [ERROR] npm not found on PATH. Install Node.js LTS.
  pause
  exit /b 1
)

"%VENV_PY%" -c "import uvicorn, fastapi" 1>nul 2>nul
if errorlevel 1 (
  echo [INFO] installing backend deps: pip install -e .
  "%VENV_PY%" -m pip install -e .
  if errorlevel 1 (
    echo [ERROR] pip install failed
    pause
    exit /b 1
  )
)

if not exist "%WEB_DIR%\node_modules\" (
  echo [INFO] npm install in web\
  pushd "%WEB_DIR%"
  call npm install
  if errorlevel 1 (
    popd
    echo [ERROR] npm install failed
    pause
    exit /b 1
  )
  popd
)

if exist "%ENV_FILE%" (
  echo [OK] backend config: %ENV_FILE%
) else (
  echo [WARN] missing backend config:
  echo   %ENV_FILE%
  echo Fill Provider keys before cloud demo.
)

if exist "%RUNTIME_ENV%" del /f /q "%RUNTIME_ENV%" >nul 2>&1

echo [..] selecting backend port and syncing frontend API_URL...
"%VENV_PY%" "%HELPER%" prepare --host %BACKEND_HOST% --start %BACKEND_PORT_START% --count 30 --out "%RUNTIME_ENV%"
if errorlevel 1 (
  echo [ERROR] prepare failed - could not pick a free backend port
  pause
  exit /b 1
)
if not exist "%RUNTIME_ENV%" (
  echo [ERROR] runtime env not written: %RUNTIME_ENV%
  pause
  exit /b 1
)

for /f "usebackq tokens=1,* delims==" %%A in ("%RUNTIME_ENV%") do (
  if /I "%%A"=="BACKEND_PORT" set "BACKEND_PORT=%%B"
  if /I "%%A"=="API_URL" set "API_URL=%%B"
)

if not defined BACKEND_PORT (
  echo [ERROR] BACKEND_PORT missing in %RUNTIME_ENV%
  type "%RUNTIME_ENV%"
  pause
  exit /b 1
)
if not defined API_URL set "API_URL=http://%BACKEND_HOST%:%BACKEND_PORT%"

echo [OK] backend port: %BACKEND_PORT%
echo [OK] API_URL: %API_URL%
echo [OK] frontend.env synced: %FE_ENV%

echo.
echo [1/2] start backend %API_URL%
start "KB-Backend" cmd /k cd /d "%ROOT%" ^& call "%VENV_ACT%" ^& title KB-Backend ^& echo API_URL=%API_URL% ^& "%VENV_PY%" -m uvicorn backend.main:app --host %BACKEND_HOST% --port %BACKEND_PORT% --log-level info

echo Waiting for backend health...
"%VENV_PY%" "%HELPER%" wait-health --url "%API_URL%/health" --timeout 60
if errorlevel 1 (
  echo.
  echo [ERROR] Backend did not become ready: %API_URL%/health
  echo Look at the KB-Backend window for bind/import errors.
  echo Frontend was NOT started.
  echo Try: stop-kb.bat then start-kb.bat again.
  pause
  exit /b 1
)

echo.
echo [2/2] start Vue frontend http://127.0.0.1:%FRONTEND_PORT%
rem Vite proxies /api -^> backend via VITE_PROXY_TARGET
start "KB-Frontend" cmd /k cd /d "%WEB_DIR%" ^& title KB-Frontend ^& set "VITE_PROXY_TARGET=%API_URL%" ^& npm run dev -- --host 127.0.0.1 --port %FRONTEND_PORT%

timeout /t 3 /nobreak >nul

echo Opening browser...
start "" "http://127.0.0.1:%FRONTEND_PORT%"
start "" "%API_URL%/docs"

echo.
echo Done. Keep KB-Backend and KB-Frontend windows open.
echo   Backend:  %API_URL%
echo   Frontend: http://127.0.0.1:%FRONTEND_PORT%  (Vue)
echo   FE env:   %FE_ENV%
echo Stop: close those two windows or run stop-kb.bat
echo.
pause
endlocal
