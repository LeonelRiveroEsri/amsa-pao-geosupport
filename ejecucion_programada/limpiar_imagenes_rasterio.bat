@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "ARCGIS_PYTHON=C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"
set "SCRIPT_PATH=%SCRIPT_DIR%limpiar_imagenes_rasterio.py"

if not exist "%ARCGIS_PYTHON%" (
    echo ERROR: No se encontro Python de ArcGIS Pro:
    echo %ARCGIS_PYTHON%
    exit /b 1
)

if not exist "%SCRIPT_PATH%" (
    echo ERROR: No se encontro el script:
    echo %SCRIPT_PATH%
    exit /b 1
)

pushd "%PROJECT_ROOT%"
"%ARCGIS_PYTHON%" "%SCRIPT_PATH%" %*
set "EXIT_CODE=%ERRORLEVEL%"
popd

exit /b %EXIT_CODE%
