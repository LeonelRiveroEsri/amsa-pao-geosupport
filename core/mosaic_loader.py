from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


MAXPS_VALUE = 10000
LOWPS_VALUE = 0.15

FP_METHOD = "RADIOMETRY"
FP_MIN_REGION_SIZE = 15
FP_MAX_REGION_SIZE = 245
FP_SMOOTHING = 10000
FP_SIMPLIFY = 5
FP_MAINTAIN_EDGES = "NO_MAINTAIN_EDGES"
FP_DERIVED = "SKIP_DERIVED_IMAGES"
FP_UPDATE_BOUNDARY = "UPDATE_BOUNDARY"
FP_MAX_VERTICES = 2000
FP_MAX_SLIVER_SIZE = 100
FP_MIN_THINNESS_RATIO = "NONE"
FP_MAX_THINNESS_RATIO = None
FP_SHRINK_DISTANCE = 20
FP_SIMPLIFY_TOL = 0.05


def _import_arcpy():
    try:
        import arcpy  # type: ignore
    except ImportError as error:
        raise RuntimeError("arcpy es requerido. Ejecuta esto con el Python de ArcGIS Pro.") from error
    return arcpy


def quote_sql_text(value: Any) -> str:
    return str(value).replace("'", "''")


def name_where_clause(name: str) -> str:
    return f"Name = '{quote_sql_text(name)}'"


def parse_date(value):
    if value is None or pd.isna(value) or value == "":
        return None
    if isinstance(value, datetime):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d")


def load_ready_and_attributes(ready_csv: str | Path, attributes_csv: str | Path) -> pd.DataFrame:
    ready_df = pd.read_csv(ready_csv)
    attributes_df = pd.read_csv(attributes_csv)

    merged_df = ready_df.merge(
        attributes_df,
        left_on=["file_name", "expected_file_name"],
        right_on=["file_name", "Raster"],
        how="left",
        suffixes=("", "_attr"),
    )

    missing_attributes = merged_df["URL"].isna() if "URL" in merged_df.columns else pd.Series(True, index=merged_df.index)
    if missing_attributes.any():
        missing_files = merged_df.loc[missing_attributes, "file_name"].tolist()
        raise ValueError(f"Faltan atributos para {len(missing_files)} imagenes: {missing_files[:5]}")

    return merged_df


def copy_to_datastore(row: pd.Series, overwrite: bool = False, dry_run: bool = True) -> dict:
    source_path = Path(row["path"])
    destination_path = Path(row["destination_path"])

    result = {
        "source_path": str(source_path),
        "destination_path": str(destination_path),
        "copy_status": None,
        "copy_error": None,
    }

    if not source_path.exists():
        result["copy_status"] = "source_missing"
        return result

    if destination_path.exists() and not overwrite:
        result["copy_status"] = "already_exists"
        return result

    if dry_run:
        result["copy_status"] = "dry_run"
        return result

    try:
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)
        result["copy_status"] = "copied"
    except Exception as error:
        result["copy_status"] = "error"
        result["copy_error"] = str(error)

    return result


def mosaic_name_exists(mosaic_dataset: str, name: str) -> bool:
    arcpy = _import_arcpy()
    where = name_where_clause(name)
    with arcpy.da.SearchCursor(mosaic_dataset, ["Name"], where_clause=where) as cursor:
        return any(True for _ in cursor)


def add_raster_to_mosaic(mosaic_dataset: str, raster_path: str, dry_run: bool = True) -> dict:
    raster_path = str(raster_path)

    result = {
        "mosaic_add_status": None,
        "mosaic_add_error": None,
    }

    if dry_run:
        result["mosaic_add_status"] = "dry_run"
        return result

    arcpy = _import_arcpy()

    try:
        arcpy.management.AddRastersToMosaicDataset(
            in_mosaic_dataset=mosaic_dataset,
            raster_type="Raster Dataset",
            input_path=raster_path,
            update_cellsize_ranges="NO_CELL_SIZES",
            update_boundary="NO_BOUNDARY",
            update_overviews="NO_OVERVIEWS",
            maximum_pyramid_levels=None,
            maximum_cell_size=0,
            minimum_dimension=1500,
            spatial_reference=None,
            filter="",
            sub_folder="NO_SUBFOLDERS",
            duplicate_items_action="ALLOW_DUPLICATES",
            build_pyramids="BUILD_PYRAMIDS",
            calculate_statistics="CALCULATE_STATISTICS",
            build_thumbnails="NO_THUMBNAILS",
            operation_description="",
            force_spatial_reference="NO_FORCE_SPATIAL_REFERENCE",
            estimate_statistics="NO_STATISTICS",
            aux_inputs=None,
            enable_pixel_cache="NO_PIXEL_CACHE",
            cache_location=rf"{Path.home()}\AppData\Local\ESRI\rasterproxies",
        )
        result["mosaic_add_status"] = "added"
    except Exception as error:
        result["mosaic_add_status"] = "error"
        result["mosaic_add_error"] = str(error)

    return result


