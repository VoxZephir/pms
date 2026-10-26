@echo off
setlocal
cd /d "%~dp0"
REM  Caviarder des PDF : glisser un ou plusieurs PDF sur ce fichier.
REM  Les IBAN, les noms propres et les adresses sont retires du fichier lui-meme
REM  (pas masques par un rectangle) ; les copies vont dans output\caviarde\.
REM  Detail : docs\caviardage.md.

if "%~1"=="" (
    echo Glisser un ou plusieurs PDF sur caviarder.bat.
    echo Ou : caviarder.bat releve.pdf --also "Nom a retirer" --spare "Nom a garder"
    echo.
    pause
    exit /b 1
)

where uv >nul 2>&1
if errorlevel 1 set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] uv introuvable : lancer run.bat une fois d'abord.
    pause
    exit /b 1
)

REM  PyMuPDF est dans le groupe dev : installe ici, pas au lancement de l'app.
uv sync --locked --extra web --inexact -q
if errorlevel 1 (
    echo [ERREUR] Installation des dependances impossible ^(uv sync^).
    pause
    exit /b 1
)

.venv\Scripts\python -m pms --redact %*
if exist "output\caviarde" start "" "output\caviarde"
echo.
pause
