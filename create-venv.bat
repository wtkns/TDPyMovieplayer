@echo off
REM ---------------------------------------------------------------------------
REM  Creates this project's Python virtual environment.
REM
REM  Runs Derivative's TDPyEnvManagerHelper as a standalone script - the same
REM  code the tdPyEnvManager palette component uses, but with the environment
REM  name passed in rather than derived from the folder. The component names the
REM  environment after whatever directory contains the project and offers no
REM  override, which is wrong as soon as that directory is named for something
REM  other than the project.
REM
REM  The helper writes TDPyEnvManagerContext.json into the working directory, so
REM  this runs from the repository root. Override the TouchDesigner install by
REM  setting TD_ROOT before running.
REM
REM  A console window opens at the end with the environment activated - that is
REM  the helper's own doing, not this script's. Close it.
REM ---------------------------------------------------------------------------

setlocal enabledelayedexpansion

set "ROOT=%~dp0"
set "ROOT_NB=%ROOT:~0,-1%"
set "ENV_NAME=TDPyMovieplayer_vEnv"
set "PY_VERSION=3.11"

REM --- TouchDesigner ---------------------------------------------------------
REM  Discovered rather than hardcoded, the same way open-project.bat does it, so
REM  this file can be committed and still work on another machine.
if not defined TD_ROOT set "TD_ROOT=C:\Program Files\Derivative\TouchDesigner"
if not exist "!TD_ROOT!\bin\python.exe" (
    for /f "delims=" %%D in ('dir /b /ad /o-n "C:\Program Files\Derivative\TouchDesigner*" 2^>nul') do (
        if not exist "!TD_ROOT!\bin\python.exe" set "TD_ROOT=C:\Program Files\Derivative\%%D"
    )
)
if not exist "!TD_ROOT!\bin\python.exe" (
    echo [create-venv] TouchDesigner not found.
    echo               Set TD_ROOT to the install folder and re-run.
    goto :fail
)

REM  The helper must run under TouchDesigner's own interpreter: it imports
REM  requests and yaml at module scope, and the environment it builds is only
REM  useful if it matches the Python the project will actually run under.
set "HELPER=!TD_ROOT!\bin\Lib\tdutils\TDPyEnvManagerHelper.py"
if not exist "!HELPER!" (
    echo [create-venv] TDPyEnvManagerHelper.py not found at:
    echo               "!HELPER!"
    echo               It ships with TouchDesigner 2023.30000 and newer.
    goto :fail
)

echo [create-venv] TouchDesigner "!TD_ROOT!"
echo [create-venv] Environment   "!ENV_NAME!"
echo [create-venv] In            "%ROOT_NB%"

REM  The helper asks "Clean install? [Y/N]" unless --clean is passed, so it will
REM  not run unattended with nothing on stdin. Answering N is the safer of the
REM  two ways to silence it. Passing --clean would work too - Derivative's own
REM  sample .bat does exactly that - but --clean means "empty the install path",
REM  and here that path is the repository root. Today it is read only in the
REM  Conda branch, so passing it would do nothing; if that ever changes it would
REM  delete the project. Answering the prompt cannot.
pushd "%ROOT_NB%"
echo N| "!TD_ROOT!\bin\python.exe" "!HELPER!" --mode "Python vEnv" --installPath "%ROOT_NB%" --envName "!ENV_NAME!" --pythonVersion "%PY_VERSION%"
set "RESULT=%ERRORLEVEL%"

REM  The helper writes "active": false - it records self.Ready, which the CLI
REM  path never sets. TouchDesigner reads that flag at startup and skips linking
REM  the environment, so the first launch after creating one would come up
REM  without it. Verified rather than assumed: a launch with false did not link,
REM  the next with true did. Flip it here so no project ever starts cold.
if "!RESULT!"=="0" if exist "TDPyEnvManagerContext.json" (
    "!TD_ROOT!\bin\python.exe" -c "import json,pathlib;p=pathlib.Path('TDPyEnvManagerContext.json');d=json.loads(p.read_text());d['active']=True;p.write_text(json.dumps(d,indent=4))"
)
popd

endlocal & exit /b %RESULT%

:fail
endlocal
echo.
pause
exit /b 1
