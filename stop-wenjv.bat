@echo off
setlocal EnableExtensions
echo Stopping wenjv-backend / wenjv-frontend windows if present...
taskkill /FI "WINDOWTITLE eq wenjv-backend*" /T /F 1>nul 2>nul
taskkill /FI "WINDOWTITLE eq wenjv-frontend*" /T /F 1>nul 2>nul
taskkill /FI "WINDOWTITLE eq wenjv-Backend*" /T /F 1>nul 2>nul
taskkill /FI "WINDOWTITLE eq wenjv-Frontend*" /T /F 1>nul 2>nul
rem Also clean up legacy windows if any exist
taskkill /FI "WINDOWTITLE eq KB-Backend*" /T /F 1>nul 2>nul
taskkill /FI "WINDOWTITLE eq KB-Frontend*" /T /F 1>nul 2>nul

rem Also free common ports if orphan python left listening
for %%P in (8000 8001 8002 8003 5173) do (
  for /f "tokens=5" %%a in ('netstat -ano ^| findstr /R /C:":%%P .*LISTENING"') do (
    echo Killing PID %%a on port %%P
    taskkill /F /PID %%a 1>nul 2>nul
  )
)

echo Done. If windows remain, close them manually.
pause
endlocal
