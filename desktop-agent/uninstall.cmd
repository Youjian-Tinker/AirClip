@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1" %*
set EXITCODE=%ERRORLEVEL%
echo.
if not "%EXITCODE%"=="0" (
  echo AirClip uninstall failed with exit code %EXITCODE%.
) else (
  echo AirClip uninstall completed.
)
pause
exit /b %EXITCODE%
