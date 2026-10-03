@echo off
rem Ka0s WoW Tools: the one way in. Opens the tool menu (or `update`). Needs Python 3.10+.
rem cmd.exe reads this file as it runs, and an update may replace it while Python runs. So Python is started on
rem the last line, and that same line exits with Python's exit code: nothing is read from the file afterwards.
rem (setlocal resets ERRORLEVEL, so the code is saved first; delayed expansion is only on after Python returns.)
setlocal
set "PYTHONPATH=%~dp0;%PYTHONPATH%"
set "WOWTOOLS_PY=python"
where py >nul 2>nul && set "WOWTOOLS_PY=py -3"
%WOWTOOLS_PY% -m wowtools %* & call set "WOWTOOLS_RC=%%ERRORLEVEL%%" & setlocal EnableDelayedExpansion & exit /b !WOWTOOLS_RC!
