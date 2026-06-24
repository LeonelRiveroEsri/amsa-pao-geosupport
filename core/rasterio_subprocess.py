"""Bridge from ArcGIS Pro/arcpy to the dedicated rasterio environment."""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterable, Optional, Union

import pandas as pd


DEFAULT_RASTERIO_ENV_PATH = r"D:\Env\geo-raster-py311"


def _read_csv(path: Union[str, Path]) -> list[dict[str, str]]:
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as file_obj:
        return list(csv.DictReader(file_obj))


def _write_csv(path: Union[str, Path], rows: Iterable[dict], fieldnames: list[str]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def _merge_destination_paths(load_rows: list[dict], attrs_rows: list[dict]) -> list[dict]:
    destination_by_name = {
        row.get("Name"): row.get("destination_path") or row.get("Path_Destino") or ""
        for row in attrs_rows
        if row.get("Name")
    }
    for row in load_rows:
        if not row.get("destination_path"):
            row["destination_path"] = destination_by_name.get(row.get("Name"), "")
    return load_rows


def read_stage_2_rows(
    load_results_csv: Union[str, Path],
    load_input_attributes_csv: Union[str, Path],
    process_only_successful_loads: bool = True,
    limit_rows: Optional[int] = None,
) -> list[dict]:
    rows = _read_csv(load_results_csv)
    attrs_rows = _read_csv(load_input_attributes_csv)

    if rows:
        rows = _merge_destination_paths(rows, attrs_rows)
        if process_only_successful_loads:
            filtered_rows = []
            for row in rows:
                overall_status = str(row.get("overall_status", "")).lower()
                mosaic_status = str(row.get("mosaic_add_status", "")).lower()
                copy_status = str(row.get("copy_status", "")).lower()
                if (
                    overall_status == "ok"
                    or mosaic_status in {"added", "already_exists"}
                    or copy_status in {"copied", "already_exists"}
                ):
                    filtered_rows.append(row)
            rows = filtered_rows
    elif attrs_rows:
        rows = attrs_rows
    else:
        raise FileNotFoundError("No existe salida de etapa 2 para normalizar.")

    normalized_rows = []
    for row in rows:
        name = row.get("Name")
        destination_path = row.get("destination_path") or row.get("Path_Destino")
        if name and destination_path:
            row["Name"] = name
            row["destination_path"] = destination_path
            normalized_rows.append(row)

    if limit_rows is not None:
        normalized_rows = normalized_rows[: int(limit_rows)]

    return normalized_rows


def load_footprints_index(feature_class: str, name_field: str) -> dict[str, object]:
    import arcpy

    fields = {field.name.lower(): field.name for field in arcpy.ListFields(feature_class)}
    if name_field.lower() not in fields:
        raise ValueError(f"No existe el campo {name_field} en {feature_class}")

    resolved_name_field = fields[name_field.lower()]
    footprints = {}
    duplicates = []
    with arcpy.da.SearchCursor(feature_class, [resolved_name_field, "SHAPE@"]) as cursor:
        for name, geometry in cursor:
            if not name or geometry is None:
                continue
            key = str(name)
            if key in footprints:
                duplicates.append(key)
            footprints[key] = geometry

    if duplicates:
        print("Advertencia: nombres duplicados en footprints:", sorted(set(duplicates))[:20])

    return footprints


def _geometry_to_geojson_dict(geometry, target_spatial_reference=None) -> dict:
    geom = geometry
    if (
        target_spatial_reference
        and geometry.spatialReference
        and geometry.spatialReference.factoryCode != target_spatial_reference.factoryCode
    ):
        geom = geometry.projectAs(target_spatial_reference)

    esri_json = json.loads(geom.JSON)
    if "rings" in esri_json:
        return {"type": "Polygon", "coordinates": esri_json["rings"]}
    if "x" in esri_json and "y" in esri_json:
        return {"type": "Point", "coordinates": [esri_json["x"], esri_json["y"]]}

    raise ValueError("Tipo de geometria no soportado para exportar a GeoJSON.")


def _raster_spatial_reference(source_path: Union[str, Path]):
    import arcpy

    spatial_reference = getattr(arcpy.Describe(str(source_path)), "spatialReference", None)
    if spatial_reference and getattr(spatial_reference, "factoryCode", 0):
        return spatial_reference
    return None


def output_path_for_raster(source_path: Union[str, Path], name: str, normalized_dir: Union[str, Path]) -> Path:
    source_path = Path(source_path)
    safe_name = f"{name}.tif" if not str(name).lower().endswith(".tif") else str(name)
    return Path(normalized_dir) / source_path.parent.name / safe_name


def build_rasterio_manifest(
    rows: list[dict],
    footprints_index: dict[str, object],
    normalized_dir: Union[str, Path],
    manifest_csv: Union[str, Path],
    mask_black_background: bool = False,
    black_threshold: int = 5,
) -> Path:
    manifest_rows = []
    missing_footprint_rows = []

    for row in rows:
        name = str(row["Name"])
        source_path = Path(row["destination_path"])
        footprint_geometry = footprints_index.get(name)
        if footprint_geometry is None:
            missing_footprint_rows.append(
                {
                    "Name": name,
                    "source_path": str(source_path),
                    "status": "missing_footprint",
                    "error": f"No existe footprint para Name={name}",
                }
            )
            continue

        target_sr = _raster_spatial_reference(source_path)
        manifest_rows.append(
            {
                "Name": name,
                "source_path": str(source_path),
                "normalized_path": str(output_path_for_raster(source_path, name, normalized_dir)),
                "footprint_geojson": json.dumps(
                    _geometry_to_geojson_dict(footprint_geometry, target_sr),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "mask_black_background": str(bool(mask_black_background)),
                "black_threshold": int(black_threshold),
            }
        )

    if missing_footprint_rows:
        missing_csv = Path(manifest_csv).with_name("00_missing_footprints_for_rasterio.csv")
        _write_csv(
            missing_csv,
            missing_footprint_rows,
            ["Name", "source_path", "status", "error"],
        )
        print(f"Footprints faltantes omitidos: {len(missing_footprint_rows)}. Revision: {missing_csv}")

    if not manifest_rows:
        raise ValueError("No hay imagenes con footprint disponible para normalizar.")

    return _write_csv(
        manifest_csv,
        manifest_rows,
        ["Name", "source_path", "normalized_path", "footprint_geojson", "mask_black_background", "black_threshold"],
    )


def _conda_executable() -> str:
    conda = shutil.which("conda") or os.environ.get("CONDA_EXE")
    if not conda:
        raise FileNotFoundError("No se encontro conda en PATH ni en CONDA_EXE.")
    return conda


def _direct_env_python_command(env_path: Union[str, Path]) -> tuple[list[str], dict[str, str]]:
    env_path = Path(env_path)
    python_exe = env_path / "python.exe"
    if not python_exe.exists():
        raise FileNotFoundError(f"No se encontro python.exe en el ambiente rasterio: {python_exe}")

    env = os.environ.copy()
    env["CONDA_PREFIX"] = str(env_path)
    env["CONDA_DEFAULT_ENV"] = env_path.name
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)

    gdal_data = env_path / "Library" / "share" / "gdal"
    proj_lib = env_path / "Library" / "share" / "proj"
    if gdal_data.exists():
        env["GDAL_DATA"] = str(gdal_data)
    if proj_lib.exists():
        env["PROJ_LIB"] = str(proj_lib)

    path_parts = [
        str(env_path),
        str(env_path / "Library" / "mingw-w64" / "bin"),
        str(env_path / "Library" / "usr" / "bin"),
        str(env_path / "Library" / "bin"),
        str(env_path / "Scripts"),
        r"C:\Windows\System32",
        r"C:\Windows",
        r"C:\Windows\System32\Wbem",
    ]
    env["PATH"] = os.pathsep.join(part for part in path_parts if part)
    return [str(python_exe)], env


def run_rasterio_worker(
    manifest_csv: Union[str, Path],
    output_dir: Union[str, Path],
    env_name: Optional[str] = None,
    env_path: Optional[Union[str, Path]] = DEFAULT_RASTERIO_ENV_PATH,
    replace_originals: bool = False,
    create_backup_before_replace: bool = False,
    backup_suffix: str = ".bak_original_before_rasterio",
) -> subprocess.CompletedProcess:
    output_dir = Path(output_dir)
    worker_script = Path(__file__).with_name("rasterio_normalize_worker.py")
    if env_path:
        runner, subprocess_env = _direct_env_python_command(env_path)
    elif env_name:
        runner = [_conda_executable(), "run", "-n", env_name, "python"]
        subprocess_env = None
    else:
        raise ValueError("Debe indicar env_path o env_name para ejecutar rasterio.")

    command = [
        *runner,
        str(worker_script),
        "--manifest",
        str(manifest_csv),
        "--summary-csv",
        str(output_dir / "00_summary.csv"),
        "--results-csv",
        str(output_dir / "01_normalizacion_rasterio_resultados.csv"),
        "--errors-csv",
        str(output_dir / "02_errors_review.csv"),
        "--backup-suffix",
        backup_suffix,
    ]

    if replace_originals:
        command.append("--replace-originals")
    if create_backup_before_replace:
        command.append("--create-backup-before-replace")

    return subprocess.run(command, check=False, text=True, capture_output=True, env=subprocess_env)


def build_pyramids_for_replaced_results(results_csv: Union[str, Path]) -> None:
    import arcpy

    for row in _read_csv(results_csv):
        if row.get("status") == "normalized_and_replaced" and row.get("source_path"):
            arcpy.management.BuildPyramidsandStatistics(row["source_path"])


def set_arcgis_nodata_for_replaced_results(results_csv: Union[str, Path]) -> None:
    import arcpy

    for row in _read_csv(results_csv):
        if row.get("status") != "normalized_and_replaced" or not row.get("source_path"):
            continue
        source_path = row["source_path"]
        try:
            band_count = int(arcpy.management.GetRasterProperties(source_path, "BANDCOUNT").getOutput(0))
        except Exception:
            band_count = 3
        nodata_values = ";".join(f"{band} 0" for band in range(1, min(band_count, 3) + 1))
        if nodata_values:
            arcpy.management.SetRasterProperties(source_path, nodata=nodata_values)


def run_stage_04_rasterio_subprocess(
    load_results_csv: Union[str, Path],
    load_input_attributes_csv: Union[str, Path],
    footprints_feature_class: str,
    footprint_name_field: str,
    output_dir: Union[str, Path],
    env_name: Optional[str] = None,
    env_path: Optional[Union[str, Path]] = DEFAULT_RASTERIO_ENV_PATH,
    process_only_successful_loads: bool = True,
    limit_rows: Optional[int] = None,
    replace_originals: bool = False,
    create_backup_before_replace: bool = False,
    build_pyramids_after_replace: bool = False,
    backup_suffix: str = ".bak_original_before_rasterio",
    mask_black_background: bool = False,
    black_threshold: int = 5,
) -> subprocess.CompletedProcess:
    output_dir = Path(output_dir)
    normalized_dir = output_dir / "normalized_tif"
    run_timestamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    manifest_csv = output_dir / f"rasterio_manifest_{run_timestamp}.csv"

    rows = read_stage_2_rows(
        load_results_csv,
        load_input_attributes_csv,
        process_only_successful_loads=process_only_successful_loads,
        limit_rows=limit_rows,
    )
    footprints_index = load_footprints_index(footprints_feature_class, footprint_name_field)
    build_rasterio_manifest(
        rows,
        footprints_index,
        normalized_dir,
        manifest_csv,
        mask_black_background=mask_black_background,
        black_threshold=black_threshold,
    )

    completed = run_rasterio_worker(
        manifest_csv=manifest_csv,
        output_dir=output_dir,
        env_name=env_name,
        env_path=env_path,
        replace_originals=replace_originals,
        create_backup_before_replace=create_backup_before_replace,
        backup_suffix=backup_suffix,
    )

    (output_dir / "rasterio_worker_stdout.log").write_text(completed.stdout or "", encoding="utf-8")
    (output_dir / "rasterio_worker_stderr.log").write_text(completed.stderr or "", encoding="utf-8")

    print(completed.stdout)
    if completed.stderr:
        print(completed.stderr)

    if completed.returncode != 0:
        raise RuntimeError(
            "El subproceso rasterio termino con codigo {}.\nSTDOUT:\n{}\nSTDERR:\n{}".format(
                completed.returncode,
                completed.stdout,
                completed.stderr,
            )
        )

    results_csv = output_dir / "01_normalizacion_rasterio_resultados.csv"
    if replace_originals:
        set_arcgis_nodata_for_replaced_results(results_csv)
    if build_pyramids_after_replace:
        build_pyramids_for_replaced_results(results_csv)

    return completed
