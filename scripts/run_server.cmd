@echo off
rem Start the HandOver server on Windows from cmd.exe or a double-click. Runs scripts\run_server.ps1;
rem environment variables pass through (set HANDOVER_CHECK=mock & scripts\run_server.cmd).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_server.ps1" %*
exit /b %ERRORLEVEL%
