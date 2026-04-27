@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"

set "ROOT_DIR=%CD%"
set "LOCK_DIR=%ROOT_DIR%\.build_release.lock"
set "LOG_ROOT=%ROOT_DIR%\logs"
set "LATEST_LOG_FILE=%LOG_ROOT%\build_release.log"
set "TEMP_DIR=%ROOT_DIR%\temp"
set "BUILD_ROOT=%TEMP_DIR%\pyinstaller-build"
set "PORTABLE_ROOT=%ROOT_DIR%\portable"
set "APP_DIR=%PORTABLE_ROOT%\SemiUtilsQt"
set "ZIP_PATH=%PORTABLE_ROOT%\SemiUtilsQt-windows.zip"
set "EXIT_CODE=1"

mkdir "%LOCK_DIR%" 2>nul
if errorlevel 1 (
    echo ERROR: Another release build appears to be running.
    echo Lock directory: %LOCK_DIR%
    echo If no build is running, delete the lock directory and run build_release.bat again.
    endlocal & exit /b 1
)
set "LOCK_HELD=1"

for /f "usebackq delims=" %%T in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Date -Format yyyyMMdd_HHmmss" 2^>nul`) do set "BUILD_STAMP=%%T"
if not defined BUILD_STAMP set "BUILD_STAMP=unknown_%RANDOM%%RANDOM%"

for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$PID" 2^>nul`) do set "BUILD_PID=%%P"
if not defined BUILD_PID set "BUILD_PID=%RANDOM%%RANDOM%"

if not exist "%LOG_ROOT%\" mkdir "%LOG_ROOT%" 2>nul
if not exist "%LOG_ROOT%\" (
    echo ERROR: Could not create build log directory:
    echo   %LOG_ROOT%
    if exist "%LOCK_DIR%" rmdir /s /q "%LOCK_DIR%" >nul 2>nul
    endlocal & exit /b 1
)

set "LOG_FILE=%LOG_ROOT%\build_release_%BUILD_STAMP%_%BUILD_PID%.log"

> "%LOCK_DIR%\owner.txt" echo SemiUtilsQt release build started at %DATE% %TIME%
>> "%LOCK_DIR%\owner.txt" echo Root: %ROOT_DIR%
>> "%LOCK_DIR%\owner.txt" echo Log: %LOG_FILE%

> "%LOG_FILE%" echo SemiUtilsQt release build started at %DATE% %TIME%
if errorlevel 1 (
    echo ERROR: Could not create build log:
    echo   %LOG_FILE%
    if exist "%LOCK_DIR%" rmdir /s /q "%LOCK_DIR%" >nul 2>nul
    endlocal & exit /b 1
)

call :log "Root: %ROOT_DIR%"
call :log "Log: %LOG_FILE%"

where python >nul 2>nul
if errorlevel 1 (
    call :log "ERROR: python was not found in PATH."
    echo ERROR: python was not found in PATH.
    set "EXIT_CODE=1"
    goto :finish
)

for /f "usebackq delims=" %%V in (`python -c "import sys; print(sys.version.split()[0])"`) do set "PYTHON_VERSION=%%V"
call :log "Python: %PYTHON_VERSION%"

python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    call :log "ERROR: Python %PYTHON_VERSION% is unsupported. Use Python 3.10 or newer."
    echo ERROR: Python %PYTHON_VERSION% is unsupported. Use Python 3.10 or newer.
    set "EXIT_CODE=1"
    goto :finish
)

if /I "%SKIP_BUILD_DEPS%"=="1" (
    call :log "Skipping build dependency installation because SKIP_BUILD_DEPS=1."
) else (
    call :log "Installing or updating build dependencies."
    python -m pip install --upgrade pip setuptools wheel pyinstaller >> "%LOG_FILE%" 2>&1
    if errorlevel 1 (
        call :log "ERROR: Failed to install build dependencies. See %LOG_FILE%."
        echo ERROR: Failed to install build dependencies. See:
        echo   %LOG_FILE%
        set "EXIT_CODE=1"
        goto :finish
    )
)

python -c "import PyInstaller; print('PyInstaller', PyInstaller.__version__)" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    call :log "ERROR: PyInstaller is not available. Install it or run without SKIP_BUILD_DEPS=1."
    echo ERROR: PyInstaller is not available. Install it or run without SKIP_BUILD_DEPS=1.
    set "EXIT_CODE=1"
    goto :finish
)

