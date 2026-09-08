@echo off
REM ---------------------------------------------------------------------------
REM  Opens this project for development:
REM    - VS Code on the repository
REM    - TouchDesigner on the working .toe
REM
REM  Paths are discovered rather than hardcoded so this file can be committed
REM  and still work on another machine. Override either by setting TD_EXE or
REM  CODE_CMD in the environment before running.
REM ---------------------------------------------------------------------------

setlocal enabledelayedexpansion

set "ROOT=%~dp0"
set "ROOT_NB=%ROOT:~0,-1%"
set "TOE=%ROOT%TDPyMovieplayer.toe"

REM --- TouchDesigner ---------------------------------------------------------
if not defined TD_EXE set "TD_EXE=C:\Program Files\Derivative\TouchDesigner\bin\TouchDesigner.exe"
if not exist "!TD_EXE!" (
    for /f "delims=" %%D in ('dir /b /ad /o-n "C:\Program Files\Derivative\TouchDesigner*" 2^>nul') do (
        if not exist "!TD_EXE!" set "TD_EXE=C:\Program Files\Derivative\%%D\bin\TouchDesigner.exe"
    )
)
if not exist "!TD_EXE!" (
    echo [open-project] TouchDesigner not found.
    echo                Set TD_EXE to the full path of TouchDesigner.exe and re-run.
    goto :fail
)

REM --- VS Code ---------------------------------------------------------------
if not defined CODE_CMD for %%C in (code.cmd) do set "CODE_CMD=%%~$PATH:C"
if not defined CODE_CMD set "CODE_CMD=%LOCALAPPDATA%\Programs\Microsoft VS Code\bin\code.cmd"
if not exist "!CODE_CMD!" set "CODE_CMD=C:\Program Files\Microsoft VS Code\bin\code.cmd"

REM --- Launch ----------------------------------------------------------------
if not exist "%TOE%" (
    echo [open-project] Working file not found:
    echo                "%TOE%"
    echo                Generate one with new-project.bat, or edit TOE in this script.
    goto :fail
)

if exist "!CODE_CMD!" (
    echo [open-project] VS Code       "!CODE_CMD!"
    call "!CODE_CMD!" "%ROOT_NB%"
) else (
    echo [open-project] VS Code not found - skipping.
    echo                Set CODE_CMD to override.
)

echo [open-project] TouchDesigner "!TD_EXE!"
echo [open-project] Opening       "%TOE%"
start "" "!TD_EXE!" "%TOE%"

endlocal
exit /b 0

:fail
endlocal
echo.
pause
exit /b 1
