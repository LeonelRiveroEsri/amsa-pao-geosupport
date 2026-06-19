"""Reusable APRX inspection helpers built on arcpy.mp."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Union


def _import_arcpy():
    try:
        import arcpy  # type: ignore
    except ImportError as exc:
        raise ImportError(
            "arcpy is required. Run this code with the ArcGIS Pro Python environment."
        ) from exc

    return arcpy


def _import_pandas():
    try:
        import pandas as pd  # type: ignore
    except ImportError as exc:
        raise ImportError("pandas is required to return inspection tables.") from exc
    except ValueError as exc:
        if "numpy.dtype size changed" in str(exc):
            raise RuntimeError(
                "pandas could not load because pandas and numpy are binary-incompatible "
                "in the active ArcGIS Pro Python environment. Reinstall matching pandas "
                "and numpy packages in that environment before running this notebook."
            ) from exc
        raise

    return pd


def _safe_layer_value(layer: Any, attr_name: str, default: Any = None) -> Any:
    try:
        return getattr(layer, attr_name)
    except Exception:
        return default


def _get_layer_data_source(layer: Any) -> Optional[str]:
    try:
        if layer.supports("DATASOURCE"):
            return layer.dataSource
    except Exception:
        pass

    return None


def _get_connection_info(layer: Any) -> Optional[dict[str, Any]]:
    try:
        return layer.connectionProperties
    except Exception:
        return None


def _layer_has_attachments(arcpy: Any, layer: Any) -> bool:
    for value in (layer, _get_layer_data_source(layer)):
        if not value:
            continue

        try:
            description = arcpy.Describe(value)
            has_attachments = getattr(description, "hasAttachments", None)

            if has_attachments is not None:
                return bool(has_attachments)
        except Exception:
            continue

    return False


def _iter_layers_recursive(container: Any, parent_path: str = "", depth: int = 0, seen: Optional[set[str]] = None):
    if seen is None:
        seen = set()

    for layer in container.listLayers():
        layer_name = _safe_layer_value(layer, "name", "")
        long_name = _safe_layer_value(layer, "longName", layer_name)
        layer_path = long_name or (f"{parent_path}\\{layer_name}" if parent_path else layer_name)
        layer_key = layer_path or str(id(layer))

        if layer_key in seen:
            continue

        seen.add(layer_key)
        yield layer, layer_path, parent_path, depth

        if _safe_layer_value(layer, "isGroupLayer", False):
            yield from _iter_layers_recursive(layer, layer_path, depth + 1, seen)


def _open_project(aprx_path: Union[str, Path]):
    arcpy = _import_arcpy()
    aprx_path = Path(aprx_path)

    if not aprx_path.exists():
        raise FileNotFoundError(f"APRX not found: {aprx_path}")

    return arcpy, arcpy.mp.ArcGISProject(str(aprx_path))


def list_aprx_maps(aprx_path: Union[str, Path]):
    """Return a DataFrame with maps available in an APRX."""

    pd = _import_pandas()
    _, project = _open_project(aprx_path)
    maps = project.listMaps()

    return pd.DataFrame(
        [
            {
                "index": index,
                "map_name": map_obj.name,
                "layer_count": len(map_obj.listLayers()),
            }
            for index, map_obj in enumerate(maps)
        ]
    )


def list_aprx_layers(
    aprx_path: Union[str, Path],
    map_index: Optional[int] = None,
    map_name: Optional[str] = None,
    include_connection_info: bool = True,
):
    """Return a DataFrame with layers from an APRX.

    Choose one map with either ``map_index`` or ``map_name``. If neither is
    provided, layers from every map are returned.
    """

    pd = _import_pandas()
    arcpy, project = _open_project(aprx_path)
    maps = project.listMaps()

    if not maps:
        raise RuntimeError("The APRX does not contain maps.")

    if map_name is not None:
        matching_maps = [map_obj for map_obj in maps if map_obj.name == map_name]

        if not matching_maps:
            available_maps = ", ".join(map_obj.name for map_obj in maps)
            raise ValueError(f"Map not found: {map_name}. Available maps: {available_maps}")

        selected_maps = matching_maps
    elif map_index is not None:
        selected_map_index = map_index

        if selected_map_index < 0 or selected_map_index >= len(maps):
            raise IndexError(f"Invalid map index: {selected_map_index}. Use 0 to {len(maps) - 1}.")

        selected_maps = [maps[selected_map_index]]
    else:
        selected_maps = maps

    layer_rows = []

    for selected_map in selected_maps:
        for order, (layer, layer_path, parent_path, depth) in enumerate(_iter_layers_recursive(selected_map), start=1):
            layer_rows.append(
                {
                    "order": order,
                    "map_name": selected_map.name,
                    "depth": depth,
                    "group_path": parent_path,
                    "layer_path": layer_path,
                    "layer_name": _safe_layer_value(layer, "name"),
                    "long_name": _safe_layer_value(layer, "longName"),
                    "is_group_layer": _safe_layer_value(layer, "isGroupLayer", False),
                    "is_broken": _safe_layer_value(layer, "isBroken", None),
                    "visible": _safe_layer_value(layer, "visible", None),
                    "has_attachments": _layer_has_attachments(arcpy, layer),
                    "data_source": _get_layer_data_source(layer),
                    "connection_info": _get_connection_info(layer) if include_connection_info else None,
                }
            )

    return pd.DataFrame(layer_rows)


def inspect_aprx(
    aprx_path: Union[str, Path],
    map_index: Optional[int] = None,
    map_name: Optional[str] = None,
    include_connection_info: bool = True,
) -> dict[str, Any]:
    """Return maps, layers, sources and attachment summaries for an APRX."""

    maps_df = list_aprx_maps(aprx_path)
    layers_df = list_aprx_layers(
        aprx_path=aprx_path,
        map_index=map_index,
        map_name=map_name,
        include_connection_info=include_connection_info,
    )

    layers_with_sources_df = layers_df[layers_df["data_source"].notna()].copy()
    layers_with_attachments_df = layers_df[layers_df["has_attachments"] == True].copy()

    return {
        "maps": maps_df,
        "layers": layers_df,
        "layers_with_sources": layers_with_sources_df,
        "layers_with_attachments": layers_with_attachments_df,
    }
