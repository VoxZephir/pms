@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

REM ---------------------------------------------------------------------
REM  Analyse de releve Swissquote -- lanceur autosuffisant.
REM
REM  Cree le venv et installe les dependances au premier lancement, ingere
REM  tous les PDF de inbox\, puis demarre l'app web.
REM
REM  Usage :
REM    run.bat              ingestion + app web (defaut)
REM    run.bat --check      controle d'integrite seul, n'ecrit rien
REM    run.bat --status     etat du ledger et historique des imports
REM    run.bat --test       lance la suite de tests
REM    run.bat --reparse    relit aussi les PDF deja importes
REM  Toute autre option est transmise telle quelle a "python -m pms".
REM ---------------------------------------------------------------------

set "VENV=.venv"
set "PY=%VENV%\Scripts\python.exe"
set "MODE=%~1"

REM --- 1. Interpreteur Python -------------------------------------------
where py >nul 2>&1
if %ERRORLEVEL%==0 (
    set "BOOTSTRAP=py -3"
) else (
    where python >nul 2>&1
    if !ERRORLEVEL!==0 (
        set "BOOTSTRAP=python"
    ) else (
        echo.
        echo [ERREUR] Python introuvable.
        echo          Installez Python 3.11 ou plus recent : https://www.python.org/downloads/
        echo          Cochez "Add python.exe to PATH" pendant l'installation.
        echo.
        pause
        exit /b 1
    )
)

REM --- 2. Environnement virtuel -----------------------------------------
if not exist "%PY%" (
    echo [1/3] Creation de l'environnement virtuel...
    %BOOTSTRAP% -m venv "%VENV%"
    if errorlevel 1 (
        echo [ERREUR] Creation du venv impossible.
        pause
        exit /b 1
    )
)

REM --- 3. Dependances ----------------------------------------------------
REM  On teste l'import reel plutot qu'un marqueur : si le venv a ete
REM  bricole a la main, on repare au lieu de partir en erreur.
"%PY%" -c "import pms, pdfplumber, jinja2, flask" >nul 2>&1
if errorlevel 1 (
    echo [2/3] Installation des dependances...
    "%PY%" -m pip install --quiet --upgrade pip
    "%PY%" -m pip install --quiet -e ".[web]"
    if errorlevel 1 (
        echo [ERREUR] Installation des dependances impossible.
        pause
        exit /b 1
    )
)

REM --- 4. Mode test ------------------------------------------------------
if /I "%MODE%"=="--test" (
    "%PY%" -m pip install --quiet -e ".[dev]"
    "%PY%" -m pytest tests -q
    echo.
    pause
    exit /b %ERRORLEVEL%
)

REM --- 5. Verification de l'inbox ---------------------------------------
if not exist "inbox\*.pdf" (
    echo.
    echo [ERREUR] Aucun PDF dans inbox\.
    echo          Deposez-y votre releve Swissquote puis relancez.
    echo.
    pause
    exit /b 1
)

REM --- 6. Ingestion ------------------------------------------------------
REM  Toujours faite en premier : un nouveau PDF depose dans inbox\ doit etre
REM  pris en compte, quel que soit le mode. Le dedoublonnage rend l'operation
REM  sans effet si rien n'a change.
echo [3/3] Ingestion des releves...
echo.
if /I "%MODE%"=="--check" (
    "%PY%" -m pms %*
    set "CODE=!ERRORLEVEL!"
    echo.
    pause
    exit /b !CODE!
) else if /I "%MODE%"=="--status" (
    "%PY%" -m pms --status
    echo.
    pause
    exit /b 0
) else if not "%MODE%"=="" (
    REM Option inconnue : on la transmet a la CLI, sans demarrer le serveur.
    "%PY%" -m pms %*
    set "CODE=!ERRORLEVEL!"
    echo.
    pause
    exit /b !CODE!
) else (
    "%PY%" -m pms --check
)
set "CODE=%ERRORLEVEL%"

REM --- 7. App web -------------------------------------------------------
echo.
echo ============================================================
echo   App disponible sur  http://127.0.0.1:5000
echo   Ctrl+C pour arreter.
echo ============================================================
echo.
"%PY%" -m pms.web
exit /b %ERRORLEVEL%