def build_footprints(mosaic_dataset: str, name: str, dry_run: bool = True) -> dict:
    where = name_where_clause(name)
    result = {
        "footprint_status": None,
        "footprint_error": None,
    }

    if dry_run:
        result["footprint_status"] = "dry_run"
        return result

    arcpy = _import_arcpy()

    try:
        arcpy.management.BuildFootprints(
            mosaic_dataset,
            where,
            FP_METHOD,
            FP_MIN_REGION_SIZE,
            FP_MAX_REGION_SIZE,
            FP_SMOOTHING,
            FP_SIMPLIFY,
            FP_MAINTAIN_EDGES,
            FP_DERIVED,
            FP_UPDATE_BOUNDARY,
            FP_MAX_VERTICES,
            FP_MAX_SLIVER_SIZE,
            FP_MIN_THINNESS_RATIO,
            FP_MAX_THINNESS_RATIO,
            FP_SHRINK_DISTANCE,
            FP_SIMPLIFY_TOL,
        )
        result["footprint_status"] = "built"
    except Exception as error:
        result["footprint_status"] = "error"
        result["footprint_error"] = str(error)

    return result


def update_mosaic_attributes(
    mosaic_dataset: str,
    row: pd.Series,
    maxps_value: float = MAXPS_VALUE,
    lowps_value: float = LOWPS_VALUE,
    dry_run: bool = True,
) -> dict:
    name = row["Name"]
    where = name_where_clause(name)

    requested_values = {
        "MaxPS": float(maxps_value),
        "LowPS": float(lowps_value),
        "Sector": row.get("Sector"),
        "FechaAdqui": parse_date(row.get("Fecha_Adqui")),
        "Fecha_Adqui": parse_date(row.get("Fecha_Adqui")),
        "URL": row.get("URL"),
        "Proyecto": row.get("Proyecto"),
        "Sensor": row.get("Sensor"),
        "FechaCarga": parse_date(row.get("Fecha_Publ")),
        "Fecha_Publ": parse_date(row.get("Fecha_Publ")),
    }

    result = {
        "attribute_status": None,
        "attribute_rows_updated": 0,
        "attribute_missing_fields": None,
        "attribute_error": None,
    }

    if dry_run:
        result["attribute_status"] = "dry_run"
        return result

    arcpy = _import_arcpy()
    existing_fields = {field.name for field in arcpy.ListFields(mosaic_dataset)}
    update_fields = [field for field in requested_values if field in existing_fields]
    missing_fields = [field for field in requested_values if field not in existing_fields]
    result["attribute_missing_fields"] = "|".join(missing_fields) if missing_fields else None

    try:
        updated = 0
        with arcpy.da.UpdateCursor(mosaic_dataset, update_fields, where_clause=where) as cursor:
            for cursor_row in cursor:
                for index, field in enumerate(update_fields):
                    cursor_row[index] = requested_values[field]
                cursor.updateRow(cursor_row)
                updated += 1

        result["attribute_rows_updated"] = updated
        result["attribute_status"] = "updated" if updated else "not_found"
    except Exception as error:
        result["attribute_status"] = "error"
        result["attribute_error"] = str(error)

    return result


def process_mosaic_load_row(
    row: pd.Series,
    mosaic_dataset: str,
    overwrite_copy: bool = False,
    skip_existing_mosaic_name: bool = True,
    maxps_value: float = MAXPS_VALUE,
    lowps_value: float = LOWPS_VALUE,
    dry_run: bool = True,
) -> dict:
    name = row["Name"]
    destination_path = row["destination_path"]

    result = {
        "file_name": row.get("file_name"),
        "Name": name,
        "destination_path": destination_path,
        "overall_status": None,
    }

    copy_result = copy_to_datastore(row, overwrite=overwrite_copy, dry_run=dry_run)
    result.update(copy_result)
    if copy_result["copy_status"] in ("source_missing", "error"):
        result["overall_status"] = "copy_failed"
        return result

    if not dry_run and skip_existing_mosaic_name and mosaic_name_exists(mosaic_dataset, name):
        result["mosaic_add_status"] = "already_exists"
    else:
        result.update(add_raster_to_mosaic(mosaic_dataset, destination_path, dry_run=dry_run))

    if result.get("mosaic_add_status") == "error":
        result["overall_status"] = "mosaic_add_failed"
        return result

    result.update(build_footprints(mosaic_dataset, name, dry_run=dry_run))
    if result.get("footprint_status") == "error":
        result["overall_status"] = "footprint_failed"
        return result

    result.update(
        update_mosaic_attributes(
            mosaic_dataset,
            row,
            maxps_value=maxps_value,
            lowps_value=lowps_value,
            dry_run=dry_run,
        )
    )
    if result.get("attribute_status") == "error":
        result["overall_status"] = "attribute_update_failed"
        return result

    result["overall_status"] = "dry_run" if dry_run else "ok"
    return result
