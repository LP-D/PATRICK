@echo off
setlocal
set "PATRICK_DIR=%~dp0"
cd /d "%PATRICK_DIR%"

if not exist "%PATRICK_DIR%.venv\Scripts\activate.bat" (
    echo [ERREUR] Environnement virtuel introuvable : %PATRICK_DIR%.venv
    echo.
    echo Cree-le une premiere fois avec :
    echo   python -m venv .venv
    echo   .venv\Scripts\activate
    echo   pip install -e ".[dev,web]"
    echo.
    pause
    exit /b 1
)

call "%PATRICK_DIR%.venv\Scripts\activate.bat"

where patrick >nul 2>nul
if errorlevel 1 (
    echo [ERREUR] La commande "patrick" n'est pas installee dans cet environnement.
    echo Lance : pip install -e ".[dev,web]"
    echo.
    pause
    exit /b 1
)

echo Lancement de PATRICK sur http://127.0.0.1:8000 ...
echo (Ctrl+C pour arreter le serveur)
echo.
patrick serve

echo.
echo Serveur arrete.
pause
