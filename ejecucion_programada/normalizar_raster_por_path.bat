@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "ARCGIS_PYTHON=C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"
set "SCRIPT_PATH=%SCRIPT_DIR%normalizar_raster_por_path.py"
set "DEFAULT_RASTER_PATH=\\amssclgis10.ams.gmams.cl\CL_MLP_PAO\Chacay_El_Mauro_Drone\26_05\CL_MLP_PAO_IF_Ortho_26_05_10_DME7_PA7_IF6.tif"

if not exist "%ARCGIS_PYTHON%" (
    echo ERROR: No se encontro Python de ArcGIS Pro:
    echo %ARCGIS_PYTHON%
    set "EXIT_CODE=1"
    goto FIN
)

if not exist "%SCRIPT_PATH%" (
    echo ERROR: No se encontro el script:
    echo %SCRIPT_PATH%
    set "EXIT_CODE=1"
    goto FIN
)

if "%~1"=="" (
    set "RASTER_PATH=%DEFAULT_RASTER_PATH%"
    set "EXTRA_ARGS=--apply"
) else (
    set "RASTER_PATH=%~1"
    shift
    set "EXTRA_ARGS=%*"
)

pushd "%PROJECT_ROOT%"
echo Raster: %RASTER_PATH%
echo Opciones: %EXTRA_ARGS%
"%ARCGIS_PYTHON%" "%SCRIPT_PATH%" "%RASTER_PATH%" %EXTRA_ARGS%
set "EXIT_CODE=%ERRORLEVEL%"
popd

:FIN
echo.
echo Proceso finalizado con codigo: %EXIT_CODE%
echo Presione una tecla para cerrar esta ventana...
pause >nul
exit /b %EXIT_CODE%
