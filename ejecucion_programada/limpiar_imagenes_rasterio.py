from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent

RASTER_EXTENSIONS = {
    ".tif",
    ".tiff",
    ".ovr",
    ".aux",
    ".xml",
}

SAFE_PATH_TOKENS = {
    "normalizacion",
    "rasterio",
    "rgb_clean",
    "normalized_tif",
}

SAFE_DIR_NAMES = {
    "normalized_tif",
    "normalizacion_footprint",
    "normalizacion_footprintv2",
    "normalizacion_footprint_gdalv6",
    "rgb_clean_from_audit",
    "etapa_04_normalizar_imagenes_rasterio",
}


def is_inside_project(path: Path, project_root: Path) -> bool:
    try:
        path.resolve().relative_to(project_root.resolve())
        return True
    except ValueError:
        return False


def is_raster_sidecar(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(".aux.xml") or name.endswith(".tif.ovr") or name.endswith(".tiff.ovr")


def is_candidate_file(path: Path, project_root: Path) -> bool:
    if not path.is_file() or not is_inside_project(path, project_root):
        return False

    lower_parts = {part.lower() for part in path.parts}
    lower_text = str(path).lower()
    suffix = path.suffix.lower()

    has_safe_context = bool(lower_parts.intersection(SAFE_DIR_NAMES)) or any(token in lower_text for token in SAFE_PATH_TOKENS)
    has_raster_extension = suffix in RASTER_EXTENSIONS or is_raster_sidecar(path)
    return has_safe_context and has_raster_extension


def find_rasterio_outputs(project_root: Path) -> list[Path]:
    candidates = []
    search_roots = [
        project_root / "outputs",
        project_root / "flujo_geosupport_etapas" / "outputs",
        project_root / "ejecucion_programada" / "outputs",
    ]

    for search_root in search_roots:
        if not search_root.exists():
            continue
        for path in search_root.rglob("*"):
            if is_candidate_file(path, project_root):
                candidates.append(path)

    return sorted(set(candidates))


def remove_empty_dirs(project_root: Path, roots: list[Path]) -> int:
    removed = 0
    for root in roots:
        if not root.exists():
            continue
        for directory in sorted([p for p in root.rglob("*") if p.is_dir()], key=lambda p: len(p.parts), reverse=True):
            if not is_inside_project(directory, project_root):
                continue
            try:
                directory.rmdir()
                removed += 1
            except OSError:
                pass
    return removed


def write_report(rows: list[dict], report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["path", "size_mb", "action", "error"]
    with report_path.open("w", newline="", encoding="utf-8-sig") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Limpia imagenes temporales/generadas por rasterio dentro del proyecto Geosupport."
    )
    parser.add_argument("--project-root", default=str(PROJECT_ROOT), help="Raiz del proyecto. Por defecto se detecta desde este script.")
    parser.add_argument("--apply", action="store_true", help="Borra archivos. Sin esto solo genera reporte dry-run.")
    parser.add_argument("--remove-empty-dirs", action="store_true", help="Elimina carpetas vacias despues de borrar.")
    parser.add_argument(
        "--report",
        default=None,
        help="CSV de reporte. Por defecto queda en ejecucion_programada/outputs/limpieza_rasterio_<timestamp>.csv",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = Path(args.project_root).resolve()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = (
        Path(args.report)
        if args.report
        else project_root / "ejecucion_programada" / "outputs" / f"limpieza_rasterio_{timestamp}.csv"
    )

    candidates = find_rasterio_outputs(project_root)
    rows = []
    total_bytes = 0

    for path in candidates:
        size_bytes = path.stat().st_size
        total_bytes += size_bytes
        row = {
            "path": str(path),
            "size_mb": round(size_bytes / (1024 * 1024), 3),
            "action": "dry_run",
            "error": "",
        }

        if args.apply:
            try:
                path.unlink()
                row["action"] = "deleted"
            except Exception as exc:
                row["action"] = "error"
                row["error"] = str(exc)

        rows.append(row)

    removed_dirs = 0
    if args.apply and args.remove_empty_dirs:
        removed_dirs = remove_empty_dirs(
            project_root,
            [
                project_root / "outputs",
                project_root / "flujo_geosupport_etapas" / "outputs",
                project_root / "ejecucion_programada" / "outputs",
            ],
        )

    write_report(rows, report_path)

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"Modo: {mode}")
    print(f"Proyecto: {project_root}")
    print(f"Archivos candidatos: {len(candidates)}")
    print(f"Tamano total candidato MB: {round(total_bytes / (1024 * 1024), 3)}")
    print(f"Carpetas vacias eliminadas: {removed_dirs}")
    print(f"Reporte: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
