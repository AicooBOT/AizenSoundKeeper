@echo off
:: AizenSoundKeeper — Ajouter au démarrage Windows
:: Double-cliquez pour installer le démarrage automatique

set "EXE_PATH=%~dp0AizenSoundKeeper.exe"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\AizenSoundKeeper.lnk"

powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -Path '%~dp0' -Recurse | Unblock-File"
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $lnk = $ws.CreateShortcut('%STARTUP%'); $lnk.TargetPath = '%EXE_PATH%'; $lnk.WorkingDirectory = '%~dp0'; $lnk.Description = 'AizenSoundKeeper - Maintient tes baffes en vie'; $lnk.Save()"

echo.
echo  [OK] AizenSoundKeeper demarrera automatiquement avec Windows.
echo  Raccourci cree dans : %STARTUP%
echo.
pause
