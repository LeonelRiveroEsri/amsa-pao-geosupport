from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from core.mosaic_image_audit import (
    DEFAULT_RENAMED_EXTENSION,
    ORTHO_MOSAIC_EXTENSIONS,
    RENAME_PREFIX,
    add_expected_names_with_spatial_sector,
    calculate_spatial_sector_matches,
    date_token_from_iso_date,
    export_no_match_extent_features,
    format_spatial_sector_token,
    normalize_key,
    resolve_duplicate_expected_names,
    scan_input_images,
)
from core.mosaic_loader import (
    LOWPS_VALUE,
    MAXPS_VALUE,
    MINPS_VALUE,
    process_mosaic_load_row,
)
from core.rasterio_subprocess import DEFAULT_RASTERIO_ENV_PATH, run_stage_04_rasterio_subprocess
from core.esrilogs import Logfile


try:
    import arcpy
except ImportError as exc:
    raise RuntimeError("Este script debe ejecutarse con el Python de ArcGIS Pro.") from exc


PATH_MOSAIC_DATASET = (
    r"\\amssclgis08.ams.gmams.cl\CL_MLP_PAO\01_Proyectos_ArcGIS\APRX"
    r"\CL MLP PAO Aereo Image Server_v2\SQLServer-amssclgis06_ArcGIS-Aereo.sde"
    r"\OWD.CL_MLP_PAO_IF_Ortho_Geosupport"
)
PATH_FC_FOOTPRINT_INDICE = (
    r"\\amssclgis08.ams.gmams.cl\CL_MLP_PAO\02_FGDB\CL_MLP_PAO_v1.gdb"
    r"\CL_MLP_PAO_06_COMPLEMENTOS\CL_MLP_PAO_Indice_Vuelos_PAO_IMGS_PO"
)
DATASTORE_ROOT = r"\\amssclgis10.ams.gmams.cl\CL_MLP_PAO"
APRX_PATH = r"\\amssclgis08.ams.gmams.cl\CL_MLP_PAO\01_Proyectos_ArcGIS\APRX\VISOR TERRITORIAL SIG PAO v7.aprx"
APRX_MAP_NAME = "CL MLP PAO 27 Imagenes Aereas PAO Image Server"
APRX_PARENT_GROUP_NAME = "Vuelos Drone PAO"
APRX_TARGET_GROUP_NAME = "Imagenes Drone"

IMAGE_SERVICE_NAME = "CL_MLP_PAO_IF_Ortho_Geosupport"
PROJECT_VALUE = "PAO"
SENSOR_VALUE = "DJI Mavic Enterprise"
FOOTPRINT_NAME_FIELD = "Name"

PRIMARY_SECTOR_WHERE = "Sensor <> 'DJI MATRICE 350 RTK'"
FALLBACK_SECTOR_WHERE = "Sensor = 'DJI MATRICE 350 RTK'"

DEFAULT_DATE_JSON = PROJECT_ROOT / "flujo_geosupport_etapas" / "json" / "fechas.json"


DESTINATION_FOLDER_BY_SECTOR = {
    "Camino_Alternativo_Salamanca": "El_Mauro_Drone",
    "DME9-PA12-IIFF8": "Chacay_El_Mauro_Drone",
    "EBD": "El_Mauro_Drone",
    "ED1": "Chacay_El_Mauro_Drone",
    "ED2": "Chacay_El_Mauro_Drone",
    "EDT": "Puerto_Punta_Chungo_Drone",
    "EM1": "Chacay_Drone",
    "EM2_S2": "Chacay_El_Mauro_Drone",
    "EM3": "Chacay_El_Mauro_Drone",
    "Estacion_Cabecera": "Chacay_Drone",
    "Estacion_Intermedia": "Chacay_El_Mauro_Drone",
    "EV1": "Chacay_El_Mauro_Drone",
    "EV2": "El_Mauro_Puerto_Punta_Chungo_Drone",
    "Helipuerto": "El_Mauro_Drone",
    "Chacay_El_Mauro_Drone": "Chacay_El_Mauro_Drone",
    "DME7_PA7_IF6": "Chacay_El_Mauro_Drone",
    "DME_13": "Chacay_El_Mauro_Drone",
    "MonteAranda-NSTC-Km-84p2-a-82p3": "Chacay_El_Mauro_Drone",
    "NSTC_km_4p4_a_7p0": "Chacay_Drone",
    "Orejas17_Ruta-D-865": "El_Mauro_Puerto_Punta_Chungo_Drone",
    "Patio-19B-y-Armado": "Chacay_El_Mauro_Drone",
    "SRA-2-km-56p1-a-57p7-Area-2": "Chacay_Drone",
    "SRA_2_km_54p6_a_56p1_Area-1": "Chacay_Drone",
    "Subestacion-El-Mauro": "El_Mauro_Drone",
    "Subestacion-El-Mauro_A_E35": "El_Mauro_Drone",
    "TORRE_E85_A_E_125": "Chacay_El_Mauro_Drone",
    "TORRES_E31_A_E48_PV4": "Chacay_El_Mauro_Drone",
    "TORRES_E48_A_E84_PV4": "Chacay_El_Mauro_Drone",
}

