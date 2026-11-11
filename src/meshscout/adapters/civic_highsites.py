"""Civic and Public-Safety High-Sites Adapter for MeshScout.

Ingests and filters authentic municipal water towers, fire lookouts,
research towers, and agricultural high structures across Northern New England,
the Adirondacks, and Southern Quebec.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from meshscout.core.contracts import (
    AccessDifficulty,
    Coordinate,
    RegionalBounds,
    SiteCandidate,
    SiteType,
)

DEFAULT_CIVIC_HIGHSITES_CATALOG = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "fixtures"
    / "civic_highsites_catalog.json"
)


def _parse_height_value(val: Any, default_m: float) -> float:
    """Parse height representations into float meters."""
    if val is None:
        return default_m
    try:
        val_str = str(val).strip().lower()
        if val_str.endswith("ft") or val_str.endswith("feet") or val_str.endswith("'"):
            num_str = re.sub(r"[^0-9.]", "", val_str)
            return round(float(num_str) * 0.3048, 2)
        if val_str.endswith("m") or val_str.endswith("meters"):
            num_str = re.sub(r"[^0-9.]", "", val_str)
            return round(float(num_str), 2)
        parsed = float(val_str)
        if parsed >= 0.0:
            return round(parsed, 2)
    except (ValueError, TypeError):
        pass
    return default_m


def load_civic_highsites(
    catalog_path: Optional[Union[str, Path]] = None,
    bounds: Optional[RegionalBounds] = None,
    site_types: Optional[Sequence[Union[SiteType, str]]] = None,
) -> List[SiteCandidate]:
    """Load authentic civic high-sites from catalog JSON and filter by bounds and site types.

    Args:
        catalog_path: Path to catalog JSON file. Defaults to fixtures/civic_highsites_catalog.json.
        bounds: Optional regional bounding box to filter sites within.
        site_types: Optional list of SiteType enum values to filter.

    Returns:
        List of validated SiteCandidate objects matching criteria.
    """
    target_path = Path(catalog_path) if catalog_path is not None else DEFAULT_CIVIC_HIGHSITES_CATALOG

    if not target_path.exists():
        return []

    raw_content = target_path.read_text(encoding="utf-8")
    raw_data = json.loads(raw_content)

    items: List[Dict[str, Any]] = []
    if isinstance(raw_data, list):
        items = raw_data
    elif isinstance(raw_data, dict):
        if "sites" in raw_data and isinstance(raw_data["sites"], list):
            items = raw_data["sites"]
        elif "site_id" in raw_data and "location" in raw_data:
            items = [raw_data]

    allowed_types: Optional[Set[SiteType]] = None
    if site_types is not None:
        allowed_types = {
            st if isinstance(st, SiteType) else SiteType(str(st))
            for st in site_types
        }

    candidates: List[SiteCandidate] = []
    for item in items:
        try:
            candidate = SiteCandidate.model_validate(item)
        except Exception:
            continue

        if allowed_types is not None and candidate.site_type not in allowed_types:
            continue

        if bounds is not None and not bounds.contains(candidate.location):
            continue

        candidates.append(candidate)

    return candidates


def harvest_civic_features_from_geojson(
    geojson_content_or_path: Union[str, Path, Dict[str, Any]],
    site_type: Optional[Union[SiteType, str]] = None,
    default_mast_m: float = 20.0,
    owner_label: str = "Civic / Public Safety",
) -> List[SiteCandidate]:
    """Parse FeatureCollection GeoJSON and synthesize validated SiteCandidate models.

    Args:
        geojson_content_or_path: Path to GeoJSON file, raw JSON string, or parsed dict.
        site_type: Target SiteType category for extracted infrastructure.
        default_mast_m: Fallback antenna mast height in meters if unspecified.
        owner_label: Label prefix or ownership description injected into notes.

    Returns:
        List of validated SiteCandidate objects.
    """
    default_type = (
        (site_type if isinstance(site_type, SiteType) else SiteType(str(site_type)))
        if site_type is not None
        else SiteType.COMMUNICATIONS_TOWER
    )

    # Parse input source
    if isinstance(geojson_content_or_path, dict):
        raw_geojson = geojson_content_or_path
    elif isinstance(geojson_content_or_path, Path):
        raw_geojson = json.loads(geojson_content_or_path.read_text(encoding="utf-8"))
    elif isinstance(geojson_content_or_path, str):
        cleaned = geojson_content_or_path.strip()
        if cleaned.startswith("{") or cleaned.startswith("["):
            raw_geojson = json.loads(cleaned)
        else:
            file_path = Path(cleaned)
            if file_path.is_file():
                raw_geojson = json.loads(file_path.read_text(encoding="utf-8"))
            else:
                raw_geojson = json.loads(cleaned)
    else:
        raise ValueError(f"Unsupported GeoJSON input type: {type(geojson_content_or_path)}")

    # Extract feature list
    features: List[Dict[str, Any]] = []
    if isinstance(raw_geojson, dict):
        if raw_geojson.get("type") == "FeatureCollection":
            features = raw_geojson.get("features", [])
        elif raw_geojson.get("type") == "Feature":
            features = [raw_geojson]
        elif "features" in raw_geojson and isinstance(raw_geojson["features"], list):
            features = raw_geojson["features"]
        else:
            features = [raw_geojson]
    elif isinstance(raw_geojson, list):
        features = raw_geojson

    candidates: List[SiteCandidate] = []
    for idx, feat in enumerate(features):
        if not isinstance(feat, dict):
            continue

        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates")
        if not coords or not isinstance(coords, (list, tuple)):
            continue

        geom_type = geom.get("type", "")
        elev_m = 0.0
        lat: Optional[float] = None
        lon: Optional[float] = None

        if geom_type == "Point" and len(coords) >= 2:
            lon = float(coords[0])
            lat = float(coords[1])
            if len(coords) >= 3:
                elev_m = float(coords[2])
        elif geom_type == "MultiPoint" and len(coords) > 0 and len(coords[0]) >= 2:
            lon = float(coords[0][0])
            lat = float(coords[0][1])
            if len(coords[0]) >= 3:
                elev_m = float(coords[0][2])
        elif geom_type == "Polygon" and len(coords) > 0 and len(coords[0]) > 0:
            ring = coords[0]
            lon = sum(float(pt[0]) for pt in ring) / len(ring)
            lat = sum(float(pt[1]) for pt in ring) / len(ring)
            if len(ring[0]) >= 3:
                elev_m = float(ring[0][2])
        else:
            continue

        if lat is None or lon is None:
            continue
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue

        props: Dict[str, Any] = feat.get("properties") or {}

        # Resolve target site type for this feature
        feat_type: Optional[SiteType] = None
        props_type = props.get("site_type") or props.get("SITE_TYPE")
        if props_type:
            try:
                feat_type = SiteType(str(props_type).lower())
            except ValueError:
                pass
        if feat_type is None:
            man_made = str(props.get("man_made", "")).lower()
            emergency = str(props.get("emergency", "")).lower()
            tower_type = str(props.get("tower:type", "")).lower()
            if man_made == "water_tower":
                feat_type = SiteType.WATER_TOWER
            elif man_made == "silo":
                feat_type = SiteType.SILO
            elif emergency == "fire_lookout" or "observation" in tower_type:
                feat_type = SiteType.FIRE_LOOKOUT
            elif man_made in ("communications_tower", "mast") or "communication" in tower_type:
                feat_type = SiteType.COMMUNICATIONS_TOWER

        target_type = feat_type if feat_type is not None else default_type

        # 1. Human-readable name
        name: Optional[str] = None
        for k in (
            "NAME",
            "name",
            "SITE_NAME",
            "site_name",
            "TOWER_NAME",
            "tower_name",
            "FACILITY_NAME",
            "facility_name",
            "FACNAME",
            "LABEL",
            "label",
            "TITLE",
            "title",
            "DESCRIPTION",
            "description",
        ):
            val = props.get(k)
            if val is not None and str(val).strip():
                name = str(val).strip()
                break
        if not name:
            name = f"{target_type.value.replace('_', ' ').title()} - {idx + 1}"

        # 2. Elevation in meters
        if elev_m == 0.0:
            for k in (
                "ELEVATION",
                "elevation",
                "ELEV_M",
                "elev_m",
                "ELEVATION_M",
                "elevation_m",
                "ELEV",
                "elev",
                "Z",
                "z",
                "ele",
                "ELE",
            ):
                val = props.get(k)
                if val is not None:
                    try:
                        elev_m = float(val)
                        break
                    except (ValueError, TypeError):
                        pass
        if elev_m == 0.0:
            for k in ("ELEV_FT", "elev_ft", "ELEVATION_FT", "elevation_ft"):
                val = props.get(k)
                if val is not None:
                    try:
                        elev_m = float(val) * 0.3048
                        break
                    except (ValueError, TypeError):
                        pass

        # 3. Mast height
        mast_height_m = default_mast_m
        for k in (
            "MAST_HEIGHT_M",
            "mast_height_m",
            "MAST_HEIGHT",
            "mast_height",
            "HEIGHT_M",
            "height_m",
            "HEIGHT",
            "height",
            "tower:height",
            "TOWER_HT",
            "tower_ht",
            "AGL",
            "agl",
            "AGL_M",
            "agl_m",
        ):
            if k in props and props[k] is not None:
                mast_height_m = _parse_height_value(props[k], default_mast_m)
                break

        # 4. Site Identifier
        site_id: Optional[str] = None
        for k in ("SITE_ID", "site_id", "ID", "id", "OBJECTID", "objectid", "FID", "fid"):
            val = props.get(k) or feat.get("id")
            if val is not None and str(val).strip():
                site_id = str(val).strip()
                break
        if not site_id:
            site_id = f"CIVIC-{target_type.value.upper()[:4]}-{idx + 1:04d}"

        # 5. Grid Power
        has_grid_power = False
        power_found = False
        for k in ("has_grid_power", "has_power", "grid_power", "GRID_POWER", "power", "POWER"):
            if k in props and props[k] is not None:
                pv = props[k]
                if isinstance(pv, bool):
                    has_grid_power = pv
                    power_found = True
                    break
                sval = str(pv).strip().lower()
                if sval in ("true", "yes", "1", "y", "grid", "commercial"):
                    has_grid_power = True
                    power_found = True
                    break
                if sval in ("false", "no", "0", "n", "solar", "off-grid", "battery"):
                    has_grid_power = False
                    power_found = True
                    break
        if not power_found:
            if target_type in (SiteType.WATER_TOWER, SiteType.BUILDING_ROOFTOP, SiteType.COMMUNICATIONS_TOWER):
                has_grid_power = True

        # 6. Solar Exposure
        solar_exposure_pct = 100.0
        for k in ("solar_exposure_pct", "solar_exposure", "solar_pct", "SOLAR"):
            if k in props and props[k] is not None:
                try:
                    solar_exposure_pct = max(0.0, min(100.0, float(props[k])))
                    break
                except (ValueError, TypeError):
                    pass

        # 7. Access Difficulty
        access = AccessDifficulty.DRIVE_UP
        for k in ("access_difficulty", "access", "ACCESS", "access_type"):
            if k in props and props[k] is not None:
                sval = str(props[k]).strip().lower().replace(" ", "_").replace("-", "_")
                if sval in ("drive_up", "drive", "road", "paved"):
                    access = AccessDifficulty.DRIVE_UP
                    break
                if sval in ("moderate", "footpath", "gravel", "atv"):
                    access = AccessDifficulty.MODERATE
                    break
                if sval in ("hike_in", "hike", "trail", "walk"):
                    access = AccessDifficulty.HIKE_IN
                    break
                if sval in ("helicopter", "heli", "air"):
                    access = AccessDifficulty.HELICOPTER
                    break

        # 8. Source URL
        source_url: Optional[str] = None
        for k in ("source_url", "url", "URL", "link", "LINK", "website", "WEBSITE"):
            if k in props and props[k]:
                source_url = str(props[k]).strip()
                break

        # 9. Notes & Owner
        notes_parts: List[str] = []
        if owner_label:
            notes_parts.append(owner_label)
        for k in ("notes", "NOTES", "description", "DESC", "comment", "COMMENTS"):
            if k in props and props[k]:
                notes_parts.append(str(props[k]).strip())
                break
        notes = " | ".join(notes_parts) if notes_parts else None

        candidate = SiteCandidate(
            site_id=site_id,
            name=name,
            location=Coordinate(
                lat=round(lat, 6),
                lon=round(lon, 6),
                elevation_m=round(elev_m, 2),
            ),
            site_type=target_type,
            mast_height_m=round(mast_height_m, 2),
            has_grid_power=has_grid_power,
            solar_exposure_pct=round(solar_exposure_pct, 2),
            access_difficulty=access,
            source_url=source_url,
            notes=notes,
        )
        candidates.append(candidate)

    return candidates


def subdivide_bounding_box(
    bounds: Union[RegionalBounds, Tuple[float, float, float, float]],
    max_tile_deg: float = 2.0,
) -> List[Tuple[float, float, float, float]]:
    """Subdivide a regional bounding box into tiles of <= max_tile_deg x max_tile_deg.

    Args:
        bounds: RegionalBounds model or tuple (min_lat, min_lon, max_lat, max_lon).
        max_tile_deg: Maximum span in degrees for both latitude and longitude.

    Returns:
        List of (min_lat, min_lon, max_lat, max_lon) tuples covering the original bounds.
    """
    if isinstance(bounds, RegionalBounds):
        min_lat, max_lat = bounds.min_lat, bounds.max_lat
        min_lon, max_lon = bounds.min_lon, bounds.max_lon
    else:
        min_lat, min_lon, max_lat, max_lon = bounds

    lat_span = max_lat - min_lat
    lon_span = max_lon - min_lon

    if lat_span <= 0.0 or lon_span <= 0.0:
        raise ValueError(f"Invalid bounding box spans: lat_span={lat_span}, lon_span={lon_span}")

    n_lat = max(1, math.ceil(lat_span / max_tile_deg))
    n_lon = max(1, math.ceil(lon_span / max_tile_deg))

    lat_step = lat_span / n_lat
    lon_step = lon_span / n_lon

    tiles: List[Tuple[float, float, float, float]] = []
    for i in range(n_lat):
        t_min_lat = min_lat + i * lat_step
        t_max_lat = min_lat + (i + 1) * lat_step if i < n_lat - 1 else max_lat
        for j in range(n_lon):
            t_min_lon = min_lon + j * lon_step
            t_max_lon = min_lon + (j + 1) * lon_step if j < n_lon - 1 else max_lon
            tiles.append(
                (
                    round(t_min_lat, 6),
                    round(t_min_lon, 6),
                    round(t_max_lat, 6),
                    round(t_max_lon, 6),
                )
            )
    return tiles


def build_overpass_query(
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    timeout_s: int = 90,
) -> str:
    """Construct Overpass QL query retrieving civic infrastructure within a bounding box.

    Queries:
      - man_made=water_tower
      - man_made=communications_tower
      - man_made=mast
      - man_made=silo
      - emergency=fire_lookout
      - man_made=tower with tower:type in communication/observation
    """
    s, w, n, e = min_lat, min_lon, max_lat, max_lon
    return (
        f"[out:json][timeout:{timeout_s}];\n"
        f"(\n"
        f'  node["man_made"="water_tower"]({s},{w},{n},{e});\n'
        f'  way["man_made"="water_tower"]({s},{w},{n},{e});\n'
        f'  node["man_made"="communications_tower"]({s},{w},{n},{e});\n'
        f'  way["man_made"="communications_tower"]({s},{w},{n},{e});\n'
        f'  node["man_made"="mast"]({s},{w},{n},{e});\n'
        f'  way["man_made"="mast"]({s},{w},{n},{e});\n'
        f'  node["man_made"="silo"]({s},{w},{n},{e});\n'
        f'  way["man_made"="silo"]({s},{w},{n},{e});\n'
        f'  node["emergency"="fire_lookout"]({s},{w},{n},{e});\n'
        f'  way["emergency"="fire_lookout"]({s},{w},{n},{e});\n'
        f'  node["man_made"="tower"]["tower:type"~"communication|observation"]({s},{w},{n},{e});\n'
        f'  way["man_made"="tower"]["tower:type"~"communication|observation"]({s},{w},{n},{e});\n'
        f");\n"
        f"out center tags;"
    )


def overpass_json_to_geojson(
    overpass_data: Dict[str, Any],
    region_code: str = "",
) -> Dict[str, Any]:
    """Convert raw Overpass API JSON response elements into a standard GeoJSON FeatureCollection."""
    elements = overpass_data.get("elements", [])
    features: List[Dict[str, Any]] = []

    for elem in elements:
        if not isinstance(elem, dict):
            continue

        elem_type = elem.get("type", "node")
        elem_id = elem.get("id", "")

        # Extract lat/lon coordinates
        lat: Optional[float] = None
        lon: Optional[float] = None
        if "lat" in elem and "lon" in elem:
            try:
                lat = float(elem["lat"])
                lon = float(elem["lon"])
            except (ValueError, TypeError):
                pass
        elif "center" in elem and isinstance(elem["center"], dict):
            try:
                lat = float(elem["center"].get("lat", 0.0))
                lon = float(elem["center"].get("lon", 0.0))
            except (ValueError, TypeError):
                pass

        if lat is None or lon is None:
            continue
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue

        tags: Dict[str, Any] = elem.get("tags") or {}

        # Resolve site_type
        man_made = str(tags.get("man_made", "")).lower()
        emergency = str(tags.get("emergency", "")).lower()
        tower_type = str(tags.get("tower:type", "")).lower()

        if man_made == "water_tower":
            site_type_val = "water_tower"
        elif man_made == "silo":
            site_type_val = "silo"
        elif emergency == "fire_lookout" or "observation" in tower_type:
            site_type_val = "fire_lookout"
        elif man_made in ("communications_tower", "mast") or "communication" in tower_type:
            site_type_val = "communications_tower"
        else:
            site_type_val = "communications_tower"

        # Resolve elevation
        ele_val = tags.get("ele") or tags.get("elevation") or tags.get("elev_m")
        ele_m: Optional[float] = None
        if ele_val is not None:
            try:
                ele_m = round(float(str(ele_val).strip().split()[0]), 2)
            except (ValueError, TypeError, IndexError):
                ele_m = None

        # Resolve height
        height_val = tags.get("height") or tags.get("tower:height") or tags.get("mast_height_m")
        height_m: Optional[float] = None
        if height_val is not None:
            height_m = _parse_height_value(height_val, 20.0)

        # Build site_id and name
        type_code = elem_type[0].upper() if elem_type else "N"
        reg_prefix = f"-{region_code.upper()}" if region_code else ""
        site_id = f"CIVIC-OSM{reg_prefix}-{type_code}{elem_id}"

        name = (
            tags.get("name")
            or tags.get("description")
            or f"Civic {site_type_val.replace('_', ' ').title()} - {type_code}{elem_id}"
        )

        props: Dict[str, Any] = {
            "site_id": site_id,
            "name": name,
            "site_type": site_type_val,
            "osm_id": elem_id,
            "osm_type": elem_type,
            "source_dataset": "civic_osm",
            "license": "ODbL 1.0",
            "attribution": "© OpenStreetMap contributors (ODbL 1.0)",
            **tags,
        }
        if ele_m is not None:
            props["elevation_m"] = ele_m
        if height_m is not None:
            props["mast_height_m"] = height_m

        coords = [round(lon, 6), round(lat, 6)]
        if ele_m is not None:
            coords.append(ele_m)

        features.append(
            {
                "type": "Feature",
                "id": site_id,
                "geometry": {
                    "type": "Point",
                    "coordinates": coords,
                },
                "properties": props,
            }
        )

    return {
        "type": "FeatureCollection",
        "region_code": region_code,
        "features": features,
    }
