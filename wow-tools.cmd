@echo off
rem Ka0s WoW Tools: the one way in. Opens the tool menu (or `update`). Needs Python 3.10+.
setlocal
set "PYTHONPATH=%~dp0;%PYTHONPATH%"
where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 -m wowtools %*
) else (
  python -m wowtools %*
)
exit /b %ERRORLEVEL%
