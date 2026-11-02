@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Instalar Cotizador
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
echo   INSTALAR COTIZADOR                 reportlab + fuentes
echo   %AZUL%----------------------------------------------------%FIN%
echo.
echo   %AZUL%[1/3]%FIN%  Python . . . . . . . . . . . . . . .
set "PY="
where py >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    where python >nul 2>&1
    if not errorlevel 1 set "PY=python"
)
if not defined PY goto SINPY
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>&1
if errorlevel 1 goto PYVIEJO
echo          ok
echo   %AZUL%[2/3]%FIN%  reportlab  ^(genera el PDF^) . . . . . .
%PY% -m pip install --user -q --disable-pip-version-check -r requirements.txt >nul 2>"%TEMP%\cot_e.txt"
if errorlevel 1 goto PIPFAIL
%PY% -c "import reportlab" >nul 2>"%TEMP%\cot_e.txt"
if errorlevel 1 goto PIPFAIL
echo          ok
echo   %AZUL%[3/3]%FIN%  Fuentes Roboto y Merriweather . . . .
set "PYTHONPATH=%~dp0src"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
%PY% -m cotizador fuentes >nul 2>"%TEMP%\cot_e.txt"
set "FUENTES=0"
for %%F in (Roboto-Regular Roboto-Bold Merriweather-Regular Merriweather-Bold) do if exist "fuentes\%%F.ttf" set /a FUENTES+=1
if not "!FUENTES!"=="4" goto SINFUENTES
echo          ok
echo.
echo   %AZUL%----------------------------------------------------%FIN%
echo.
echo %VERDE%  Listo. Abre INICIAR.bat%FIN%
echo.
call :LOGO
exit /b 0

:SINPY
echo.
echo   %ROJO%x  NO HAY PYTHON%FIN%
echo      Instalalo de python.org ^(marca "Add python.exe to PATH"^)
echo.
call :LOGO
exit /b 1

:PYVIEJO
echo.
echo   %ROJO%x  PYTHON MUY VIEJO: se necesita 3.9 o mas nuevo%FIN%
echo.
call :LOGO
exit /b 1

:PIPFAIL
type "%TEMP%\cot_e.txt"
echo.
echo   %ROJO%x  NO SE INSTALO REPORTLAB%FIN%
echo      Revisa tu internet y vuelve a correr INSTALAR.bat
echo.
call :LOGO
exit /b 1

:SINFUENTES
type "%TEMP%\cot_e.txt"
echo.
echo   %ROJO%^^!  FUENTES NO BAJARON: el PDF usara Helvetica/Times%FIN%
echo      Vuelve a correr INSTALAR.bat con internet
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
