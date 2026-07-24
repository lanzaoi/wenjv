@echo off
setlocal EnableExtensions
echo Stopping KB-Backend / KB-Frontend windows if present...
taskkill /FI "WINDOWTITLE eq KB-Backend*" /T /F 1>nul 2>nul
taskkill /FI "WINDOWTITLE eq KB-Frontend*" /T /F 1>nul 2>nul
echo If windows remain, close them manually.
pause
endlocal
