"""Update footprint URL fields from the stage 02 attribute CSV.

Run with the ArcGIS Pro Python environment because it requires arcpy.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path
from typing import Optional, Union


def read_url_lookup(attributes_csv: Union[str, Path]) -> dict[str, str]:
    attributes_csv = Path(attributes_csv)
    with attributes_csv.open("r", newline="", encoding="utf-8-sig") as file_obj:
        rows = csv.DictReader(file_obj)
        if "Name" not in (rows.fieldnames or []) or "URL" not in (rows.fieldnames or []):
            raise ValueError("El CSV debe contener columnas Name y URL.")

        lookup = {}
        for row in rows:
            name = (row.get("Name") or "").strip()
            url = (row.get("URL") or "").strip()
            if name and url:
                lookup[name] = url
        return lookup


def quote_sql_text(value: str) -> str:
    return str(value).replace("'", "''")


def sql_in_clause(field_name: str, values: list[str]) -> str:
    values = [value for value in values if value]
    if not values:
        return "1 = 0"
    joined = ", ".join("'{}'".format(quote_sql_text(value)) for value in values)
    return "{} IN ({})".format(field_name, joined)


def resolve_field(feature_class: str, preferred_names: list[str]) -> Optional[str]:
    import arcpy

    fields = {field.name.lower(): field.name for field in arcpy.ListFields(feature_class)}
    for preferred_name in preferred_names:
        resolved = fields.get(preferred_name.lower())
        if resolved:
            return resolved
    return None


def write_report(path: Union[str, Path], rows: list[dict]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["Name", "status", "old_url", "new_url", "error"]
    with path.open("w", newline="", encoding="utf-8-sig") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def update_footprint_urls(
    feature_class: str,
    attributes_csv: Union[str, Path],
    output_report: Union[str, Path],
    dry_run: bool = True,
) -> list[dict]:
    import arcpy

    url_lookup = read_url_lookup(attributes_csv)
    name_field = resolve_field(feature_class, ["Name"])
    url_field = resolve_field(feature_class, ["URL", "Url", "url"])

    if not name_field:
        raise ValueError("No existe campo Name en {}".format(feature_class))
    if not url_field:
        raise ValueError("No existe campo URL en {}".format(feature_class))

    where = sql_in_clause(name_field, sorted(url_lookup.keys()))
    seen = set()
    report_rows = []

    with arcpy.da.UpdateCursor(feature_class, [name_field, url_field], where_clause=where) as cursor:
        for row in cursor:
            name = row[0]
            if not name:
                continue
            seen.add(name)
            new_url = url_lookup.get(name)
            old_url = row[1] or ""
            if not new_url:
                report_rows.append(
                    {"Name": name, "status": "sin_url_en_csv", "old_url": old_url, "new_url": "", "error": ""}
                )
                continue

            if old_url == new_url:
                status = "sin_cambios"
            else:
                status = "dry_run" if dry_run else "updated"
                if not dry_run:
                    row[1] = new_url
                    cursor.updateRow(row)

            report_rows.append(
                {"Name": name, "status": status, "old_url": old_url, "new_url": new_url, "error": ""}
            )

    for missing_name in sorted(set(url_lookup) - seen):
        report_rows.append(
            {
                "Name": missing_name,
                "status": "no_encontrado_en_feature_class",
                "old_url": "",
                "new_url": url_lookup[missing_name],
                "error": "",
            }
        )

    write_report(output_report, report_rows)
    return report_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update footprint URL values by Name.")
    parser.add_argument("--feature-class", required=True)
    parser.add_argument("--attributes-csv", type=Path, required=True)
    parser.add_argument("--output-report", type=Path)
    parser.add_argument("--apply", action="store_true", help="Write changes. Omit for dry-run.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = args.output_report
    if report is None:
        report = Path("flujo_geosupport_etapas") / "outputs" / "etapa_03_actualizar_footprints_indice" / (
            "04_footprint_url_updates_{}.csv".format(datetime.now().strftime("%Y%m%d_%H%M%S"))
        )

    rows = update_footprint_urls(
        feature_class=args.feature_class,
        attributes_csv=args.attributes_csv,
        output_report=report,
        dry_run=not args.apply,
    )

    counts = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1

    print("Reporte:", report)
    for status, count in sorted(counts.items()):
        print("{}: {}".format(status, count))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
