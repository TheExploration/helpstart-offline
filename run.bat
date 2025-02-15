
:: Bootstrap responsible for downloading and setting up all required dependencies
:: Author: musava_ribica
:: License: GNU GPL v3

@echo off
setlocal enabledelayedexpansion

set PYTHON_EXE=
set NODE_EXE=
set NPM_EXE=

set USEPORTABLE=false
set DEBUG=false

:: Parse arguments
:parse_args
if "%~1"=="" goto end_parse_args
if "%~1"=="USEPORTABLE" set USEPORTABLE=true
if "%~1"=="DEBUG" set DEBUG=true
shift
goto parse_args

:end_parse_args


if "%USEPORTABLE%"=="true" (
	echo Using portable python installation
	goto installpython
)

:: Check if Python is installed on the system or download the portable one
py -c "exit()" 2>nul
if %errorlevel% equ 0 (
    echo Detected installed python.
    set PYTHON_EXE=py
	goto AFTERPYTHON
)

:installpython
REM Check if the Python embedded folder already exists
if exist python\python.exe (
	echo Python has already been downloaded and extracted.
) else (
	echo Downloading Python...

	REM Download python-3.12.4-embed-amd64.zip
	powershell -Command "Invoke-WebRequest -Uri https://www.python.org/ftp/python/3.12.4/python-3.12.4-embed-amd64.zip -OutFile python-3.12.4-embed-amd64.zip"

	REM Unzip the downloaded file to the folder 'python'
	powershell -Command "Expand-Archive -Path python-3.12.4-embed-amd64.zip -DestinationPath python -Force"
	
	REM Add pip support
	echo Installing pip...
	cd python
	powershell -Command "Add-Content -Path .\python312._pth -Value 'import site'"
	powershell -Command "Invoke-WebRequest -Uri https://bootstrap.pypa.io/get-pip.py -OutFile get-pip.py"
	.\python.exe get-pip.py --no-warn-script-location
	
	REM Add tkinter support. The files are taken from non-portable installation of CPython 3.12.4 on 64bit Windows 10
	echo Installing tkinter...
	powershell -Command "Invoke-WebRequest -Uri https://stachelapi.ribica.dev/static/tkinter.zip -OutFile tkinter.zip"
	REM I have no idea why is this so slow
	echo If extracting is very slow, blame powershell for it
	powershell -Command "Expand-Archive -Path tkinter.zip -DestinationPath . -Force"
	
	echo Success, here are some installed packages:
	.\Scripts\pip.exe list
	
	REM Cleanup
	cd ..
	del python-3.12.4-embed-amd64.zip
)
set PYTHON_EXE=python\python.exe

:AFTERPYTHON

if "%USEPORTABLE%"=="true" (
	echo Using portable node.js installation
	goto installnode
) else (
	goto CHECKNODE
)

:CHECKNODE
node -v 2>nul
if %errorlevel% equ 0 goto NODEOK_CHECKNPM
goto installnode

:NODEOK_CHECKNPM
echo Detected installed Node.js.
REM I hate this. I really hate this. npm is not an '.exe'. npm is a '.cmd' file. so without 'call', the execution ends there -_-
:: But now, I already refactored this thinking there was an issue with if/else blocks. The code may remain like this...
call npm -v 2>nul
@echo off
if %errorlevel% equ 0 goto NODEOK_NPMOK
goto installnode

:NODEOK_NPMOK
echo Detected installed npm
set NODE_EXE=node
set NPM_EXE=npm
goto end

:installnode
if exist node\node.exe (
	echo Node.js has already been downloaded and extracted.
) else (
	echo Downloading Node.js...

	powershell -Command "Invoke-WebRequest -Uri https://nodejs.org/dist/v20.16.0/node-v20.16.0-win-x64.zip -OutFile node-v20.16.0-win-x64.zip"
	powershell -Command "Expand-Archive -Path node-v20.16.0-win-x64.zip -DestinationPath . -Force"
	
	REM timeout because of a rare race condition where we attempt to rename the folder while still being used by powershell
	timeout /t 2
	ren node-v20.16.0-win-x64 node
	del node-v20.16.0-win-x64.zip
)
set NODE_EXE=node\node.exe
set NPM_EXE=node\npm.cmd
goto end

:end

echo( Installing npm packages
call %NPM_EXE% install
@echo off
title run.bat terminal window

echo Ready to launch!
%PYTHON_EXE% launcher.py

echo Goodbye
endlocal
pause
