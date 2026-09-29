@echo off
rem Double-click to set up and start TES Auto-Convert.
rem First run: installs Python 3.14 if missing (winget, no admin), creates a
rem private .venv here that reuses packages already installed in that Python
rem and installs only what is missing or at another version into .venv (never
rem into the user's own Python). Every run: repairs a broken .venv, checks the
rem packages, offers xWMAEncode.exe while it is missing, and runs
rem core\setup_check.py, which lists anything else still to install.
rem Setup output goes to logs\launcher.log.
setlocal
for /f %%A in ('echo prompt $E^| cmd') do set "ESC=%%A"
set "RED=%ESC%[91m"
set "YELLOW=%ESC%[93m"
set "GREEN=%ESC%[92m"
set "WHITE=%ESC%[97m"
set "CYAN=%ESC%[96m"
set "OSC8=%ESC%]8;;"
set "ST=%ESC%\"
set "RESET=%ESC%[0m"
cd /d "%~dp0" || goto not_writable
set "VENV_PY=.venv\Scripts\python.exe"
set "LOG=logs\launcher.log"
set "XWMA_DIR=external\xwmaencode"
set "DXSDK_URL=https://download.microsoft.com/download/A/E/7/AE743F1F-632B-4809-87A9-AA1BB3458E31/DXSDK_Jun10.exe"

del ".write_test" >nul 2>&1
(echo.>".write_test") >nul 2>&1
if not exist ".write_test" goto not_writable
del ".write_test"
if not exist logs mkdir logs
>>"%LOG%" echo ==== %date% %time% ====

if exist "%VENV_PY%" "%VENV_PY%" -c "" >nul 2>&1 || call :drop_broken_venv
if exist "%VENV_PY%" goto packages

set "FIRST_RUN=--first-run"
call :find_python
if not defined PYEXE call :install_python
if not defined PYEXE goto fail
echo Creating the Python environment in .venv ...
"%PYEXE%" -m venv --system-site-packages .venv >>"%LOG%" 2>&1 || goto fail
echo Installing Python packages. The first time this can take a few minutes ...

:packages
echo Checking Python packages ...
"%VENV_PY%" -m pip install --disable-pip-version-check -q -r requirements.txt >>"%LOG%" 2>&1 || goto fail
call :get_xwmaencode
"%VENV_PY%" -m core.setup_check %FIRST_RUN%
start "" ".venv\Scripts\pythonw.exe" gui.py
exit /b 0

:drop_broken_venv
if not exist "%VENV_PY%" exit /b 0
echo %YELLOW%The Python environment in .venv no longer works. Rebuilding it ...%RESET%
>>"%LOG%" echo .venv failed to start; rebuilding it.
rmdir /s /q .venv
exit /b 0

:find_python
set "PYEXE="
for /f "delims=" %%E in ('py -3.14 -c "import sys, tkinter; print(sys.executable)" 2^>nul') do set "PYEXE=%%E"
if defined PYEXE exit /b 0
for %%E in ("%LOCALAPPDATA%\Programs\Python\Python314\python.exe" "%ProgramFiles%\Python314\python.exe") do (
    if exist "%%~E" set "PYEXE=%%~E"
)
exit /b 0

:install_python
where winget >nul 2>&1 || (
    echo %RED%Python 3.14 is not installed and winget is not available.%RESET%
    echo Install Python 3.14 from %OSC8%https://www.python.org/downloads/%ST%%CYAN%https://www.python.org/downloads/%RESET%%OSC8%%ST% and run this again.
    exit /b 0
)
echo Installing Python 3.14 for your user account ...
winget install -e --id Python.Python.3.14 --scope user --accept-package-agreements --accept-source-agreements
call :find_python
if not defined PYEXE (
    echo %YELLOW%Python was installed, but this window cannot see it yet.
    echo Close this window and double-click TES Auto-Convert.cmd again.%RESET%
)
exit /b 0

:get_xwmaencode
if exist "%XWMA_DIR%\xWMAEncode.exe" exit /b 0
echo.
echo %YELLOW%Voice lines need xWMAEncode.exe, from Microsoft's DirectX SDK (June 2010).%RESET%
echo Microsoft does not allow it to be shipped with this tool, but this window can
echo download the SDK installer from Microsoft (about 600 MB), take out just that
echo one file, and delete the rest. Nothing is installed.
choice /c YN /m "%WHITE%Download it now%RESET%"
if errorlevel 2 (
    echo Skipped. You will be asked again next time.
    exit /b 0
)
set "DXSDK=%TEMP%\DXSDK_Jun10.exe"
curl.exe -L --fail -# -o "%DXSDK%" "%DXSDK_URL%" || goto xwma_failed
external\7zip\7z.exe e -y "%DXSDK%" "DXSDK\Utilities\bin\x86\xWMAEncode.exe" -o"%XWMA_DIR%" >>"%LOG%" 2>&1 || goto xwma_failed
del "%DXSDK%"
echo %GREEN%xWMAEncode.exe is in %XWMA_DIR%\.%RESET%
exit /b 0

:xwma_failed
if defined DXSDK del "%DXSDK%" 2>nul
>>"%LOG%" echo xWMAEncode download or extraction failed.
echo %YELLOW%Could not get xWMAEncode.exe. You will be asked again next time.%RESET%
exit /b 0

:not_writable
echo %RED%This folder can't be opened or written to:%RESET%
echo   %~dp0
echo Move the whole folder somewhere else, such as your Documents folder, and
echo double-click TES Auto-Convert.cmd there.
pause
exit /b 1

:fail
echo.
echo %RED%Setup did not finish.%RESET% The last lines of %LOG%:
echo.
powershell -NoProfile -Command "Get-Content -Tail 15 -LiteralPath $env:LOG" 2>nul
echo.
echo If you ask for help, include the file %LOG%.
pause
exit /b 1
