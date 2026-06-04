@echo off
cd /d "%~dp0"
echo Lancement du solveur avec config\solveur_config.json
echo.
python solveur_v2.py --config config\solveur_config.json
echo.
if errorlevel 1 (
    echo Le solveur n'a pas pu generer un planning valide.
    echo Lis les messages ci-dessus pour voir quelle contrainte bloque.
) else (
    echo Planning genere.
    echo Fichiers de sortie horodates selon solveur_config.json.
)
echo.
pause