DESTINATION_FOLDER_BY_FILE_NAME = {
    "GEOSP-TRN-002603_ORTOFOTO_CORTADA_EM2_100526.tif": "Chacay_El_Mauro_Drone",
    "GEOSP-TRN-002615_GS_ORTOFOTO_ESTACION DE MONITOREO NÂ°2_13-05-2026.tif": "El_Mauro_Drone",
    "GEOSP-TRN-002617_GS_ORTOFOTO_SUBESTACION_EL MAURO_PRIORIDAD 1_13_05_26.tif": "Chacay_El_Mauro_Drone",
    "GEOSP-TRN-002545_GS_ORTOFOTO_EB3_06-05-26.tif": "El_Mauro_Drone",
    "GEOSP-TRN-002546_GS_ORTOFOTO_SSEE_06-05-26.tif": "El_Mauro_Drone",
    "GEOSP-TRN-002621_GS_ORTOFOTO_ESTACION DE BOMBEO NÂº3_13_05_26.tif": "El_Mauro_Drone",
}

SPATIAL_SECTOR_BY_FILE_NAME = {
    "GEOSP-TRN-002517_1001-03-T-CS-202-5600-C-DW-11486[000].tif": "Chacay_El_Mauro_Drone",
    "GEOSP-TRN-002580_GS_Ortofoto Deposito Patio Pulmon.tif": "Chacay_El_Mauro_Drone",
}


LOGGER = None


def log(message: str) -> None:
    if LOGGER is not None:
        LOGGER.info(message)
    else:
        print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def log_warning(message: str) -> None:
    if LOGGER is not None:
        LOGGER.warning(message)
    else:
        print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] WARN - {message}", flush=True)


def log_error(message: str) -> None:
    if LOGGER is not None:
        LOGGER.error(message)
    else:
        print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] ERROR - {message}", flush=True)


def log_dataframe(df: pd.DataFrame, max_rows: int = 20) -> None:
    if LOGGER is not None and isinstance(df, pd.DataFrame):
        LOGGER.dataframe(df.head(max_rows))


