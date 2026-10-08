@echo off
rem Installe (ou met en ordre) PATRICK sur ce PC : double-clic. Options : voir Installer.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Installer.ps1" %*
if errorlevel 1 pause
