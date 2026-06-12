from __future__ import annotations

import re
import sqlite3
import unicodedata
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Iterable

import pandas as pd


ORTHO_MOSAIC_EXTENSIONS = {".tif", ".tiff"}
IMAGE_EXTENSIONS = ORTHO_MOSAIC_EXTENSIONS | {".jpg", ".jpeg", ".png", ".sid", ".jp2", ".ecw"}
RENAME_PREFIX = "CL_MLP_PAO_IF_Ortho"
DEFAULT_RENAMED_EXTENSION = ".tif"

SECTOR_ALIASES = {
    "ESTACION DE BOMBEO N 1": "estacion_de_bombeo_no1",
    "ESTACION DE BOMBEO N 2": "estacion_de_bombeo_no2",
    "ESTACION DE BOMBEO N 3": "estacion_de_bombeo_no3",
    "ESTACION CABECERAS EC": "estacion_cabeceras",
    "ESTACION CABECERA": "estacion_cabecera",
    "SUBESTACION EL MAURO PRIORIDAD 1": "subestacion_el_mauro",
}


def strip_accents(value) -> str:
    value = unicodedata.normalize("NFKD", str(value))
    return "".join(char for char in value if not unicodedata.combining(char))


def normalize_key(value) -> str | None:
    if value is None or pd.isna(value):
        return None

    value = strip_accents(value).lower()
    value = value.replace("\\", "/")
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or None


