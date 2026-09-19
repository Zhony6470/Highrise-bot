@echo off
title HighriseBot
cd /d "%~dp0"
echo Activando el entorno virtual...
call .venv\Scripts\activate

echo Iniciando el bot de Highrise...
:loop
python bots\zeta\main.py
echo El bot se ha detenido. Reiniciando en 5 segundos...
timeout /t 5 /nobreak >nul
goto loop