call :log "Cleaning previous build outputs."
if exist "%TEMP_DIR%" rmdir /s /q "%TEMP_DIR%" >> "%LOG_FILE%" 2>&1
if exist "%APP_DIR%" rmdir /s /q "%APP_DIR%" >> "%LOG_FILE%" 2>&1
if exist "%ZIP_PATH%" del /f /q "%ZIP_PATH%" >> "%LOG_FILE%" 2>&1
if exist "%ROOT_DIR%\build_release" rmdir /s /q "%ROOT_DIR%\build_release" >> "%LOG_FILE%" 2>&1
if exist "%ROOT_DIR%\SemiUtilsQt.spec" del /f /q "%ROOT_DIR%\SemiUtilsQt.spec" >> "%LOG_FILE%" 2>&1
for /d %%D in (*.egg-info) do rmdir /s /q "%%D" >> "%LOG_FILE%" 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath '%ROOT_DIR%' -Directory -Recurse -Force -Filter '__pycache__' | Remove-Item -Recurse -Force" >> "%LOG_FILE%" 2>&1

if not exist "%BUILD_ROOT%" mkdir "%BUILD_ROOT%" >> "%LOG_FILE%" 2>&1
if not exist "%PORTABLE_ROOT%" mkdir "%PORTABLE_ROOT%" >> "%LOG_FILE%" 2>&1

call :log "Running PyInstaller onedir build."
python -m PyInstaller ^
    --noconfirm ^
    --onedir ^
    --contents-directory "." ^
    --windowed ^
    --name SemiUtilsQt ^
    --icon "%ROOT_DIR%\logo.ico" ^
    --distpath "%PORTABLE_ROOT%" ^
    --workpath "%BUILD_ROOT%" ^
    --specpath "%TEMP_DIR%" ^
    --add-data "%ROOT_DIR%\fonts;fonts" ^
    --add-data "%ROOT_DIR%\logos;logos" ^
    --add-data "%ROOT_DIR%\exiftool;exiftool" ^
    --add-data "%ROOT_DIR%\config.yaml;." ^
    --add-data "%ROOT_DIR%\example.jpg;." ^
    --add-data "%ROOT_DIR%\logo.ico;." ^
    main_gui.py >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    call :log "ERROR: PyInstaller build failed. See %LOG_FILE%."
    echo ERROR: PyInstaller build failed. See:
    echo   %LOG_FILE%
    set "EXIT_CODE=1"
    goto :finish
)

if not exist "%APP_DIR%\SemiUtilsQt.exe" (
    call :log "ERROR: SemiUtilsQt.exe was not found in PyInstaller output."
    echo ERROR: SemiUtilsQt.exe was not found in PyInstaller output. See:
    echo   %LOG_FILE%
    set "EXIT_CODE=1"
    goto :finish
)

call :copy_runtime_resources
if errorlevel 1 (
    set "EXIT_CODE=1"
    goto :finish
)

if exist "%ROOT_DIR%\bin" (
    call :log "Copying optional bin directory."
    xcopy "%ROOT_DIR%\bin\*" "%APP_DIR%\bin\" /E /I /Y >> "%LOG_FILE%" 2>&1
)

call :write_runner

call :log "Creating zip archive."
call :create_zip
if errorlevel 1 (
    call :log "ERROR: Failed to create zip archive."
    echo ERROR: Failed to create zip archive. See:
    echo   %LOG_FILE%
    set "EXIT_CODE=1"
    goto :finish
)

call :log "Cleaning temporary build files."
if exist "%TEMP_DIR%" rmdir /s /q "%TEMP_DIR%" >> "%LOG_FILE%" 2>&1
if exist "%ROOT_DIR%\build_release" rmdir /s /q "%ROOT_DIR%\build_release" >> "%LOG_FILE%" 2>&1
if exist "%ROOT_DIR%\SemiUtilsQt.spec" del /f /q "%ROOT_DIR%\SemiUtilsQt.spec" >> "%LOG_FILE%" 2>&1
for /d %%D in (*.egg-info) do rmdir /s /q "%%D" >> "%LOG_FILE%" 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath '%ROOT_DIR%' -Directory -Recurse -Force -Filter '__pycache__' | Remove-Item -Recurse -Force" >> "%LOG_FILE%" 2>&1

