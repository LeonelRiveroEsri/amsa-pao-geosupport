from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import arcpy
except ImportError as exc:
    raise RuntimeError("Este script debe ejecutarse con el Python de ArcGIS Pro.") from exc

from core.rasterio_subprocess import (
    DEFAULT_RASTERIO_ENV_PATH,
    _geometry_to_geojson_dict,
    _raster_spatial_reference,
    run_rasterio_worker,
)


DEFAULT_FOOTPRINTS_FC = (
    r"\\amssclgis08.ams.gmams.cl\CL_MLP_PAO\02_FGDB\CL_MLP_PAO_v1.gdb"
    r"\CL_MLP_PAO_06_COMPLEMENTOS\CL_MLP_PAO_Indice_Vuelos_PAO_IMGS_PO"
)


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def infer_name_from_path(raster_path: Path) -> str:
    return raster_path.stem


def quote_sql(value: str) -> str:
    return value.replace("'", "''")


def get_footprint_geometry(feature_class: str, name_field: str, name: str):
    fields = {field.name.lower(): field.name for field in arcpy.ListFields(feature_class)}
    resolved_name_field = fields.get(name_field.lower())
    if not resolved_name_field:
        raise ValueError(f"No existe el campo {name_field} en {feature_class}")

    where = f"{resolved_name_field} = '{quote_sql(name)}'"
    matches = []
    with arcpy.da.SearchCursor(feature_class, [resolved_name_field, "SHAPE@"], where_clause=where) as cursor:
        for match_name, geometry in cursor:
            if geometry is not None:
                matches.append((match_name, geometry))

    if not matches:
        raise ValueError(f"No se encontro footprint para {resolved_name_field}={name}")
    if len(matches) > 1:
        print(f"Advertencia: se encontraron {len(matches)} footprints para {name}. Se usara el primero.")

    return matches[0][1]


def backup_original(source_path: Path, backup_root: Path, run_timestamp: str) -> Path:
    backup_dir = backup_root / run_timestamp
    backup_dir.mkdir(parents=True, exist_ok=True)

    backup_path = backup_dir / source_path.name
    if backup_path.exists():
        backup_path = backup_dir / f"{source_path.stem}_{pd.Timestamp.now().strftime('%H%M%S')}{source_path.suffix}"

    shutil.copy2(source_path, backup_path)

    metadata = {
        "created_at": pd.Timestamp.now().isoformat(),
        "original_path": str(source_path),
        "backup_path": str(backup_path),
    }
    (backup_path.with_suffix(backup_path.suffix + ".json")).write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return backup_path


def find_latest_backup(source_path: Path, backup_root: Path) -> Path | None:
    if not backup_root.exists():
        return None

    candidates = []
    for candidate in backup_root.rglob(source_path.name):
        if candidate.is_file():
            candidates.append(candidate)

    if not candidates:
        return None

    return max(candidates, key=lambda path: path.stat().st_mtime)


def restore_latest_backup(source_path: Path, backup_root: Path) -> Path:
    latest_backup = find_latest_backup(source_path, backup_root)
    if latest_backup is None:
        raise FileNotFoundError(f"No existe backup previo para restaurar: {source_path.name} en {backup_root}")

    shutil.copy2(latest_backup, source_path)
    return latest_backup


def restore_latest_backup_if_exists(source_path: Path, backup_root: Path) -> Path | None:
    latest_backup = find_latest_backup(source_path, backup_root)
    if latest_backup is None:
        return None

    shutil.copy2(latest_backup, source_path)
    return latest_backup


def build_manifest(
    name: str,
    source_path: Path,
    footprint_geometry,
    output_dir: Path,
    mask_black_background: bool = False,
    black_threshold: int = 5,
) -> Path:
    target_sr = _raster_spatial_reference(source_path)
    footprint_geojson = _geometry_to_geojson_dict(footprint_geometry, target_sr)
    normalized_path = output_dir / "normalized_tif" / source_path.name
    manifest_csv = output_dir / "01_manifest_single_raster.csv"

    write_csv(
        manifest_csv,
        [
            {
                "Name": name,
                "source_path": str(source_path),
                "normalized_path": str(normalized_path),
                "footprint_geojson": json.dumps(footprint_geojson, ensure_ascii=False, separators=(",", ":")),
                "mask_black_background": str(bool(mask_black_background)),
                "black_threshold": int(black_threshold),
            }
        ],
        ["Name", "source_path", "normalized_path", "footprint_geojson", "mask_black_background", "black_threshold"],
    )
    return manifest_csv


