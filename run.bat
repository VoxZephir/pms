@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

REM ---------------------------------------------------------------------
REM  Analyse de releve Swissquote -- lanceur autosuffisant.
REM
REM  Installe uv, Python et les dependances au premier lancement, ingere
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

set "PY=.venv\Scripts\python.exe"
set "MODE=%~1"
REM  Where a ZIP copy gets its updates: the public repository, which
REM  tools/publish.py fills from the private one. A copy that is already a
REM  clone keeps following its own origin.
set "PMS_REPO=https://github.com/VoxZephir/pms.git"
set "PMS_BRANCH=main"

REM --- 0. git : les mises a jour ---------------------------------------
REM  Le bouton "Mettre a jour" de l'app est un git pull : sans git, l'app
REM  tourne mais ne se met pas a jour seule. Propose une fois de l'installer
REM  (winget, l'outil d'installation de Windows) ; un refus est retenu dans
REM  data\no-git. Une copie venue d'un ZIP devient une copie suivie, a la
REM  derniere version : data\ et inbox\ ne sont pas touches (hors du depot).
REM  Pas de ! dans les messages : l'expansion retardee les avale.
if exist "data\no-git" goto git_done
where git >nul 2>&1
if errorlevel 1 set "PATH=%ProgramFiles%\Git\cmd;%PATH%"
where git >nul 2>&1
if errorlevel 1 (
    where winget >nul 2>&1
    if errorlevel 1 (
        echo [0/3] Git absent : l'app marche, mais sans mise a jour d'un clic.
        echo       Pour l'activer : installer git depuis https://git-scm.com puis relancer.
        goto git_done
    )
    echo.
    echo Git permet a l'app de se mettre a jour d'un clic, depuis sa page.
    choice /c ON /m "Installer git maintenant (O = oui, N = jamais)"
    if errorlevel 2 (
        if not exist "data" mkdir "data"
        echo refuse le %DATE%> "data\no-git"
        echo Compris : mises a jour a la main. Supprimer data\no-git pour changer d'avis.
        goto git_done
    )
    echo [0/3] Installation de git...
    winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements
    where git >nul 2>&1
    if errorlevel 1 (
        echo [ATTENTION] Git n'a pas pu etre installe : l'app demarre sans mise a jour d'un clic.
        goto git_done
    )
)
if exist ".git" goto git_done
REM  One block, read whole by cmd before it runs: checking out rewrites this
REM  very file, and cmd would otherwise read the rest of the new one at the
REM  old offset. The block ends by starting the new version and leaving.
echo [0/3] Copie sans suivi (un ZIP) : elle devient une copie suivie, pour les mises a jour...
(
    git init -q
    git remote add origin "%PMS_REPO%"
    git fetch -q origin "+refs/heads/%PMS_BRANCH%:refs/remotes/origin/%PMS_BRANCH%"
    if errorlevel 1 (
        rmdir /s /q ".git"
        echo [ATTENTION] Depot injoignable : la copie reste telle quelle, l'app demarre quand meme.
    ) else (
        git checkout -q -f -B "%PMS_BRANCH%" "origin/%PMS_BRANCH%"
        git branch -q --set-upstream-to="origin/%PMS_BRANCH%"
        git clean -fdq -- "src/pms/web/static/spa"
        echo       Copie a jour et suivie : le bouton "Mettre a jour" de l'app est actif.
        call "%~f0" %*
        exit /b
    )
)
:git_done

REM --- 1. uv -------------------------------------------------------------
REM  uv installe lui-meme la bonne version de Python (.python-version) et
REM  les dependances aux versions exactes de uv.lock : rien a installer a la
REM  main, et les memes versions sur chaque PC. Installe au premier
REM  lancement s'il manque (%USERPROFILE%\.local\bin).
where uv >nul 2>&1
if errorlevel 1 (
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
    where uv >nul 2>&1
    if errorlevel 1 (
        echo [1/3] Installation de uv...
        powershell -NoProfile -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
        where uv >nul 2>&1
        if errorlevel 1 (
            echo.
            echo [ERREUR] Installation de uv impossible.
            echo          Voir https://docs.astral.sh/uv/getting-started/installation/
            echo.
            pause
            exit /b 1
        )
    )
)

REM --- 2. Python et dependances -----------------------------------------
REM  `uv sync` cree ou repare .venv, et ne fait rien si tout est a jour. Les
REM  outils de test (groupe dev) ne viennent qu'avec --test ; --inexact les
REM  laisse en place ensuite plutot que de les desinstaller.
set "DEV=--no-dev"
if /I "%MODE%"=="--test" set "DEV="
echo [2/3] Python et dependances (uv)...
uv sync --locked --extra web %DEV% --inexact
if errorlevel 1 (
    echo.
    echo [ERREUR] Installation des dependances impossible ^(uv sync^).
    echo.
    pause
    exit /b 1
)

REM --- 3. Mode test ------------------------------------------------------
if /I "%MODE%"=="--test" (
    REM Sur tous les coeurs ; les tests du vrai releve sur un seul (--dist loadgroup).
    "%PY%" -m pytest tests -q -n auto --dist loadgroup
    set "CODE=!ERRORLEVEL!"
    echo.
    pause
    exit /b !CODE!
)

REM --- 4. Premier lancement -----------------------------------------------
REM  Sans ledger ni releve, rien a ingerer : l'app demarre quand meme, et le
REM  navigateur s'ouvre sur son accueil vide, qui propose l'import. S'arreter ici sur une erreur
REM  laissait quelqu'un qui decouvre l'app devant une console fermee.
if not exist "inbox" mkdir "inbox"
if "%MODE%"=="" if not exist "data\ledger.json" (
    dir /s /b /a-d "inbox" >nul 2>&1
    if errorlevel 1 (
        echo.
        echo Aucun releve pour l'instant : l'app s'ouvre sur sa page d'accueil, qui propose l'import.
        goto web
    )
)

REM --- 5. Ingestion ------------------------------------------------------
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

REM --- 5b. Sauvegarde ----------------------------------------------------
REM  data\ porte les corrections, les regles perso, les budgets : rien de
REM  cela ne se reconstruit depuis les PDF. Copie zippee et chiffree vers
REM  OneDrive (cle : data\backup.key, creee au premier passage), ecrite
REM  seulement si quelque chose a change. Un echec ne bloque pas l'app.
"%PY%" -m pms --backup

REM --- 5c. Cours du jour -------------------------------------------------
REM  IBKR (service Flex, si configure), reperes, indices du 3a, crypto :
REM  une fois par jour, chaque etape independante. Un site injoignable ne
REM  bloque pas l'app ; l'etape est retentee au lancement suivant.
"%PY%" -m pms --refresh --daily

REM --- 6. App web -------------------------------------------------------
:web
echo.
echo ============================================================
echo   App disponible sur  http://127.0.0.1:5000
echo   Ctrl+C pour arreter.
echo ============================================================
echo.
"%PY%" -m pms.web
exit /b %ERRORLEVEL%
