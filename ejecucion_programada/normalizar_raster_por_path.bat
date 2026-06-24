@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "ARCGIS_PYTHON=C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"
set "SCRIPT_PATH=%SCRIPT_DIR%normalizar_raster_por_path.py"
set "DEFAULT_RASTER_PATH=\\amssclgis10.ams.gmams.cl\CL_MLP_PAO\Chacay_El_Mauro_Drone\26_05\CL_MLP_PAO_IF_Ortho_26_05_10_DME7_PA7_IF6.tif"
set "DEFAULT_EXTRA_ARGS=--apply --restore-latest-backup-first --mask-black-background --black-threshold 35"
set "BAT_LOG_DIR=%SCRIPT_DIR%outputs\bat_logs"
if not exist "%BAT_LOG_DIR%" mkdir "%BAT_LOG_DIR%"
set "BAT_LOG=%BAT_LOG_DIR%\normalizar_raster_por_path_ultimo.log"

echo ============================================================ > "%BAT_LOG%"
echo Inicio BAT: %DATE% %TIME% >> "%BAT_LOG%"
echo Script dir: %SCRIPT_DIR% >> "%BAT_LOG%"
echo Proyecto: %PROJECT_ROOT% >> "%BAT_LOG%"
echo Python ArcGIS: %ARCGIS_PYTHON% >> "%BAT_LOG%"
echo Script Python: %SCRIPT_PATH% >> "%BAT_LOG%"

if not exist "%ARCGIS_PYTHON%" (
    echo ERROR: No se encontro Python de ArcGIS Pro:
    echo %ARCGIS_PYTHON%
    echo ERROR: No se encontro Python de ArcGIS Pro: %ARCGIS_PYTHON% >> "%BAT_LOG%"
    set "EXIT_CODE=1"
    goto FIN
)

if not exist "%SCRIPT_PATH%" (
    echo ERROR: No se encontro el script:
    echo %SCRIPT_PATH%
    echo ERROR: No se encontro el script: %SCRIPT_PATH% >> "%BAT_LOG%"
    set "EXIT_CODE=1"
    goto FIN
)

if "%~1"=="" (
    set "RASTER_PATH=%DEFAULT_RASTER_PATH%"
    set "EXTRA_ARGS=%DEFAULT_EXTRA_ARGS%"
) else (
    set "RASTER_PATH=%~1"
    shift
    if "%~1"=="" (
        set "EXTRA_ARGS=%DEFAULT_EXTRA_ARGS%"
    ) else (
        set "EXTRA_ARGS=%*"
    )
)

pushd "%PROJECT_ROOT%"
echo Raster: %RASTER_PATH%
echo Opciones: %EXTRA_ARGS%
echo Raster: %RASTER_PATH% >> "%BAT_LOG%"
echo Opciones: %EXTRA_ARGS% >> "%BAT_LOG%"
echo Ejecutando Python... >> "%BAT_LOG%"
"%ARCGIS_PYTHON%" "%SCRIPT_PATH%" "%RASTER_PATH%" %EXTRA_ARGS% 1>> "%BAT_LOG%" 2>>&1
set "EXIT_CODE=%ERRORLEVEL%"
popd

:FIN
echo Fin BAT: %DATE% %TIME% >> "%BAT_LOG%"
echo Codigo salida: %EXIT_CODE% >> "%BAT_LOG%"
echo.
echo Proceso finalizado con codigo: %EXIT_CODE%
echo Log BAT: %BAT_LOG%
echo Presione una tecla para cerrar esta ventana...
pause
exit /b %EXIT_CODE%