def set_arcgis_rgb_nodata(raster_path: Path) -> None:
    """Define 0 como NoData en bandas RGB para que ArcGIS no dibuje el fondo negro."""
    try:
        band_count = int(arcpy.management.GetRasterProperties(str(raster_path), "BANDCOUNT").getOutput(0))
    except Exception:
        band_count = 3

    nodata_values = ";".join(f"{band} 0" for band in range(1, min(band_count, 3) + 1))
    if nodata_values:
        arcpy.management.SetRasterProperties(str(raster_path), nodata=nodata_values)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normaliza un raster puntual con rasterio, respalda el original en el proyecto y sobrescribe el TIFF origen."
    )
    parser.add_argument("raster_path", help="Path completo del TIFF a normalizar y sobrescribir.")
    parser.add_argument("--name", default=None, help="Valor del campo Name en footprints. Si se omite usa el nombre del archivo sin extension.")
    parser.add_argument("--footprints-fc", default=DEFAULT_FOOTPRINTS_FC, help="Feature class con footprints.")
    parser.add_argument("--footprint-name-field", default="Name", help="Campo de busqueda en footprints.")
    parser.add_argument("--rasterio-env", default=DEFAULT_RASTERIO_ENV_PATH, help="Ambiente Python con rasterio.")
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "ejecucion_programada" / "outputs" / "normalizar_raster_por_path"),
        help="Directorio de salidas de revision.",
    )
    parser.add_argument(
        "--backup-root",
        default=str(PROJECT_ROOT / "Bkg_rasterio_normalizacion"),
        help="Directorio del proyecto donde se guarda el backup del TIFF original.",
    )
    parser.add_argument(
        "--restore-latest-backup-first",
        action="store_true",
        help="Restaura el ultimo backup disponible del raster antes de volver a normalizar.",
    )
    parser.add_argument(
        "--restore-latest-backup-if-exists",
        action="store_true",
        help="Restaura el ultimo backup si existe; si no existe continua normalizando el raster actual.",
    )
    parser.add_argument(
        "--mask-black-background",
        action="store_true",
        help="Enmascara pixeles RGB casi negros del raster original, util para collars negros internos.",
    )
    parser.add_argument(
        "--black-threshold",
        type=int,
        default=5,
        help="Umbral RGB para detectar fondo negro cuando --mask-black-background esta activo.",
    )
    parser.add_argument("--apply", action="store_true", help="Ejecuta el reemplazo. Sin esto solo prepara manifest y backup no se crea.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_path = Path(args.raster_path)
    name = args.name or infer_name_from_path(source_path)
    run_timestamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir) / run_timestamp
    backup_root = Path(args.backup_root)

    if not source_path.exists():
        raise FileNotFoundError(f"No existe el raster: {source_path}")

    print(f"Raster: {source_path}")
    print(f"Name footprint: {name}")
    print(f"Footprints FC: {args.footprints_fc}")
    print(f"Salida: {output_dir}")
    print(f"Backup root: {backup_root}")
    print(f"Apply: {args.apply}")
    print(f"Restaurar backup primero: {args.restore_latest_backup_first}")
    print(f"Restaurar backup si existe: {args.restore_latest_backup_if_exists}")
    print(f"Enmascarar fondo negro: {args.mask_black_background}")
    print(f"Umbral negro: {args.black_threshold}")

    backup_path = ""
    restored_backup_path = ""
    if args.apply:
        if args.restore_latest_backup_first:
            restored_backup_path = str(restore_latest_backup(source_path, backup_root))
            print(f"Restaurado desde backup: {restored_backup_path}")
        elif args.restore_latest_backup_if_exists:
            optional_backup = restore_latest_backup_if_exists(source_path, backup_root)
            if optional_backup:
                restored_backup_path = str(optional_backup)
                print(f"Restaurado desde backup: {restored_backup_path}")
            else:
                print("No hay backup previo. Se normaliza el raster actual.")

        footprint_geometry = get_footprint_geometry(args.footprints_fc, args.footprint_name_field, name)
        manifest_csv = build_manifest(
            name,
            source_path,
            footprint_geometry,
            output_dir,
            mask_black_background=args.mask_black_background,
            black_threshold=args.black_threshold,
        )
        backup_path = str(backup_original(source_path, backup_root, run_timestamp))
        completed = run_rasterio_worker(
            manifest_csv=manifest_csv,
            output_dir=output_dir,
            env_path=args.rasterio_env,
            replace_originals=True,
            create_backup_before_replace=False,
        )
        (output_dir / "rasterio_worker_stdout.log").write_text(completed.stdout or "", encoding="utf-8")
        (output_dir / "rasterio_worker_stderr.log").write_text(completed.stderr or "", encoding="utf-8")
        print(completed.stdout)
        if completed.stderr:
            print(completed.stderr)
        if completed.returncode != 0:
            raise RuntimeError(f"Rasterio termino con codigo {completed.returncode}. Ver logs en {output_dir}")
        set_arcgis_rgb_nodata(source_path)
        arcpy.management.BuildPyramidsandStatistics(str(source_path))
    else:
        footprint_geometry = get_footprint_geometry(args.footprints_fc, args.footprint_name_field, name)
        manifest_csv = build_manifest(
            name,
            source_path,
            footprint_geometry,
            output_dir,
            mask_black_background=args.mask_black_background,
            black_threshold=args.black_threshold,
        )
        print("Dry-run: no se creo backup ni se reemplazo el raster. Use --apply para ejecutar.")

    summary_csv = output_dir / "00_summary.csv"
    write_csv(
        summary_csv,
        [
            {"metric": "run_timestamp", "value": run_timestamp},
            {"metric": "raster_path", "value": str(source_path)},
            {"metric": "Name", "value": name},
            {"metric": "manifest_csv", "value": str(manifest_csv)},
            {"metric": "restored_backup_path", "value": restored_backup_path},
            {"metric": "backup_path", "value": backup_path},
            {"metric": "mask_black_background", "value": args.mask_black_background},
            {"metric": "black_threshold", "value": args.black_threshold},
            {"metric": "apply", "value": args.apply},
        ],
        ["metric", "value"],
    )
    print(f"Resumen: {summary_csv}")
    if backup_path:
        print(f"Backup original: {backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
