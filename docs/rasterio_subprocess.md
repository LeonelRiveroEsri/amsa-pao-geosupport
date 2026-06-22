# Rasterio en ambiente aislado

El ambiente `arcgispro` debe quedarse para `arcpy`. Los procesos con `rasterio`
se ejecutan en un subproceso separado para evitar conflictos binarios con GDAL,
numpy y pandas.

## Ambiente rasterio

El flujo 04 usa este ambiente ya creado:

```text
C:\Users\esrlrivero_adm\AppData\Local\ESRI\conda\envs\geo-raster-py311
```

Validacion desde Anaconda Prompt o ArcGIS Pro Python Command Prompt:

```powershell
C:\Users\esrlrivero_adm\AppData\Local\ESRI\conda\envs\geo-raster-py311\python.exe -c "import rasterio, numpy; print(rasterio.__version__, numpy.__version__)"
```

Si se necesita recrear un ambiente alternativo:

```powershell
conda env create -f environments\rasterio.yml
conda activate geo-raster-py311
python -c "import rasterio, numpy; print(rasterio.__version__, numpy.__version__)"
```

Si el ambiente ya existe:

```powershell
conda env update -f environments\rasterio.yml --prune
```

## Uso desde el notebook 04

Ejecutar esta celda desde el kernel de ArcGIS Pro, donde `arcpy` funciona:

```python
from pathlib import Path
import sys

PROJECT_ROOT = Path.cwd()
if not (PROJECT_ROOT / "core").exists():
    for candidate in [Path.cwd().parent, Path.cwd().parent.parent]:
        if (candidate / "core").exists():
            PROJECT_ROOT = candidate
            break

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.rasterio_subprocess import run_stage_04_rasterio_subprocess

FLOW_DIR = PROJECT_ROOT / "flujo_geosupport_etapas"
OUTPUT_DIR = FLOW_DIR / "outputs" / "etapa_04_normalizar_imagenes_rasterio"

completed = run_stage_04_rasterio_subprocess(
    load_results_csv=FLOW_DIR / "outputs" / "etapa_02_carga_datastore_mosaico" / "02_load_results.csv",
    load_input_attributes_csv=FLOW_DIR / "outputs" / "etapa_02_carga_datastore_mosaico" / "01_load_input_with_attributes.csv",
    footprints_feature_class=r"\\amssclgis08.ams.gmams.cl\CL_MLP_PAO\02_FGDB\CL_MLP_PAO_v1.gdb\CL_MLP_PAO_06_COMPLEMENTOS\CL_MLP_PAO_Indice_Vuelos_PAO_IMGS_PO",
    footprint_name_field="Name",
    output_dir=OUTPUT_DIR,
    env_path=r"C:\Users\esrlrivero_adm\AppData\Local\ESRI\conda\envs\geo-raster-py311",
    process_only_successful_loads=True,
    limit_rows=None,
    replace_originals=True,
    create_backup_before_replace=False,
    build_pyramids_after_replace=False,
)

completed.returncode
```

El wrapper con `arcpy` genera un manifiesto CSV con paths y geometrias. Luego
ejecuta:

```powershell
conda run -p C:\Users\esrlrivero_adm\AppData\Local\ESRI\conda\envs\geo-raster-py311 python core\rasterio_normalize_worker.py ...
```

El worker no importa `arcpy` ni `pandas`.
