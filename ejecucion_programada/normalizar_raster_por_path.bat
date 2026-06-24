@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "ARCGIS_PYTHON=C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"
set "SCRIPT_PATH=%SCRIPT_DIR%normalizar_raster_por_path.py"

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
    echo Uso:
    echo   normalizar_raster_por_path.bat "PATH_TIF" [--name NAME_FOOTPRINT] [--apply]
    echo.
    echo Ejemplo:
    echo   normalizar_raster_por_path.bat "\\servidor\ruta\CL_MLP_PAO_IF_Ortho_26_05_10_DME7_PA7_IF6.tif" --apply
    set "EXIT_CODE=2"
    goto FIN
)

pushd "%PROJECT_ROOT%"
"%ARCGIS_PYTHON%" "%SCRIPT_PATH%" %*
set "EXIT_CODE=%ERRORLEVEL%"
popd

:FIN
echo.
echo Proceso finalizado con codigo: %EXIT_CODE%
echo Presione una tecla para cerrar esta ventana...
pause >nul
exit /b %EXIT_CODE%
