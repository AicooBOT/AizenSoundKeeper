@echo off
:: AizenSoundKeeper — Lanceur avec déblocage automatique SmartScreen
:: Supprime le marqueur "Mark of the Web" (Zone.Identifier) et lance l'application sans écran bleu

powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -Path '%~dp0' -Recurse | Unblock-File"
start "" "%~dp0AizenSoundKeeper.exe"