def write_df(df: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def date_token_to_iso(date_token: str | None) -> str | None:
    if not date_token or pd.isna(date_token):
        return None
    match = re.match(r"^(\d{2})_(\d{2})_(\d{2})$", str(date_token))
    if not match:
        return None
    yy, mm, dd = match.groups()
    return f"20{yy}-{mm}-{dd}"


def today_iso() -> str:
    return dt.date.today().isoformat()


def add_date_lookup_keys(lookup: dict, name: str, date_value: str) -> None:
    date_match = date_token_from_iso_date(date_value)
    if not date_match:
        return

    keys = {
        normalize_key(name),
        normalize_key(Path(str(name)).stem),
    }
    trn_match = re.search(r"GEOSP[-_ ]?TRN[-_ ]?(\d+)", str(name), flags=re.IGNORECASE)
    if trn_match:
        keys.add(f"geosp_trn_{trn_match.group(1)}")

    for key in keys:
        if key:
            lookup[key] = date_match


def load_date_lookup(json_path: Path | None = None, excel_path: Path | None = None) -> dict:
    lookup: dict = {}

    if json_path and json_path.exists():
        rows = json.loads(json_path.read_text(encoding="utf-8-sig"))
        for row in rows:
            name = row.get("name") or row.get("archivo") or row.get("file_name")
            fecha = row.get("fecha") or row.get("date")
            if name and fecha:
                add_date_lookup_keys(lookup, str(name), str(fecha))

    if excel_path and excel_path.exists():
        excel_df = pd.read_excel(excel_path)
        normalized_columns = {normalize_key(col): col for col in excel_df.columns}
        name_col = next(
            (normalized_columns[key] for key in ["name", "archivo", "file_name", "nombre"] if key in normalized_columns),
            None,
        )
        date_col = next(
            (normalized_columns[key] for key in ["fecha", "date", "fecha_adqui", "fecha_adquisicion"] if key in normalized_columns),
            None,
        )
        if not name_col or not date_col:
            raise ValueError(f"El Excel de fechas no tiene columnas reconocibles de nombre/fecha: {excel_path}")
        for _, row in excel_df.iterrows():
            if pd.notna(row.get(name_col)) and pd.notna(row.get(date_col)):
                add_date_lookup_keys(lookup, str(row[name_col]), str(row[date_col])[:10])

    return lookup


def merge_spatial_primary_fallback(primary_df: pd.DataFrame, fallback_df: pd.DataFrame) -> pd.DataFrame:
    result = primary_df.copy()
    if "spatial_query_source" not in result.columns:
        result["spatial_query_source"] = "sensor_activo"

    fallback_by_path = fallback_df.set_index("path").to_dict("index") if not fallback_df.empty else {}
    for index, row in result[result["spatial_status"].ne("ok")].iterrows():
        fallback = fallback_by_path.get(row.get("path"))
        if not fallback or fallback.get("spatial_status") != "ok":
            continue
        for column, value in fallback.items():
            if column in result.columns:
                result.at[index, column] = value
        result.at[index, "spatial_query_source"] = "sensor_excluido"
    return result


def apply_manual_spatial_exceptions(spatial_df: pd.DataFrame) -> pd.DataFrame:
    result = spatial_df.copy()
    exception_lookup = {normalize_key(name): sector for name, sector in SPATIAL_SECTOR_BY_FILE_NAME.items()}
    exception_lookup.update({normalize_key(Path(name).stem): sector for name, sector in SPATIAL_SECTOR_BY_FILE_NAME.items()})

    for index, row in result[result["spatial_status"].ne("ok")].iterrows():
        keys = [normalize_key(row.get("file_name")), normalize_key(Path(str(row.get("file_name"))).stem)]
        sector = next((exception_lookup[key] for key in keys if key in exception_lookup), None)
        if not sector:
            continue
        result.at[index, "spatial_status"] = "ok"
        result.at[index, "spatial_sector_raw"] = sector
        result.at[index, "spatial_sector"] = format_spatial_sector_token(sector)
        result.at[index, "spatial_overlap_area"] = 0
        result.at[index, "spatial_overlap_pct"] = 0
        result.at[index, "spatial_overlap_count"] = 0
        result.at[index, "spatial_query_source"] = "excepcion_espacial_manual"
    return result


def destination_folder_for_row(row: pd.Series) -> str | None:
    file_name = str(row.get("file_name"))
    if file_name in DESTINATION_FOLDER_BY_FILE_NAME:
        return DESTINATION_FOLDER_BY_FILE_NAME[file_name]

    sector = row.get("spatial_sector_raw") or row.get("expected_sector")
    if not sector or pd.isna(sector):
        return None

    sector_text = str(sector).strip().replace(" ", "_")
    return DESTINATION_FOLDER_BY_SECTOR.get(sector_text)


def add_destination_paths(df: pd.DataFrame, datastore_root: str) -> pd.DataFrame:
    result = df.copy()
    result["destination_folder"] = result.apply(destination_folder_for_row, axis=1)
    result["destination_date_folder"] = result["expected_date_token"].map(
        lambda token: str(token)[:5] if token and not pd.isna(token) else None
    )
    result["destination_path"] = result.apply(
        lambda row: str(
            Path(datastore_root)
            / str(row["destination_folder"])
            / str(row["destination_date_folder"])
            / str(row["expected_file_name"])
        )
        if row.get("destination_folder")
        and row.get("destination_date_folder")
        and row.get("expected_file_name")
        and not pd.isna(row.get("expected_file_name"))
        else None,
        axis=1,
    )
    result["review_reason"] = result.apply(review_reason, axis=1)
    return result


def review_reason(row: pd.Series) -> str | None:
    reasons = []
    if row.get("rename_status") != "ok":
        reasons.append(str(row.get("rename_status")))
    if not row.get("destination_folder") or pd.isna(row.get("destination_folder")):
        reasons.append("sin_mapeo_datastore")
    if not row.get("destination_path") or pd.isna(row.get("destination_path")):
        reasons.append("sin_path_destino")
    return "|".join(reasons) if reasons else None


def prepare_paths_stage(input_folder: Path, output_dir: Path, date_json: Path | None, date_excel: Path | None) -> dict:
    log("Etapa 01: preparando paths de datastore")
    output_dir.mkdir(parents=True, exist_ok=True)

    date_lookup = load_date_lookup(date_json, date_excel)
    images_df = scan_input_images(input_folder, extensions=ORTHO_MOSAIC_EXTENSIONS)
    write_df(images_df, output_dir / "01_input_images.csv")
    write_df(
        pd.DataFrame(
            [{"key": key, "date_token": value["date_token"], "date_source": value.get("date_source")} for key, value in date_lookup.items()]
        ),
        output_dir / "06_date_dictionary.csv",
    )

    primary_df = calculate_spatial_sector_matches(
        images_df,
        PATH_FC_FOOTPRINT_INDICE,
        sector_field="Sector",
        where_clause=PRIMARY_SECTOR_WHERE,
    )
    fallback_df = calculate_spatial_sector_matches(
        images_df[primary_df["spatial_status"].ne("ok")].copy(),
        PATH_FC_FOOTPRINT_INDICE,
        sector_field="Sector",
        where_clause=FALLBACK_SECTOR_WHERE,
    )
    spatial_df = merge_spatial_primary_fallback(primary_df, fallback_df)
    spatial_df = apply_manual_spatial_exceptions(spatial_df)
    write_df(spatial_df, output_dir / "02_spatial_matches.csv")

    no_match_fc = export_no_match_extent_features(
        spatial_df,
        PROJECT_ROOT / "Dataset" / "data.gdb",
        feature_class_name="spatial_no_match_extents",
    )

    expected_df = add_expected_names_with_spatial_sector(images_df, spatial_df, date_lookup=date_lookup)
    expected_df = resolve_duplicate_expected_names(expected_df)
    manifest_df = add_destination_paths(expected_df, DATASTORE_ROOT)

    ready_df = manifest_df[manifest_df["review_reason"].isna()].copy()
    review_df = manifest_df[manifest_df["review_reason"].notna()].copy()

    write_df(manifest_df, output_dir / "03_manifest_paths_datastore.csv")
    write_df(ready_df, output_dir / "04_ready_for_datastore.csv")
    write_df(review_df, output_dir / "05_review_required.csv")

    summary_df = pd.DataFrame(
        [
            {"metric": "input_folder", "value": str(input_folder)},
            {"metric": "input_images", "value": len(images_df)},
            {"metric": "ready_for_datastore", "value": len(ready_df)},
            {"metric": "review_required", "value": len(review_df)},
            {"metric": "spatial_no_match_feature_class", "value": no_match_fc or ""},
            {"metric": "date_dictionary_entries", "value": len(date_lookup)},
        ]
    )
    write_df(summary_df, output_dir / "00_summary.csv")
    log_dataframe(summary_df)
    if not review_df.empty:
        log_warning(f"Etapa 01 dejo {len(review_df)} imagenes para revision")
        log_dataframe(review_df[["file_name", "review_reason"]])
    return {"ready_df": ready_df, "review_df": review_df, "manifest_df": manifest_df}


def build_url(destination_folder: str, destination_date_folder: str, expected_file_name: str) -> str:
    relative_file_id = f".\\{destination_folder}\\{destination_date_folder}\\{expected_file_name}"
    return (
        f"https://sig.aminerals.cl/imgdyn/rest/services/CL_MLP_PAO/{IMAGE_SERVICE_NAME}"
        f"/ImageServer/file?id={relative_file_id}&rasterId="
    )


def build_load_attributes(ready_df: pd.DataFrame) -> pd.DataFrame:
    df = ready_df.copy()
    df["Name"] = df["expected_name"]
    df["Raster"] = df["expected_file_name"]
    df["Path_Destino"] = df["destination_path"]
    df["Sector"] = df["spatial_sector_raw"]
    df["Fecha_Adqui"] = df["expected_date_token"].map(date_token_to_iso)
    df["URL"] = df.apply(
        lambda row: build_url(row["destination_folder"], row["destination_date_folder"], row["expected_file_name"]),
        axis=1,
    )
    df["Proyecto"] = PROJECT_VALUE
    df["Sensor"] = SENSOR_VALUE
    df["Fecha_Publ"] = today_iso()
    df["MaxPS"] = MAXPS_VALUE
    df["LowPS"] = LOWPS_VALUE
    df["MinPS"] = MINPS_VALUE
    df["ProductName"] = "OBJECTID del registro en el mosaic dataset"
    return df


def load_mosaic_stage(ready_df: pd.DataFrame, output_dir: Path, apply_changes: bool, overwrite_copy: bool) -> dict:
    log("Etapa 02: copiando al datastore y cargando al mosaic dataset")
    output_dir.mkdir(parents=True, exist_ok=True)
    load_df = build_load_attributes(ready_df)
    write_df(load_df, output_dir / "01_load_input_with_attributes.csv")

    results = []
    for index, row in load_df.iterrows():
        log(f"{index + 1}/{len(load_df)} - {row['Name']}")
        result = process_mosaic_load_row(
            row,
            PATH_MOSAIC_DATASET,
            overwrite_copy=overwrite_copy,
            skip_existing_mosaic_name=True,
            maxps_value=MAXPS_VALUE,
            lowps_value=LOWPS_VALUE,
            minps_value=MINPS_VALUE,
            dry_run=not apply_changes,
        )
        results.append(result)

    results_df = pd.DataFrame(results)
    write_df(results_df, output_dir / "02_load_results.csv")
    errors_df = results_df[
        ~results_df.get("overall_status", pd.Series(dtype=str)).astype(str).str.lower().isin(["ok", "dry_run"])
    ].copy()
    write_df(errors_df, output_dir / "03_errors_review.csv")

    summary_rows = [
        {"metric": "apply_changes", "value": apply_changes},
        {"metric": "input_ready", "value": len(load_df)},
        {"metric": "errors", "value": len(errors_df)},
    ]
    if not results_df.empty and "overall_status" in results_df.columns:
        for status, count in results_df["overall_status"].value_counts(dropna=False).items():
            summary_rows.append({"metric": f"overall_status_{status}", "value": int(count)})
    summary_df = pd.DataFrame(summary_rows)
    write_df(summary_df, output_dir / "00_summary.csv")
    log_dataframe(summary_df)
    if not errors_df.empty:
        log_warning(f"Etapa 02 dejo {len(errors_df)} errores para revision")
        log_dataframe(errors_df)
    return {"load_df": load_df, "results_df": results_df}


def quote_sql(value: object) -> str:
    return str(value).replace("'", "''")


def where_in_names(names: Iterable[str], field_name: str = "Name") -> str:
    values = sorted({str(name) for name in names if name and not pd.isna(name)})
    if not values:
        return "1 = 0"
    chunks = []
    for start in range(0, len(values), 900):
        subset = values[start : start + 900]
        quoted_values = ", ".join("'" + quote_sql(value) + "'" for value in subset)
        chunks.append(f"{field_name} IN ({quoted_values})")
    return " OR ".join(chunks)


def arcpy_rows_to_df(dataset: str, fields: list[str], where_clause: str | None = None) -> pd.DataFrame:
    rows = []
    with arcpy.da.SearchCursor(dataset, fields, where_clause=where_clause) as cursor:
        for row in cursor:
            rows.append(dict(zip(fields, row)))
    return pd.DataFrame(rows)


def existing_names(feature_class: str, names: list[str]) -> set[str]:
    if not names:
        return set()
    where = where_in_names(names)
    found = set()
    with arcpy.da.SearchCursor(feature_class, ["Name"], where_clause=where) as cursor:
        for (name,) in cursor:
            if name:
                found.add(str(name))
    return found


def ensure_scratch_gdb(output_dir: Path) -> Path:
    gdb = output_dir / "scratch.gdb"
    if not arcpy.Exists(str(gdb)):
        output_dir.mkdir(parents=True, exist_ok=True)
        arcpy.management.CreateFileGDB(str(output_dir), gdb.name)
    return gdb


def field_names(dataset: str) -> set[str]:
    return {field.name for field in arcpy.ListFields(dataset)}


def alter_field_if_possible(dataset: str, old_name: str, new_name: str) -> None:
    fields = field_names(dataset)
    if old_name in fields and new_name not in fields:
        arcpy.management.AlterField(dataset, old_name, new_name)


def successful_stage2_names(results_df: pd.DataFrame, load_df: pd.DataFrame) -> list[str]:
    if results_df.empty:
        return []
    ok = pd.Series(False, index=results_df.index)
    if "overall_status" in results_df.columns:
        ok = ok | results_df["overall_status"].astype(str).str.lower().isin(["ok"])
    if "mosaic_add_status" in results_df.columns:
        ok = ok | results_df["mosaic_add_status"].astype(str).str.lower().isin(["added", "already_exists"])
    if not ok.any() and "overall_status" in results_df.columns and results_df["overall_status"].astype(str).str.lower().eq("dry_run").all():
        return load_df["Name"].dropna().astype(str).tolist()
    return results_df.loc[ok, "Name"].dropna().astype(str).tolist()


def update_footprints_stage(load_df: pd.DataFrame, results_df: pd.DataFrame, output_dir: Path, apply_changes: bool) -> dict:
    log("Etapa 03: actualizando geometria indice de footprints")
    output_dir.mkdir(parents=True, exist_ok=True)
    names = successful_stage2_names(results_df, load_df)
    names_df = pd.DataFrame({"Name": names})
    write_df(names_df, output_dir / "01_stage_2_names.csv")

    if not apply_changes:
        summary_df = pd.DataFrame([{"metric": "apply_changes", "value": False}])
        write_df(summary_df, output_dir / "00_summary.csv")
        log_dataframe(summary_df)
        return {"names_to_append": names}

    existing = existing_names(PATH_FC_FOOTPRINT_INDICE, names)
    names_to_append = [name for name in names if name not in existing]
    write_df(pd.DataFrame({"Name": names_to_append}), output_dir / "02_names_to_append.csv")

    export_fc = ""
    if names_to_append:
        scratch_gdb = ensure_scratch_gdb(output_dir)
        export_fc = str(scratch_gdb / "footprints_export")
        if arcpy.Exists(export_fc):
            arcpy.management.Delete(export_fc)

        where = where_in_names(names_to_append)
        arcpy.management.ExportMosaicDatasetGeometry(
            in_mosaic_dataset=PATH_MOSAIC_DATASET,
            out_feature_class=export_fc,
            where_clause=where,
            geometry_type="FOOTPRINT",
        )

        field_map = {
            "FechaAdqui": "Fecha_Adqu",
            "FechaCarga": "Fecha_Publ",
            "NombreVuelo": "Nombre_de_Vuelo",
            "ProductName": "ProductNam",
        }
        for old_name, new_name in field_map.items():
            alter_field_if_possible(export_fc, old_name, new_name)

        arcpy.management.Append(export_fc, PATH_FC_FOOTPRINT_INDICE, "NO_TEST", "")

    updates = recalculate_nombre_vuelo(PATH_FC_FOOTPRINT_INDICE)
    write_df(pd.DataFrame(updates), output_dir / "03_nombre_vuelo_recalculado.csv")
    mosaic_updates = update_mosaic_nombre_vuelo_from_footprints(names)
    write_df(pd.DataFrame(mosaic_updates), output_dir / "04_mosaic_nombre_vuelo_updates.csv")

    summary_df = pd.DataFrame(
        [
            {"metric": "stage_2_names", "value": len(names)},
            {"metric": "already_in_footprint_fc", "value": len(existing)},
            {"metric": "appended_to_footprint_fc", "value": len(names_to_append)},
            {"metric": "export_fc", "value": export_fc},
            {"metric": "nombre_vuelo_updates", "value": len(updates)},
            {"metric": "mosaic_nombre_vuelo_updates", "value": len(mosaic_updates)},
        ]
    )
    write_df(summary_df, output_dir / "00_summary.csv")
    log_dataframe(summary_df)
    return {"names_to_append": names_to_append}


def recalculate_nombre_vuelo(feature_class: str) -> list[dict]:
    rows = []
    fields = ["Name", "Nombre_de_Vuelo", "Sector", "Fecha_Adqu"]
    available = field_names(feature_class)
    if not set(fields).issubset(available):
        return [{"status": "missing_fields", "missing": "|".join(sorted(set(fields) - available))}]

    with arcpy.da.UpdateCursor(feature_class, fields, sql_clause=(None, "ORDER BY Name ASC")) as cursor:
        count = 0
        for row in cursor:
            name, _, sector, fecha = row
            if sector and fecha:
                count += 1
                fecha_token = pd.to_datetime(fecha).strftime("%y_%m_%d")
                nombre_vuelo = f"{str(count).zfill(3)}_{fecha_token}_{sector}"
                row[1] = nombre_vuelo
                cursor.updateRow(row)
                rows.append({"Name": name, "Nombre_de_Vuelo": nombre_vuelo, "Sector": sector, "Fecha_Adqu": fecha})
    return rows


def update_mosaic_nombre_vuelo_from_footprints(names: list[str]) -> list[dict]:
    if not names:
        return []
    where = where_in_names(names)
    lookup = {}
    with arcpy.da.SearchCursor(PATH_FC_FOOTPRINT_INDICE, ["Name", "Nombre_de_Vuelo"], where_clause=where) as cursor:
        for name, nombre_vuelo in cursor:
            if name and nombre_vuelo:
                lookup[str(name)] = nombre_vuelo

    updates = []
    if not lookup:
        return updates

    fields = ["Name", "NombreVuelo"]
    if "NombreVuelo" not in field_names(PATH_MOSAIC_DATASET):
        return [{"status": "missing_field", "field": "NombreVuelo"}]

    with arcpy.da.UpdateCursor(PATH_MOSAIC_DATASET, fields, where_clause=where_in_names(lookup.keys())) as cursor:
        for row in cursor:
            name = str(row[0])
            new_value = lookup.get(name)
            if new_value and row[1] != new_value:
                old_value = row[1]
                row[1] = new_value
                cursor.updateRow(row)
                updates.append({"Name": name, "old_NombreVuelo": old_value, "new_NombreVuelo": new_value})
    return updates


def run_rasterio_stage(load_results_csv: Path, load_input_csv: Path, output_dir: Path, args) -> None:
    if args.skip_rasterio:
        log("Etapa 04 omitida por --skip-rasterio")
        return
    if not args.apply:
        log("Etapa 04 omitida en dry-run. Use --apply para ejecutar rasterio.")
        return

    log("Etapa 04: normalizando imagenes con rasterio por subprocess")
    output_dir.mkdir(parents=True, exist_ok=True)
    run_stage_04_rasterio_subprocess(
        load_results_csv=load_results_csv,
        load_input_attributes_csv=load_input_csv,
        footprints_feature_class=PATH_FC_FOOTPRINT_INDICE,
        footprint_name_field=FOOTPRINT_NAME_FIELD,
        output_dir=output_dir,
        env_path=args.rasterio_env,
        process_only_successful_loads=True,
        replace_originals=args.replace_originals,
        create_backup_before_replace=args.create_backup_before_replace,
        build_pyramids_after_replace=args.build_pyramids_after_replace,
    )
    summary_csv = output_dir / "00_summary.csv"
    if summary_csv.exists():
        log_dataframe(pd.read_csv(summary_csv))


def layer_long_name(layer) -> str:
    try:
        return layer.longName
    except Exception:
        return layer.name


def short_image_name(value: object) -> str:
    name = Path(str(value)).name
    while name.startswith("tmp_"):
        name = name.replace("tmp_", "", 1)
    if name.startswith(RENAME_PREFIX + "_"):
        name = name.replace(RENAME_PREFIX + "_", "", 1)
    elif name.startswith(RENAME_PREFIX):
        name = name.replace(RENAME_PREFIX, "", 1)
    for suffix in [".tif", ".tiff"]:
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name


def image_keys(value: object) -> set[str]:
    short = short_image_name(value)
    return {
        short.lower(),
        f"{RENAME_PREFIX}_{short}".lower(),
        f"{RENAME_PREFIX}_{short}{DEFAULT_RENAMED_EXTENSION}".lower(),
        f"{short}{DEFAULT_RENAMED_EXTENSION}".lower(),
    }


def image_date_sort_key(name: object) -> tuple:
    short = short_image_name(name)
    match = re.match(r"^(\d{2})_(\d{2})_(\d{2})_(.*)$", short)
    if not match:
        return (0, 0, 0, short.lower())
    yy, mm, dd, rest = match.groups()
    return (int(yy), int(mm), int(dd), rest.lower())


def find_group(map_obj, group_name: str, parent_group=None):
    matches = []
    for layer in map_obj.listLayers():
        if not layer.isGroupLayer or layer.name != group_name:
            continue
        if parent_group is not None:
            expected_prefix = layer_long_name(parent_group) + "\\"
            if not layer_long_name(layer).startswith(expected_prefix):
                continue
        matches.append(layer)
    if not matches:
        raise ValueError(f"No se encontro el grupo {group_name}.")
    return matches[0]


def is_direct_child(layer, group_layer) -> bool:
    long_name = layer_long_name(layer)
    prefix = layer_long_name(group_layer) + "\\"
    if not long_name.startswith(prefix):
        return False
    return "\\" not in long_name[len(prefix) :]


def direct_raster_children(map_obj, group_layer) -> list:
    return [
        layer
        for layer in map_obj.listLayers()
        if layer != group_layer and is_direct_child(layer, group_layer) and layer.isRasterLayer and not layer.isGroupLayer
    ]


def add_raster_directly_to_group(map_obj, group_layer, raster_path: str, target_name: str):
    before = {layer_long_name(layer) for layer in direct_raster_children(map_obj, group_layer)}
    temp_layer = map_obj.addDataFromPath(raster_path)
    temp_layer.name = target_name
    try:
        map_obj.addLayerToGroup(group_layer, temp_layer, "TOP")
    finally:
        map_obj.removeLayer(temp_layer)

    after_layers = direct_raster_children(map_obj, group_layer)
    new_layers = [layer for layer in after_layers if layer_long_name(layer) not in before]
    if new_layers:
        new_layers[0].name = target_name
        return new_layers[0]

    target_keys = image_keys(target_name)
    for layer in after_layers:
        if image_keys(layer.name).intersection(target_keys):
            layer.name = target_name
            return layer
    return None


def move_to_top_inside_group(map_obj, group_layer, layer_to_move) -> None:
    children = direct_raster_children(map_obj, group_layer)
    if not children or children[0] == layer_to_move:
        return
    map_obj.moveLayer(children[0], layer_to_move, "BEFORE")


def order_group_newest_first(map_obj, group_layer) -> None:
    ordered = sorted(direct_raster_children(map_obj, group_layer), key=lambda layer: image_date_sort_key(layer.name), reverse=True)
    for layer in reversed(ordered):
        move_to_top_inside_group(map_obj, group_layer, layer)


def normalize_group_layer_names(map_obj, group_layer) -> int:
    renamed = 0
    for layer in direct_raster_children(map_obj, group_layer):
        new_name = short_image_name(layer.name)
        if layer.name != new_name:
            layer.name = new_name
            renamed += 1
    return renamed


def prepare_aprx_stage(load_df: pd.DataFrame, results_df: pd.DataFrame, output_dir: Path, aprx_output: Path, apply_changes: bool) -> None:
    log("Etapa 05: preparando APRX de publicacion")
    output_dir.mkdir(parents=True, exist_ok=True)
    names = successful_stage2_names(results_df, load_df)
    if names:
        paths_df = load_df[load_df["Name"].isin(names)].copy()
    else:
        paths_df = load_df.copy() if not apply_changes else load_df.iloc[0:0].copy()

    aprx_results = []
    if not apply_changes:
        paths_df[["Name", "destination_path"]].to_csv(output_dir / "01_aprx_candidates.csv", index=False, encoding="utf-8-sig")
        summary_df = pd.DataFrame([{"metric": "apply_changes", "value": False}])
        write_df(summary_df, output_dir / "00_summary.csv")
        log_dataframe(summary_df)
        return

    aprx = arcpy.mp.ArcGISProject(APRX_PATH)
    try:
        maps = aprx.listMaps(APRX_MAP_NAME)
        if not maps:
            raise ValueError(f"No se encontro el mapa: {APRX_MAP_NAME}")
        map_obj = maps[0]
        parent_group = find_group(map_obj, APRX_PARENT_GROUP_NAME)
        target_group = find_group(map_obj, APRX_TARGET_GROUP_NAME, parent_group)

        existing_keys = set()
        for layer in direct_raster_children(map_obj, target_group):
            existing_keys.update(image_keys(layer.name))

        for _, row in paths_df.iterrows():
            raster_path = str(row["destination_path"])
            target_name = short_image_name(raster_path)
            record = {"raster_path": raster_path, "target_name": target_name, "status": None, "error": ""}
            if image_keys(target_name).intersection(existing_keys):
                record["status"] = "skipped_existing"
                aprx_results.append(record)
                continue
            try:
                add_raster_directly_to_group(map_obj, target_group, raster_path, target_name)
                existing_keys.update(image_keys(target_name))
                record["status"] = "added"
            except Exception as exc:
                record["status"] = "error"
                record["error"] = str(exc)
            aprx_results.append(record)

        renamed_count = normalize_group_layer_names(map_obj, target_group)
        order_group_newest_first(map_obj, target_group)
        final_layers = direct_raster_children(map_obj, target_group)

        aprx_output.parent.mkdir(parents=True, exist_ok=True)
        aprx.saveACopy(str(aprx_output))
        write_df(pd.DataFrame(aprx_results), output_dir / "01_aprx_update_results.csv")
        summary_df = pd.DataFrame(
            [
                {"metric": "aprx_source", "value": APRX_PATH},
                {"metric": "aprx_output", "value": str(aprx_output)},
                {"metric": "target_group", "value": f"{APRX_PARENT_GROUP_NAME} > {APRX_TARGET_GROUP_NAME}"},
                {"metric": "candidates", "value": len(paths_df)},
                {"metric": "renamed_layers", "value": renamed_count},
                {"metric": "final_layers_in_group", "value": len(final_layers)},
            ]
        )
        write_df(summary_df, output_dir / "00_summary.csv")
        log_dataframe(summary_df)
    finally:
        del aprx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ejecuta el flujo completo Geosupport: paths, datastore, mosaico, footprints, rasterio y APRX."
    )
    parser.add_argument("input_folder", help="Folder raiz con las imagenes nuevas.")
    parser.add_argument("--apply", action="store_true", help="Ejecuta cambios reales. Sin esto solo prepara/revisa.")
    parser.add_argument("--output-root", default=str(SCRIPT_DIR / "outputs"), help="Directorio raiz de salidas.")
    parser.add_argument("--run-id", default=dt.datetime.now().strftime("%Y%m%d_%H%M%S"), help="Identificador de corrida.")
    parser.add_argument("--date-json", default=str(DEFAULT_DATE_JSON), help="JSON opcional con fechas por nombre de archivo.")
    parser.add_argument("--date-excel", default=None, help="Excel opcional con fechas por nombre de archivo.")
    parser.add_argument("--overwrite-copy", action="store_true", help="Sobrescribe archivos existentes en datastore.")
    parser.add_argument("--skip-rasterio", action="store_true", help="Omite normalizacion rasterio.")
    parser.add_argument("--replace-originals", action="store_true", help="Rasterio reemplaza el TIFF original del datastore.")
    parser.add_argument("--create-backup-before-replace", action="store_true", help="Crea .bak antes de reemplazar original.")
    parser.add_argument("--build-pyramids-after-replace", action="store_true", help="Construye piramides/estadisticas despues de reemplazar.")
    parser.add_argument("--rasterio-env", default=DEFAULT_RASTERIO_ENV_PATH, help="Ambiente Python rasterio.")
    parser.add_argument("--aprx-output", default=None, help="Ruta del APRX resultado. Si no se indica queda en la corrida.")
    parser.add_argument("--log-name", default="geosupport_flujo_programado", help="Nombre base del archivo log.")
    parser.add_argument("--log-path", default=str(SCRIPT_DIR), help="Directorio base para Logs/.")
    parser.add_argument("--log-max-age-days", type=int, default=15, help="Dias maximos antes de rotar el log.")
    return parser.parse_args()


