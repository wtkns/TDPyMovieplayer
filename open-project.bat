@echo off
REM ---------------------------------------------------------------------------
REM  Opens this project for development: TouchDesigner on the working .toe.
REM
REM  It deliberately does NOT launch VS Code, unlike the same file in the
REM  TouchDesigner-Python framework this project was generated from. Work on
REM  this project happens in an editor session that already has the framework
REM  repository open beside it - a session launched from here would not, and
REM  the framework is where shared tdpy files have to be edited.
REM
REM  Paths are discovered rather than hardcoded so this file can be committed
REM  and still work on another machine. Override by setting TD_EXE in the
REM  environment before running.
REM ---------------------------------------------------------------------------

setlocal enabledelayedexpansion

set "ROOT=%~dp0"
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

REM --- Launch ----------------------------------------------------------------
if not exist "%TOE%" (
    echo [open-project] Working file not found:
    echo                "%TOE%"
    echo                Generate one with new-project.bat, or edit TOE in this script.
    goto :fail
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
