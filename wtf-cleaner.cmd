@echo off
rem Ka0s WoW Tools: WTF Cleaner. Needs Python 3.10+ (uses the py launcher when present).
setlocal
set "PYTHONPATH=%~dp0;%PYTHONPATH%"
where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 -m wowtools wtf-cleaner %*
) else (
  python -m wowtools wtf-cleaner %*
)
exit /b %ERRORLEVEL%
