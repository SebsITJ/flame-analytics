@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Flame in Freefall - OCEANPIXELS
echo.
echo  ==============================================
echo    FLAME IN FREEFALL - OCEANPIXELS
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
echo  Paso 2 de 2: preparando y abriendo la app.
echo  La primera vez puede tardar de 1 a 5 minutos. Espera...
echo  El navegador se abrira solo cuando este lista.
echo.
start "" powershell -NoProfile -WindowStyle Hidden -c "for($i=0;$i -lt 300;$i++){try{Invoke-WebRequest -UseBasicParsing http://localhost:8501/_stcore/health -TimeoutSec 2 | Out-Null; Start-Process 'http://localhost:8501'; break}catch{Start-Sleep 2}}"
uv run streamlit run app.py --server.headless true --server.port 8501
echo.
echo  La app se detuvo. Si viste un error arriba, toma una foto de esta ventana y enviala al equipo.
pause
exit /b

:error_uv
echo.
echo  No se pudo instalar uv. Revisa tu conexion a internet y vuelve a hacer doble clic en RESPALDO_STREAMLIT_WINDOWS.bat
pause
exit /b