def normalize_sector_text(value) -> str:
    value = strip_accents(value)
    value = re.sub(r"[^0-9A-Za-z]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def normalize_sector_key(value) -> str:
    value = normalize_sector_text(value).lower()
    return value.replace(" ", "_")


def format_sector_token(value) -> str | None:
    normalized = normalize_sector_text(value)
    if not normalized:
        return None

    alias_key = normalized.upper()
    if alias_key in SECTOR_ALIASES:
        return SECTOR_ALIASES[alias_key]

    return normalized.lower().replace(" ", "_")


def is_valid_date_parts(year: int, month: int, day: int) -> bool:
    try:
        datetime(year=year, month=month, day=day)
        return True
    except ValueError:
        return False


def extract_date_token_from_filename(file_name: str) -> dict | None:
    stem = Path(file_name).stem
    stem_without_id = re.sub(r"^GEOSP[-_ ]?TRN[-_ ]?\d+", "", stem, flags=re.IGNORECASE)

    patterns = [
        r"(?<![A-Za-z0-9])(?P<day>\d{2})[-_](?P<month>\d{2})[-_](?P<year>20\d{2}|\d{2})(?!\d)",
        r"(?<!\d)(?P<day>\d{2})(?P<month>\d{2})(?P<year>\d{2})(?!\d)",
        r"(?<!\d)(?P<year>20\d{2})(?P<month>\d{2})(?P<day>\d{2})(?!\d)",
    ]

    candidates = []
    invalid_matches = []
    for pattern in patterns:
        for match in re.finditer(pattern, stem_without_id):
            year = match.group("year")[-2:]
            month = int(match.group("month"))
            day = int(match.group("day"))

            if is_valid_date_parts(2000 + int(year), month, day):
                candidates.append(
                    {
                        "year": year,
                        "month": f"{month:02d}",
                        "day": f"{day:02d}",
                        "date_token": f"{year}_{month:02d}_{day:02d}",
                        "matched_text": match.group(0),
                        "span": match.span(),
                    }
                )
            else:
                invalid_matches.append(match.group(0))

    if not candidates:
        return None

    selected = candidates[-1]
    selected["date_warning"] = "|".join(invalid_matches) if invalid_matches else None
    return selected


def extract_sector_candidates_from_filename(file_name: str, date_match: dict | None) -> list[str]:
    stem = Path(file_name).stem
    working = stem

    if date_match:
        working = working.replace(date_match["matched_text"], " ")

    cleanup_patterns = [
        r"^GEOSP[-_ ]?TRN[-_ ]?\d+",
        r"^SIN[-_ ]?ID",
        r"(?<![A-Z0-9])GS(?![A-Z0-9])",
        r"(?<![A-Z0-9])GD(?![A-Z0-9])",
        r"(?<![A-Z0-9])ORTOFOTO(?![A-Z0-9])",
        r"(?<![A-Z0-9])ORTHOMOSAIC(?![A-Z0-9])",
        r"(?<![A-Z0-9])ORTOMOSAICO(?![A-Z0-9])",
        r"(?<![A-Z0-9])CORTADA(?![A-Z0-9])",
        r"(?<![A-Z0-9])COMPLETA(?![A-Z0-9])",
        r"(?<![A-Z0-9])DRONE(?![A-Z0-9])",
        r"(?<![A-Z0-9])PAO(?![A-Z0-9])",
        r"\(.*?\)",
        r"(?<![A-Z0-9])PRIORIDAD(?![A-Z0-9])\s*\d+",
    ]

    working = strip_accents(working).upper()
    working = re.sub(r"[-_]+", " ", working)
    for pattern in cleanup_patterns:
        working = re.sub(pattern, " ", working, flags=re.IGNORECASE)

    working = re.sub(r"\s+", " ", working).strip()
    if not working:
        return []

    candidates = []
    direct = format_sector_token(working)
    if direct:
        candidates.append(direct)

    sector_key = normalize_sector_key(working)
    for alias_text, alias_value in SECTOR_ALIASES.items():
        if normalize_sector_key(alias_text) in sector_key and alias_value not in candidates:
            candidates.append(alias_value)

    return candidates


def build_expected_image_name(file_name: str, output_extension: str = DEFAULT_RENAMED_EXTENSION) -> dict:
    if re.search(r"1001-03-T-CS|DW-", file_name, flags=re.IGNORECASE):
        return {
            "expected_name": None,
            "expected_file_name": None,
            "expected_stem": None,
            "expected_date_token": None,
            "expected_sector": None,
            "expected_sector_candidates": None,
            "expected_stem_candidates": None,
            "date_warning": None,
            "rename_status": "descartar_posible_plano",
        }

    date_match = extract_date_token_from_filename(file_name)
    if not date_match:
        return {
            "expected_name": None,
            "expected_file_name": None,
            "expected_stem": None,
            "expected_date_token": None,
            "expected_sector": None,
            "expected_sector_candidates": None,
            "expected_stem_candidates": None,
            "date_warning": None,
            "rename_status": "sin_fecha",
        }

    sector_candidates = extract_sector_candidates_from_filename(file_name, date_match)
    if not sector_candidates:
        return {
            "expected_name": None,
            "expected_file_name": None,
            "expected_stem": None,
            "expected_date_token": date_match["date_token"],
            "expected_sector": None,
            "expected_sector_candidates": None,
            "expected_stem_candidates": None,
            "date_warning": date_match.get("date_warning"),
            "rename_status": "sin_sector",
        }

    expected_stems = [f"{RENAME_PREFIX}_{date_match['date_token']}_{sector}" for sector in sector_candidates]
    expected_stem = expected_stems[0]

    return {
        "expected_name": expected_stem,
        "expected_file_name": f"{expected_stem}{output_extension}",
        "expected_stem": expected_stem,
        "expected_date_token": date_match["date_token"],
        "expected_sector": sector_candidates[0],
        "expected_sector_candidates": "|".join(sector_candidates),
        "expected_stem_candidates": "|".join(expected_stems),
        "date_warning": date_match.get("date_warning"),
        "rename_status": "ok",
    }


def scan_input_images(input_folder: str | Path, extensions: Iterable[str] = IMAGE_EXTENSIONS) -> pd.DataFrame:
    input_folder = Path(input_folder)
    extensions = {ext.lower() for ext in extensions}

    if not input_folder.exists():
        raise FileNotFoundError(f"No existe la carpeta input: {input_folder}")

    rows = []
    for file_path in sorted(input_folder.rglob("*")):
        if not file_path.is_file() or file_path.suffix.lower() not in extensions:
            continue

        stat = file_path.stat()
        rows.append(
            {
                "file_name": file_path.name,
                "stem": file_path.stem,
                "extension": file_path.suffix.lower(),
                "path": str(file_path),
                "relative_path": str(file_path.relative_to(input_folder)),
                "size_mb": round(stat.st_size / (1024 * 1024), 3),
                "modified_at": datetime.fromtimestamp(stat.st_mtime),
            }
        )

    return pd.DataFrame(rows)


def add_control_flags(images_df: pd.DataFrame, control_subfolder: str | None) -> pd.DataFrame:
    result = images_df.copy()
    if result.empty:
        result["top_folder"] = pd.Series(dtype="object")
        result["is_in_control_folder"] = pd.Series(dtype="bool")
        return result

    control_key = normalize_key(control_subfolder) if control_subfolder else None
    if not control_key:
        result["is_in_control_folder"] = True
        return result

    result["top_folder"] = result["relative_path"].map(lambda value: str(value).split("\\")[0].split("/")[0])
    result["is_in_control_folder"] = result["top_folder"].map(lambda value: normalize_key(value) == control_key)
    return result


def arcpy_table_to_dataframe(dataset_path: str, max_rows: int | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    import arcpy

    fields = [
        field
        for field in arcpy.ListFields(dataset_path)
        if field.type not in ("Geometry", "Raster", "Blob")
    ]
    field_names = [field.name for field in fields]
    fields_df = pd.DataFrame(
        [
            {
                "name": field.name,
                "alias": field.aliasName,
                "type": field.type,
                "length": field.length,
                "required": field.required,
                "nullable": field.isNullable,
            }
            for field in fields
        ]
    )

    rows = []
    with arcpy.da.SearchCursor(dataset_path, field_names) as cursor:
        for index, values in enumerate(cursor):
            if max_rows is not None and index >= max_rows:
                break
            rows.append(dict(zip(field_names, values)))

    return pd.DataFrame(rows), fields_df


def arcpy_table_fields_to_dataframe(table_path: str) -> pd.DataFrame:
    import arcpy

    return pd.DataFrame(
        [
            {
                "name": field.name,
                "alias": field.aliasName,
                "type": field.type,
                "length": field.length,
                "required": field.required,
                "nullable": field.isNullable,
            }
            for field in arcpy.ListFields(table_path)
            if field.type not in ("Geometry", "Raster", "Blob")
        ]
    )


def arcpy_table_rows_to_dataframe(table_path: str, max_rows: int | None = None) -> pd.DataFrame:
    import arcpy

    field_names = [
        field.name
        for field in arcpy.ListFields(table_path)
        if field.type not in ("Geometry", "Raster", "Blob")
    ]

    rows = []
    with arcpy.da.SearchCursor(table_path, field_names) as cursor:
        for index, values in enumerate(cursor):
            if max_rows is not None and index >= max_rows:
                break
            rows.append(dict(zip(field_names, values)))

    return pd.DataFrame(rows)


def export_mosaic_dataset_paths_to_dataframe(
    mosaic_dataset_path: str,
    output_workspace: str | Path | None = None,
    output_table_name: str | None = None,
    max_rows: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """Exporta los paths reales del mosaic dataset y retorna la tabla como DataFrame.

    Esta es la fuente de control para comparar contra los nombres esperados,
    porque refleja el nombre/ruta final despues de la carga manual al mosaico.
    """
    import arcpy

    if output_workspace is None:
        scratch_gdb = getattr(arcpy.env, "scratchGDB", None)
        if scratch_gdb:
            output_workspace = scratch_gdb
        else:
            scratch_root = Path.cwd() / "outputs" / "arcpy_scratch"
            scratch_root.mkdir(parents=True, exist_ok=True)
            output_workspace = scratch_root / "mosaic_audit_scratch.gdb"
            if not arcpy.Exists(str(output_workspace)):
                arcpy.management.CreateFileGDB(str(scratch_root), output_workspace.name)

    output_workspace = str(output_workspace)
    output_table_name = output_table_name or f"mosaic_paths_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    output_table = str(Path(output_workspace) / output_table_name)

    if arcpy.Exists(output_table):
        arcpy.management.Delete(output_table)

    arcpy.management.ExportMosaicDatasetPaths(mosaic_dataset_path, output_table)

    paths_df = arcpy_table_rows_to_dataframe(output_table, max_rows=max_rows)
    fields_df = arcpy_table_fields_to_dataframe(output_table)
    return paths_df, fields_df, output_table


def detect_candidate_path_fields(fields_df: pd.DataFrame) -> list[str]:
    tokens = ("path", "uri", "url", "file", "name", "source", "raster")
    candidate_fields = []

    for _, row in fields_df.iterrows():
        field_name = row["name"]
        field_type = row["type"]
        normalized_name = field_name.lower()

        if field_type in ("String", "Guid") and any(token in normalized_name for token in tokens):
            candidate_fields.append(field_name)

    return candidate_fields


def extract_mosaic_path_parts(value) -> dict:
    if value is None or pd.isna(value):
        raw_value = ""
    else:
        raw_value = str(value)

    path_value = raw_value.replace("\\", "/")
    file_name = PureWindowsPath(raw_value).name if raw_value else ""
    stem = PureWindowsPath(file_name).stem if file_name else ""

    return {
        "mosaic_path": path_value.lower(),
        "mosaic_file_name": file_name.lower(),
        "mosaic_stem": stem.lower(),
        "mosaic_key": normalize_key(path_value),
        "mosaic_file_key": normalize_key(file_name),
        "mosaic_stem_key": normalize_key(stem),
    }


def build_mosaic_image_inventory(mosaic_df: pd.DataFrame, candidate_fields: Iterable[str]) -> pd.DataFrame:
    inventory_rows = []

    for field in candidate_fields:
        if field not in mosaic_df.columns:
            continue

        for row_index, value in mosaic_df[field].dropna().items():
            path_parts = extract_mosaic_path_parts(value)
            if not path_parts["mosaic_key"]:
                continue

            inventory_rows.append(
                {
                    "mosaic_row_index": row_index,
                    "source_field": field,
                    "source_value": value,
                    **path_parts,
                }
            )

    inventory_df = pd.DataFrame(inventory_rows)
    if inventory_df.empty:
        return inventory_df

    return inventory_df.drop_duplicates(subset=["source_field", "mosaic_key", "mosaic_file_key", "mosaic_stem_key"])


def add_expected_names(ortho_images_df: pd.DataFrame) -> pd.DataFrame:
    if ortho_images_df.empty:
        result = ortho_images_df.copy()
        for column in [
            "expected_name",
            "expected_file_name",
            "expected_stem",
            "expected_date_token",
            "expected_sector",
            "expected_sector_candidates",
            "expected_stem_candidates",
            "date_warning",
            "rename_status",
        ]:
            result[column] = pd.Series(dtype="object")
        return result

    expected_names_df = pd.DataFrame([build_expected_image_name(file_name) for file_name in ortho_images_df["file_name"]])
    return pd.concat([ortho_images_df.reset_index(drop=True), expected_names_df], axis=1)


def add_mosaic_match(input_expected_names_df: pd.DataFrame, mosaic_inventory_df: pd.DataFrame) -> pd.DataFrame:
    if input_expected_names_df.empty:
        result = input_expected_names_df.copy()
        result["expected_name_exists_in_mosaic"] = pd.Series(dtype="bool")
        result["load_status"] = pd.Series(dtype="object")
        return result

    result = input_expected_names_df.copy()
    match_lookup = {}

    if not mosaic_inventory_df.empty:
        for _, mosaic_row in mosaic_inventory_df.iterrows():
            for key_column in ["mosaic_key", "mosaic_file_key", "mosaic_stem_key"]:
                key = normalize_key(mosaic_row.get(key_column))
                if key and key not in match_lookup:
                    match_lookup[key] = mosaic_row

    def find_mosaic_match(row):
        keys = []
        for value in [row.get("expected_file_name"), row.get("expected_stem"), row.get("expected_name")]:
            keys.append(normalize_key(value))

        stem_candidates = row.get("expected_stem_candidates")
        if stem_candidates and not pd.isna(stem_candidates):
            for stem in str(stem_candidates).split("|"):
                keys.append(normalize_key(stem))
                keys.append(normalize_key(f"{stem}{DEFAULT_RENAMED_EXTENSION}"))

        for key in keys:
            if key and key in match_lookup:
                return match_lookup[key]

        return None

    result["mosaic_match"] = result.apply(find_mosaic_match, axis=1)
    result["expected_name_exists_in_mosaic"] = result["mosaic_match"].notna()
    result["matched_mosaic_source_field"] = result["mosaic_match"].map(lambda row: row.get("source_field") if row is not None else None)
    result["matched_mosaic_path"] = result["mosaic_match"].map(lambda row: row.get("mosaic_path") if row is not None else None)
    result["matched_mosaic_file_name"] = result["mosaic_match"].map(lambda row: row.get("mosaic_file_name") if row is not None else None)
    result["matched_mosaic_stem"] = result["mosaic_match"].map(lambda row: row.get("mosaic_stem") if row is not None else None)
    result = result.drop(columns=["mosaic_match"])
    result["load_status"] = result.apply(
        lambda row: row["rename_status"] if row["rename_status"] != "ok" else ("ya_cargada" if row["expected_name_exists_in_mosaic"] else "nueva_candidata"),
        axis=1,
    )
    return result


def build_mosaic_date_index(mosaic_inventory_df: pd.DataFrame) -> dict[str, list[str]]:
    date_index: dict[str, list[str]] = {}
    if mosaic_inventory_df.empty:
        return date_index

    for _, row in mosaic_inventory_df.iterrows():
        value = row.get("mosaic_stem") or row.get("mosaic_path")
        match = re.search(r"(\d{2}_\d{2}_\d{2})", str(value))
        if match:
            date_index.setdefault(match.group(1), [])
            example = row.get("mosaic_path") or row.get("mosaic_stem")
            if example not in date_index[match.group(1)]:
                date_index[match.group(1)].append(example)
    return date_index


def add_triage(input_vs_mosaic_df: pd.DataFrame, mosaic_inventory_df: pd.DataFrame) -> pd.DataFrame:
    result = input_vs_mosaic_df.copy()
    date_index = build_mosaic_date_index(mosaic_inventory_df)

    def date_exists(row) -> bool:
        token = row.get("expected_date_token")
        return bool(token and token in date_index)

    def examples(row) -> str:
        token = row.get("expected_date_token")
        if not token:
            return ""
        return " | ".join(date_index.get(token, [])[:8])

    def triage_status(row) -> str:
        load_status = row.get("load_status")
        if load_status == "nueva_candidata":
            return "revisar_fecha_existente_en_mosaico" if date_exists(row) else "nueva_alta_confianza"
        if load_status == "sin_fecha":
            return "revisar_fecha_o_nombre"
        return load_status

    result["date_exists_in_mosaic"] = result.apply(date_exists, axis=1)
    result["same_date_mosaic_examples"] = result.apply(examples, axis=1)
    result["triage_status"] = result.apply(triage_status, axis=1)
    return result


def export_results(dataframes: dict[str, pd.DataFrame], output_dir: str | Path, run_timestamp: str) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    exported = {}
    for index, (name, dataframe) in enumerate(dataframes.items(), start=1):
        csv_path = output_dir / f"{index:02d}_{name}.csv"
        dataframe.to_csv(csv_path, index=False, encoding="utf-8-sig")
        exported[f"{name}_csv"] = csv_path

    sqlite_path = output_dir / f"auditoria_mosaico_{run_timestamp}.sqlite"
    with sqlite3.connect(sqlite_path) as connection:
        for name, dataframe in dataframes.items():
            dataframe.copy().to_sql(name, connection, if_exists="replace", index=False)
    exported["sqlite"] = sqlite_path
    return exported
