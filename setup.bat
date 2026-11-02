@echo off
rem Double-click this file to install or update the portal (it runs setup.ps1).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
echo.
pause
