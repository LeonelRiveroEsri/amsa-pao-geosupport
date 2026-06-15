
import arcpy
from pathlib import Path
DUPLICATE_ACTION = "EXCLUDE_DUPLICATES"
UPDATE_CELLSIZE = "UPDATE_CELL_SIZES"
UPDATE_BOUNDARY = "UPDATE_BOUNDARY"
UPDATE_OVERVIEWS = "NO_OVERVIEWS"

MAX_PYRAMID_LEVELS = None
MAX_CELL_SIZE = 0
MINIMUM_DIMENSION = 1500

SUBFOLDERS = "SUBFOLDERS"
BUILD_PYRAMIDS = "BUILD_PYRAMIDS"
CALC_STATS = "CALCULATE_STATISTICS"
BUILD_THUMBNAILS = "BUILD_THUMBNAILS"
FORCE_SP_REF = "NO_FORCE_SPATIAL_REFERENCE"
ESTIMATE_STATS = "ESTIMATE_STATISTICS"
PIXEL_CACHE = "NO_PIXEL_CACHE"

# BuildFootprints (según tu script)
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

# Campos personalizados (fijos)
MAXPS_VALUE = 10000
LOWPS_VALUE = 0.15


in_mosaic = ''
imagen_input = ''

stem = Path(imagen_input).stem
where = f"Name = '{stem}'"
arcpy.management.AddRastersToMosaicDataset(
        in_mosaic_dataset=in_mosaic,
        raster_type="Raster Dataset",
        input_path=imagen_input,
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
        cache_location=rf'{Path.home()}\AppData\Local\ESRI\rasterproxies"
        ) 



arcpy.management.BuildFootprints(
                in_mosaic,
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
                FP_SIMPLIFY_TOL
            )
print("Footprints: OK.")

# 3) Update fields
print("Actualizando campos personalizados...")
updated = 0
cols_update = [ "MaxPS", "LowPS"]
with arcpy.da.UpdateCursor(in_mosaic, cols_update, where_clause=where) as cur:
    for row in cur:
        row[0] = float(MAXPS_VALUE)
        row[1] = float(LOWPS_VALUE)
        cur.updateRow(row)
        updated += 1