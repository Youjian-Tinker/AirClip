@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set EXITCODE=%ERRORLEVEL%
echo.
if not "%EXITCODE%"=="0" (
  echo AirClip install failed with exit code %EXITCODE%.
) else (
  echo AirClip install completed.
)
pause
exit /b %EXITCODE%
