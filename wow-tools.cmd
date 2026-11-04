@echo off
rem Ka0s WoW Tools: the one way in. Opens the tool menu (or `update`). Needs Python 3.10+.
rem cmd.exe reads this file as it runs, and an update may replace it while Python runs. So Python is started on
rem the last line, and that same line logs the exit, pauses if needed and exits with Python's exit code: nothing is
rem read from the file afterwards. (setlocal resets ERRORLEVEL, so the code is saved first; delayed expansion is only
rem on after Python returns, and the log path is read as !WOWTOOLS_LOG! there, so a "!" in the folder is safe.)
rem Every launch is logged to logs\suite\launcher.log; if that folder can't be written, logging is skipped silently.
setlocal
set "PYTHONPATH=%~dp0;%PYTHONPATH%"
set "WOWTOOLS_LOG=%~dp0logs\suite\launcher.log"
if not exist "%~dp0logs\suite\" mkdir "%~dp0logs\suite" >nul 2>nul
rem Double-clicked: keep the window open on failure. Explorer or a shortcut runs cmd.exe /c ""<this script>" ", with
rem a space and a quote after the script's name; PowerShell and scripts run cmd.exe /c with the name too, never so.
set "WOWTOOLS_DBLCLICK="
setlocal EnableDelayedExpansion
set "WOWTOOLS_CL=!cmdcmdline!"
set "WOWTOOLS_CUT=!WOWTOOLS_CL:%~nx0" "=!"
set "WOWTOOLS_DC="
if /i not "!WOWTOOLS_CUT!"=="!WOWTOOLS_CL!" if /i not "!WOWTOOLS_CL:/c=!"=="!WOWTOOLS_CL!" set "WOWTOOLS_DC=1"
endlocal & set "WOWTOOLS_DBLCLICK=%WOWTOOLS_DC%"
set "WOWTOOLS_PY=python"
where py >nul 2>nul && set "WOWTOOLS_PY=py -3"
(>>"%WOWTOOLS_LOG%" echo %date% %time% launcher.started python=%WOWTOOLS_PY% platform=windows args=%*) 2>nul
rem The Python check: 0 = fine, 3 = too old, anything else (9009: not found, or the Microsoft Store placeholder) = none.
call %WOWTOOLS_PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 3)" >nul 2>nul
set "WOWTOOLS_CHECK=%ERRORLEVEL%"
if "%WOWTOOLS_CHECK%"=="0" goto :run
set "WOWTOOLS_FOUND=unknown"
if "%WOWTOOLS_CHECK%"=="3" for /f "delims=" %%v in ('call %WOWTOOLS_PY% -c "import sys; sys.stdout.write('.'.join(map(str, sys.version_info[:2])))" 2^>nul') do set "WOWTOOLS_FOUND=%%v"
if "%WOWTOOLS_CHECK%"=="3" (
    (>>"%WOWTOOLS_LOG%" echo %date% %time% launcher.python_too_old found=%WOWTOOLS_FOUND% python=%WOWTOOLS_PY%) 2>nul
    echo Ka0s WoW Tools needs Python 3.10 or newer, but "%WOWTOOLS_PY%" is Python %WOWTOOLS_FOUND%.
) else (
    set "WOWTOOLS_CHECK=9009"
    (>>"%WOWTOOLS_LOG%" echo %date% %time% launcher.python_missing python=%WOWTOOLS_PY%) 2>nul
    echo Ka0s WoW Tools needs Python 3.10 or newer, and no Python was found: "%WOWTOOLS_PY%" did not run.
)
echo Install it as README.md describes under "Installing Python", then start wow-tools again.
(>>"%WOWTOOLS_LOG%" echo %date% %time% launcher.exited code=%WOWTOOLS_CHECK%) 2>nul
if defined WOWTOOLS_DBLCLICK echo. & echo Press any key to close this window. & pause >nul
exit /b %WOWTOOLS_CHECK%
:run
%WOWTOOLS_PY% -m wowtools %* & call set "WOWTOOLS_RC=%%ERRORLEVEL%%" & setlocal EnableDelayedExpansion & (>>"!WOWTOOLS_LOG!" echo !date! !time! launcher.exited code=!WOWTOOLS_RC!) 2>nul & (if !WOWTOOLS_RC! neq 0 if defined WOWTOOLS_DBLCLICK echo. & echo Press any key to close this window. & pause >nul) & exit /b !WOWTOOLS_RC!