call :log "Build completed."
echo.
echo Build completed:
echo   %APP_DIR%\SemiUtilsQt.exe
echo   %ZIP_PATH%
echo   %LOG_FILE%
echo   %LATEST_LOG_FILE% ^(latest copy^)
set "EXIT_CODE=0"
goto :finish

:finish
call :publish_latest_log
if defined LOCK_HELD (
    if exist "%LOCK_DIR%" rmdir /s /q "%LOCK_DIR%" >nul 2>nul
)
endlocal & exit /b %EXIT_CODE%

:write_runner
> "%APP_DIR%\run_with_log.bat" echo @echo off
>> "%APP_DIR%\run_with_log.bat" echo setlocal
>> "%APP_DIR%\run_with_log.bat" echo cd /d "%%~dp0"
>> "%APP_DIR%\run_with_log.bat" echo echo Runtime started at %%DATE%% %%TIME%% ^> runtime.log
>> "%APP_DIR%\run_with_log.bat" echo SemiUtilsQt.exe ^>^> runtime.log 2^>^&1
>> "%APP_DIR%\run_with_log.bat" echo echo Exit code: %%ERRORLEVEL%% ^>^> runtime.log
>> "%APP_DIR%\run_with_log.bat" echo pause
exit /b 0

:copy_runtime_resources
call :log "Copying runtime resources to portable output."
if exist "%ROOT_DIR%\*.ico" (
    for %%I in ("%ROOT_DIR%\*.ico") do copy /y "%%~fI" "%APP_DIR%\" >> "%LOG_FILE%" 2>&1
)
if exist "%ROOT_DIR%\logos" (
    xcopy "%ROOT_DIR%\logos\*" "%APP_DIR%\logos\" /E /I /Y >> "%LOG_FILE%" 2>&1
)
if exist "%ROOT_DIR%\exiftool" (
    xcopy "%ROOT_DIR%\exiftool\*" "%APP_DIR%\exiftool\" /E /I /Y >> "%LOG_FILE%" 2>&1
)
if not exist "%APP_DIR%\logo.ico" (
    call :log "ERROR: logo.ico was not copied to portable output."
    echo ERROR: logo.ico was not copied to portable output. See:
    echo   %LOG_FILE%
    exit /b 1
)
if not exist "%APP_DIR%\logos\" (
    call :log "ERROR: logos directory was not copied to portable output."
    echo ERROR: logos directory was not copied to portable output. See:
    echo   %LOG_FILE%
    exit /b 1
)
dir /b "%APP_DIR%\logos\*" >nul 2>nul
if errorlevel 1 (
    call :log "ERROR: logos directory is empty in portable output."
    echo ERROR: logos directory is empty in portable output. See:
    echo   %LOG_FILE%
    exit /b 1
)
if not exist "%APP_DIR%\exiftool\exiftool.exe" (
    call :log "ERROR: exiftool\exiftool.exe was not copied to portable output."
    echo ERROR: exiftool\exiftool.exe was not copied to portable output. See:
    echo   %LOG_FILE%
    exit /b 1
)
exit /b 0

:create_zip
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $source='%APP_DIR%'; $dest='%ZIP_PATH%'; for ($i = 1; $i -le 10; $i++) { try { Compress-Archive -LiteralPath $source -DestinationPath $dest -Force; exit 0 } catch { if ($i -eq 10) { Write-Error $_; exit 1 }; Start-Sleep -Milliseconds 750 } }" >> "%LOG_FILE%" 2>&1
exit /b %ERRORLEVEL%

:publish_latest_log
if not defined LOG_FILE exit /b 0
if not exist "%LOG_FILE%" exit /b 0
copy /y "%LOG_FILE%" "%LATEST_LOG_FILE%" >nul 2>nul
if errorlevel 1 (
    echo WARNING: Could not update latest log copy:
    echo   %LATEST_LOG_FILE%
    echo Current build log remains available at:
    echo   %LOG_FILE%
)
exit /b 0

:log
echo [%DATE% %TIME%] %~1
>> "%LOG_FILE%" echo [%DATE% %TIME%] %~1
exit /b 0
