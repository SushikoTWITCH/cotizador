@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Cotizador
set "ESC="
for /f %%E in ('echo prompt $E ^| cmd') do set "ESC=%%E"
set "AZUL="
set "VERDE="
set "ROJO="
set "FIN="
if defined ESC set "AZUL=%ESC%[38;2;31;148;249m"
if defined ESC set "VERDE=%ESC%[38;2;63;185;80m"
if defined ESC set "ROJO=%ESC%[38;2;248;81;73m"
if defined ESC set "FIN=%ESC%[0m"

echo.
echo   COTIZADOR                     http://localhost:5571
echo   %AZUL%----------------------------------------------------%FIN%
set "PY="
where py >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    where python >nul 2>&1
    if not errorlevel 1 set "PY=python"
)
if not defined PY goto SINPY
%PY% -c "import reportlab" >nul 2>&1
if errorlevel 1 goto SINREPORTLAB
set "PYTHONPATH=%~dp0src"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
echo %VERDE%  Abriendo el navegador. Cierra esta ventana para apagarlo.%FIN%
echo.
%PY% -m cotizador serve --abrir
if errorlevel 1 goto CAYO
call :LOGO
exit /b 0

:SINPY
echo.
echo   %ROJO%x  NO HAY PYTHON: corre INSTALAR.bat%FIN%
echo.
call :LOGO
exit /b 1

:SINREPORTLAB
echo.
echo   %ROJO%x  FALTA INSTALAR: corre INSTALAR.bat%FIN%
echo.
call :LOGO
exit /b 1

:CAYO
echo.
echo   %ROJO%x  EL COTIZADOR SE DETUVO CON ERROR%FIN%
echo      Si dice "address already in use", ya esta abierto en otra ventana
echo.
call :LOGO
exit /b 1

:LOGO
where node >nul 2>&1
if errorlevel 1 goto SINLOGO
if not exist "%~dp0logo-animado.js" goto SINLOGO
node "%~dp0logo-animado.js" giro marca 0 12
goto :eof

:SINLOGO
pause
goto :eof
