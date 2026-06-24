@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "ARCGIS_PYTHON=C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"
set "SCRIPT_PATH=%SCRIPT_DIR%geosupport_flujo_completo.py"
set "DEFAULT_INPUT_FOLDER=\\amssclgis10.ams.gmams.cl\CL_MLP_PAO\Vuelos_Drone_Sin_Procesar\INPUT\20260206_Geosupport_segunda entrega"

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
    set "INPUT_FOLDER=%DEFAULT_INPUT_FOLDER%"
    set "EXTRA_ARGS=--apply --replace-originals --create-backup-before-replace --build-pyramids-after-replace"
) else (
    set "INPUT_FOLDER=%~1"
    shift
    set "EXTRA_ARGS=%*"
)

pushd "%PROJECT_ROOT%"
echo Input folder: %INPUT_FOLDER%
echo Opciones: %EXTRA_ARGS%
"%ARCGIS_PYTHON%" "%SCRIPT_PATH%" "%INPUT_FOLDER%" %EXTRA_ARGS%
set "EXIT_CODE=%ERRORLEVEL%"
popd

:FIN
echo.
echo Proceso finalizado con codigo: %EXIT_CODE%
echo Presione una tecla para cerrar esta ventana...
pause >nul
exit /b %EXIT_CODE%
