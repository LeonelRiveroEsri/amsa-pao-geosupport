"""Rasterio-only worker for image normalization.

Run this file from the dedicated rasterio conda environment. It intentionally
does not import arcpy or pandas.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Union


def _configure_conda_dll_search_path() -> None:
    env_prefix = Path(sys.prefix)
    dll_dirs = [
        env_prefix / "Library" / "bin",
        env_prefix / "DLLs",
        env_prefix,
    ]

    for dll_dir in dll_dirs:
        if dll_dir.exists() and hasattr(os, "add_dll_directory"):
            os.add_dll_directory(str(dll_dir))


_configure_conda_dll_search_path()


def _increase_csv_field_size_limit() -> None:
    max_int = sys.maxsize
    while True:
        try:
            csv.field_size_limit(max_int)
            return
        except OverflowError:
            max_int = int(max_int / 10)


_increase_csv_field_size_limit()


def _read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as file_obj:
        return list(csv.DictReader(file_obj))


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def normalize_with_rasterio(source_path: Union[str, Path], footprint_geojson: dict, output_path: Union[str, Path]) -> Path:
    import numpy as np
    import rasterio
    from rasterio.mask import mask

    source_path = Path(source_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(source_path) as src:
        masked_data, out_transform = mask(src, [footprint_geojson], crop=True, filled=False)
        profile = src.profile.copy()
        profile.update(
            driver="GTiff",
            height=masked_data.shape[1],
            width=masked_data.shape[2],
            transform=out_transform,
            tiled=True,
            compress="deflate",
            photometric="RGB",
        )

        if src.count >= 3:
            rgb = masked_data[:3].filled(0)
        elif src.count == 1:
            values = masked_data[0].filled(0)
            colormap = None
            try:
                colormap = src.colormap(1)
            except Exception:
                colormap = None

            if colormap:
                rgb = np.zeros((3, values.shape[0], values.shape[1]), dtype="uint8")
                for pixel_value, color in colormap.items():
                    color_mask = values == pixel_value
                    if color_mask.any():
                        rgb[0][color_mask] = color[0]
                        rgb[1][color_mask] = color[1]
                        rgb[2][color_mask] = color[2]
            else:
                rgb = np.repeat(values[np.newaxis, :, :], 3, axis=0)
        else:
            raise ValueError(f"Raster con cantidad de bandas no soportada: {src.count}")

        alpha = (~masked_data.mask.all(axis=0)).astype("uint8") * 255
        profile.update(count=4, dtype=rgb.dtype, nodata=None)

        with rasterio.open(output_path, "w", **profile) as dst:
            dst.write(rgb.astype(profile["dtype"], copy=False))
            dst.write(alpha, 4)
            dst.colorinterp = (
                rasterio.enums.ColorInterp.red,
                rasterio.enums.ColorInterp.green,
                rasterio.enums.ColorInterp.blue,
                rasterio.enums.ColorInterp.alpha,
            )

    return output_path


def replace_original(
    source_path: Union[str, Path],
    normalized_path: Union[str, Path],
    create_backup: bool,
    backup_suffix: str,
) -> Optional[Path]:
    source_path = Path(source_path)
    normalized_path = Path(normalized_path)
    backup_path = source_path.with_suffix(source_path.suffix + backup_suffix)

    if create_backup and not backup_path.exists():
        shutil.copy2(source_path, backup_path)

    shutil.copy2(normalized_path, source_path)
    return backup_path if create_backup else None


def validate_rasterio_runtime() -> None:
    import rasterio  # noqa: F401


def run(args: argparse.Namespace) -> int:
    validate_rasterio_runtime()
    rows = _read_manifest(args.manifest)
    results = []

    for row in rows:
        name = row.get("Name") or row.get("name") or ""
        source_path = Path(row["source_path"])
        normalized_path = Path(row["normalized_path"])
        item = {
            "Name": name,
            "source_path": str(source_path),
            "normalized_path": str(normalized_path),
            "replace_original": args.replace_originals,
            "backup_path": "",
            "status": "pending",
            "error": "",
        }

        try:
            if not source_path.exists():
                raise FileNotFoundError(f"No existe raster origen: {source_path}")

            footprint_geojson = json.loads(row["footprint_geojson"])
            normalize_with_rasterio(source_path, footprint_geojson, normalized_path)

            if args.replace_originals:
                backup_path = replace_original(
                    source_path,
                    normalized_path,
                    create_backup=args.create_backup_before_replace,
                    backup_suffix=args.backup_suffix,
                )
                item["backup_path"] = str(backup_path or "")
                item["status"] = "normalized_and_replaced"
            else:
                item["status"] = "normalized_for_review"

            print(f"OK {name}: {item['status']}")
        except Exception as exc:
            item["status"] = "error"
            item["error"] = str(exc)
            print(f"ERROR {name}: {exc}")

        results.append(item)

    fieldnames = [
        "Name",
        "source_path",
        "normalized_path",
        "replace_original",
        "backup_path",
        "status",
        "error",
    ]
    _write_csv(args.results_csv, results, fieldnames)
    _write_csv(args.errors_csv, [row for row in results if row["status"] == "error"], fieldnames)

    counts: dict[str, int] = {}
    for row in results:
        counts[row["status"]] = counts.get(row["status"], 0) + 1

    summary_rows = [
        {"metric": "run_timestamp", "value": datetime.now().strftime("%Y%m%d_%H%M%S")},
        {"metric": "manifest_csv", "value": str(args.manifest)},
        {"metric": "rows_to_process", "value": len(rows)},
        {"metric": "replace_originals", "value": args.replace_originals},
        {"metric": "create_backup_before_replace", "value": args.create_backup_before_replace},
    ]
    summary_rows.extend({"metric": f"status_{status}", "value": count} for status, count in sorted(counts.items()))
    _write_csv(args.summary_csv, summary_rows, ["metric", "value"])

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize rasters with rasterio from a CSV manifest.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--summary-csv", type=Path, required=True)
    parser.add_argument("--results-csv", type=Path, required=True)
    parser.add_argument("--errors-csv", type=Path, required=True)
    parser.add_argument("--replace-originals", action="store_true")
    parser.add_argument("--create-backup-before-replace", action="store_true")
    parser.add_argument("--backup-suffix", default=".bak_original_before_rasterio")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
