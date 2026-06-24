@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "ARCGIS_PYTHON=C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"
set "SCRIPT_PATH=%SCRIPT_DIR%normalizar_raster_por_path.py"

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

if "%~1"=="" (
    echo Uso:
    echo   normalizar_raster_por_path.bat "PATH_TIF" [--name NAME_FOOTPRINT] [--apply]
    echo.
    echo Ejemplo:
    echo   normalizar_raster_por_path.bat "\\servidor\ruta\CL_MLP_PAO_IF_Ortho_26_05_10_DME7_PA7_IF6.tif" --apply
    exit /b 2
)

pushd "%PROJECT_ROOT%"
"%ARCGIS_PYTHON%" "%SCRIPT_PATH%" %*
set "EXIT_CODE=%ERRORLEVEL%"
popd

exit /b %EXIT_CODE%
