@echo off
:: AizenSoundKeeper — Retirer du démarrage automatique

set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\AizenSoundKeeper.lnk"
set "LEGACY_STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\SoundKeeper.lnk"

if exist "%STARTUP%" (
    del "%STARTUP%"
    echo  [OK] AizenSoundKeeper retire du demarrage Windows.
)
if exist "%LEGACY_STARTUP%" (
    del "%LEGACY_STARTUP%"
)
if not exist "%STARTUP%" if not exist "%LEGACY_STARTUP%" (
    echo  [INFO] AizenSoundKeeper n'etait pas dans le demarrage automatique.
)
echo.
pause
