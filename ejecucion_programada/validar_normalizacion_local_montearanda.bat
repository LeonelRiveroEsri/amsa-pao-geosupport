@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "ARCGIS_PYTHON=C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"
set "SCRIPT_PATH=%SCRIPT_DIR%normalizar_raster_por_path.py"
set "RASTER_PATH=D:\Developer\VacacionesOthman\GeoSupport\Bkg_rasterio_normalizacion\20260624_135901\CL_MLP_PAO_IF_Ortho_26_05_02_MonteAranda-NSTC-Km-84p2-a-82p3.tif"
set "FOOTPRINTS_FC=D:\Developer\VacacionesOthman\GeoSupport\Bkg_rasterio_normalizacion\DATA.gdb\FOOPRINT"
set "RASTERIO_ENV=D:\Env\geo-raster-py311"
set "BAT_LOG_DIR=%SCRIPT_DIR%outputs\bat_logs"
if not exist "%BAT_LOG_DIR%" mkdir "%BAT_LOG_DIR%"
set "BAT_LOG=%BAT_LOG_DIR%\validar_normalizacion_local_montearanda_ultimo.log"

echo ============================================================ > "%BAT_LOG%"
echo Inicio BAT: %DATE% %TIME% >> "%BAT_LOG%"
echo Proyecto: %PROJECT_ROOT% >> "%BAT_LOG%"
echo Raster: %RASTER_PATH% >> "%BAT_LOG%"
echo Footprints: %FOOTPRINTS_FC% >> "%BAT_LOG%"
echo Rasterio env: %RASTERIO_ENV% >> "%BAT_LOG%"

if not exist "%ARCGIS_PYTHON%" (
    echo ERROR: No se encontro Python de ArcGIS Pro: %ARCGIS_PYTHON%
    echo ERROR: No se encontro Python de ArcGIS Pro: %ARCGIS_PYTHON% >> "%BAT_LOG%"
    set "EXIT_CODE=1"
    goto FIN
)

if not exist "%SCRIPT_PATH%" (
    echo ERROR: No se encontro el script: %SCRIPT_PATH%
    echo ERROR: No se encontro el script: %SCRIPT_PATH% >> "%BAT_LOG%"
    set "EXIT_CODE=1"
    goto FIN
)

pushd "%PROJECT_ROOT%"
echo Ejecutando validacion local sin reemplazar origen...
"%ARCGIS_PYTHON%" "%SCRIPT_PATH%" "%RASTER_PATH%" --footprints-fc "%FOOTPRINTS_FC%" --review-only --mask-black-background --black-threshold 35 --rasterio-env "%RASTERIO_ENV%" 1>> "%BAT_LOG%" 2>>&1
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
