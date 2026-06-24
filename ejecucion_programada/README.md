# Ejecucion programada Geosupport

Este folder contiene el script consolidado para ejecutar el flujo completo de imagenes PAO desde una carpeta de entrada:

1. Calcula nombre final por fecha y cruce espacial contra sectores.
2. Define ruta destino en el datastore.
3. Copia las imagenes al datastore.
4. Agrega los raster al mosaic dataset.
5. Construye footprints y actualiza campos criticos del mosaico.
6. Exporta/actualiza geometria de footprints en la GDB indice.
7. Normaliza las imagenes con rasterio por subprocess.
8. Genera una copia APRX lista para revisar/publicar con capas ordenadas.

## Ejecucion de revision

```powershell
.\ejecucion_programada\ejecutar_flujo_geosupport.bat `
  "\\amssclgis10.ams.gmams.cl\CL_MLP_PAO\Vuelos_Drone_Sin_Procesar\INPUT\20260519_Geosupport"
```

Sin `--apply` no escribe en datastore, mosaic dataset, GDB ni APRX. Solo deja CSV de revision en `ejecucion_programada/outputs/<run_id>/`.

## Ejecucion real

El BAT queda configurado por defecto para esta entrada:

`\\amssclgis10.ams.gmams.cl\CL_MLP_PAO\Vuelos_Drone_Sin_Procesar\INPUT\20260206_Geosupport_segunda entrega`

Al ejecutarlo sin parametros corre esa ruta con:

`--apply --replace-originals --create-backup-before-replace --build-pyramids-after-replace`

El log de ejecucion queda en `ejecucion_programada/Logs/geosupport_flujo_programado.log`.

```powershell
.\ejecucion_programada\ejecutar_flujo_geosupport.bat
```

Tambien puede recibir otra ruta y opciones manuales si se indica el primer parametro.

La copia APRX queda por defecto en:

`ejecucion_programada/outputs/<run_id>/aprx/VISOR TERRITORIAL SIG PAO v7_resultado_<run_id>.aprx`

## Fechas externas

Si la fecha no viene en el nombre del archivo, el flujo puede leerla desde:

- `flujo_geosupport_etapas/json/fechas.json` por defecto.
- Otro JSON con `--date-json`.
- Un Excel con `--date-excel`.

Las columnas esperadas son equivalentes a `name`/`archivo`/`file_name` y `fecha`/`date`.

## Limpieza de salidas rasterio del proyecto

Para revisar que imagenes temporales/generadas por rasterio existen dentro del proyecto:

```powershell
.\ejecucion_programada\limpiar_imagenes_rasterio.bat
```

Para borrarlas:

```powershell
.\ejecucion_programada\limpiar_imagenes_rasterio.bat --apply --remove-empty-dirs
```

El limpiador solo busca dentro del directorio del proyecto y en carpetas de salida asociadas a rasterio/normalizacion. No borra imagenes del datastore.

## Normalizar un raster puntual

Para corregir una imagen especifica ya cargada, indicando su path completo:

```powershell
.\ejecucion_programada\normalizar_raster_por_path.bat `
  "\\amssclgis10.ams.gmams.cl\CL_MLP_PAO\Chacay_El_Mauro_Drone\26_05\CL_MLP_PAO_IF_Ortho_26_05_10_DME7_PA7_IF6.tif" `
  --apply
```

Si el `Name` del footprint no coincide exactamente con el nombre del archivo sin extension, se puede indicar:

```powershell
.\ejecucion_programada\normalizar_raster_por_path.bat "PATH_TIF" --name "CL_MLP_PAO_IF_Ortho_26_05_10_DME7_PA7_IF6" --apply
```

El backup del TIFF original queda en `Bkg_rasterio_normalizacion/<timestamp>/` dentro del proyecto.
