@echo off
setlocal EnableExtensions
chcp 65001 >nul

rem The root directory is the folder that contains this .bat file: qt_gui.
set "ROOT_DIR=%~dp0"
for %%I in ("%ROOT_DIR%.") do set "ROOT_DIR=%%~fI"

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT_DIR%\build_release.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"

if not defined NO_PAUSE pause
exit /b %EXIT_CODE%