def main() -> int:
    global LOGGER
    args = parse_args()
    input_folder = Path(args.input_folder)
    output_root = Path(args.output_root)
    run_dir = output_root / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    aprx_output = Path(args.aprx_output) if args.aprx_output else run_dir / "aprx" / f"{Path(APRX_PATH).stem}_resultado_{args.run_id}.aprx"

    LOGGER = Logfile(
        args.log_name,
        log_path=args.log_path,
        max_age_days=args.log_max_age_days,
        rotate_mode="archive",
    )
    LOGGER.start_script(f"{args.log_name} run_id={args.run_id}")

    try:
        log(f"Run dir: {run_dir}")
        log(f"Modo apply: {args.apply}")
        log(f"Input folder: {input_folder}")
        log(f"Log file: {LOGGER.file_name}")

        stage1 = prepare_paths_stage(
            input_folder=input_folder,
            output_dir=run_dir / "01_preparar_paths_datastore",
            date_json=Path(args.date_json) if args.date_json else None,
            date_excel=Path(args.date_excel) if args.date_excel else None,
        )

        stage2 = load_mosaic_stage(
            ready_df=stage1["ready_df"],
            output_dir=run_dir / "02_carga_datastore_mosaico",
            apply_changes=args.apply,
            overwrite_copy=args.overwrite_copy,
        )

        update_footprints_stage(
            load_df=stage2["load_df"],
            results_df=stage2["results_df"],
            output_dir=run_dir / "03_actualizar_footprints_indice",
            apply_changes=args.apply,
        )

        run_rasterio_stage(
            load_results_csv=run_dir / "02_carga_datastore_mosaico" / "02_load_results.csv",
            load_input_csv=run_dir / "02_carga_datastore_mosaico" / "01_load_input_with_attributes.csv",
            output_dir=run_dir / "04_normalizar_imagenes_rasterio",
            args=args,
        )

        prepare_aprx_stage(
            load_df=stage2["load_df"],
            results_df=stage2["results_df"],
            output_dir=run_dir / "05_preparar_aprx_publicacion",
            aprx_output=aprx_output,
            apply_changes=args.apply,
        )

        summary = pd.DataFrame(
            [
                {"metric": "run_id", "value": args.run_id},
                {"metric": "apply", "value": args.apply},
                {"metric": "input_folder", "value": str(input_folder)},
                {"metric": "run_dir", "value": str(run_dir)},
                {"metric": "log_file", "value": str(LOGGER.file_name)},
                {"metric": "aprx_output", "value": str(aprx_output) if args.apply else "dry_run"},
                {"metric": "ready_for_datastore", "value": len(stage1["ready_df"])},
                {"metric": "review_required", "value": len(stage1["review_df"])},
                {"metric": "load_rows", "value": len(stage2["load_df"])},
            ]
        )
        write_df(summary, run_dir / "00_run_summary.csv")
        log_dataframe(summary)
        log("Flujo finalizado")
        log(f"Resumen: {run_dir / '00_run_summary.csv'}")
        if args.apply:
            log(f"APRX resultado: {aprx_output}")
        LOGGER.end("Fin flujo Geosupport")
        return 0
    except Exception as exc:
        import traceback

        log_error(str(exc))
        log_error(traceback.format_exc())
        raise
    finally:
        if LOGGER is not None:
            LOGGER.close(args.log_name)


if __name__ == "__main__":
    raise SystemExit(main())
