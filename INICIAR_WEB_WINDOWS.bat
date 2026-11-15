@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Flame in Freefall (web) - OCEANPIXELS
echo.
echo  ==============================================
echo    FLAME IN FREEFALL - OCEANPIXELS  (version web)
echo    No cierres esta ventana mientras uses la app.
echo  ==============================================
echo.
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >nul 2>nul
if errorlevel 1 goto instalar_uv
goto correr

:instalar_uv
echo  Paso 1 de 2: instalando la herramienta uv. Solo pasa la primera vez...
powershell -NoProfile -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >nul 2>nul
if errorlevel 1 goto error_uv

:correr
echo  Paso 2 de 2: preparando y abriendo la app en http://localhost:8600
echo  La primera vez puede tardar de 1 a 5 minutos. Espera...
echo  El navegador se abrira solo cuando este lista.
echo.
start "" powershell -NoProfile -WindowStyle Hidden -c "for($i=0;$i -lt 300;$i++){try{Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8600/api/health -TimeoutSec 5 | Out-Null; Start-Process 'http://localhost:8600'; break}catch{Start-Sleep 2}}"
set "FLAME_PORT=8600"
uv run python server.py
echo.
echo  La app se detuvo. Si viste un error arriba, toma una foto de esta ventana y enviala al equipo.
echo  (Si el puerto 8600 esta ocupado, cierra la otra ventana de la app y vuelve a intentar.)
pause
exit /b

:error_uv
echo.
echo  No se pudo instalar uv. Revisa tu conexion a internet y vuelve a hacer doble clic en INICIAR_WEB_WINDOWS.bat
pause
exit /b
