"""Screen-space map clustering and viewport bounds fitting utilities for MeshScout."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union


def normalize_conformal_bounds(
    raw_bounds: Dict[str, float],
    width: float = 900.0,
    height: float = 440.0,
    pad_x: float = 42.0,
    pad_y: float = 28.0,
) -> Dict[str, float]:
    """Compute conformal aspect-ratio-corrected viewport bounds.

    Prevents vertical or horizontal stretching across variable geodetic latitudes
    by scaling longitude degrees by cos(center_latitude). Matches the client-side
    conformal map projection math in app.js.

    Args:
        raw_bounds: Bounding box dictionary with min_lat/minLat, max_lat/maxLat,
                    min_lon/minLon, max_lon/maxLon.
        width: Viewport width in screen pixels (default 900).
        height: Viewport height in screen pixels (default 440).
        pad_x: Horizontal padding in screen pixels (default 42).
        pad_y: Vertical padding in screen pixels (default 28).

    Returns:
        Conformal bounding box dictionary:
        {"min_lat": float, "max_lat": float, "min_lon": float, "max_lon": float}
    """
    min_lat = float(raw_bounds.get("min_lat", raw_bounds.get("minLat", 0.0)))
    max_lat = float(raw_bounds.get("max_lat", raw_bounds.get("maxLat", 0.0)))
    min_lon = float(raw_bounds.get("min_lon", raw_bounds.get("minLon", 0.0)))
    max_lon = float(raw_bounds.get("max_lon", raw_bounds.get("maxLon", 0.0)))

    usable_w = max(1.0, width - pad_x * 2.0)
    usable_h = max(1.0, height - pad_y * 2.0)

    center_lat = (min_lat + max_lat) / 2.0
    center_lon = (min_lon + max_lon) / 2.0
    cos_phi = math.cos(math.radians(center_lat))
    if abs(cos_phi) < 1e-6:
        cos_phi = 1.0

    span_lat = max(0.01, max_lat - min_lat)
    span_lon_eq = max(0.01, (max_lon - min_lon) * cos_phi)

    # Conformal scale S (pixels per degree of latitude)
    s = min(usable_w / span_lon_eq, usable_h / span_lat)

    visible_span_lat = usable_h / s
    visible_span_lon = usable_w / (s * cos_phi)

    return {
        "min_lat": center_lat - visible_span_lat / 2.0,
        "max_lat": center_lat + visible_span_lat / 2.0,
        "min_lon": center_lon - visible_span_lon / 2.0,
        "max_lon": center_lon + visible_span_lon / 2.0,
    }


def project_lat_lon(
    lat: float,
    lon: float,
    bounds: Dict[str, float],
    width: float = 900.0,
    height: float = 440.0,
    pad_x: float = 42.0,
    pad_y: float = 28.0,
) -> Tuple[float, float]:
    """Project geodetic lat/lon to 2D screen coordinates within given conformal bounds.

    Args:
        lat: Latitude in decimal degrees.
        lon: Longitude in decimal degrees.
        bounds: Viewport bounds with min_lat, max_lat, min_lon, max_lon.
        width: Screen width.
        height: Screen height.
        pad_x: Horizontal padding.
        pad_y: Vertical padding.

    Returns:
        (x, y) screen pixel coordinates.
    """
    usable_w = width - pad_x * 2.0
    usable_h = height - pad_y * 2.0

    min_lat = bounds["min_lat"]
    max_lat = bounds["max_lat"]
    min_lon = bounds["min_lon"]
    max_lon = bounds["max_lon"]

    lat_span = max(1e-9, max_lat - min_lat)
    lon_span = max(1e-9, max_lon - min_lon)

    x_frac = (lon - min_lon) / lon_span
    y_frac = (max_lat - lat) / lat_span

    x = pad_x + x_frac * usable_w
    y = pad_y + y_frac * usable_h
    return x, y


def cluster_points_screen_grid(
    points: Sequence[Union[Dict[str, Any], Tuple[float, float]]],
    width: float = 900.0,
    height: float = 440.0,
    cell_size: float = 40.0,
    bounds: Optional[Dict[str, float]] = None,
    pad_x: float = 42.0,
    pad_y: float = 28.0,
) -> Dict[str, Any]:
    """Group points into screen-space square grid cells of ~40px.

    When visible density is high (> 1,000 points), clustering prevents DOM bloat
    and illegible visual clutter in SVG canvas rendering.

    Invariants guaranteed:
      - Total cluster counts plus individual point count strictly equals visible point count.
      - Clusters with count == 1 are emitted as individual points.
      - Clusters with count > 1 provide centroid (cx, cy) and bounding box.

    Args:
        points: Sequence of point dicts (with 'lat', 'lon' keys) or (lat, lon) tuples.
        width: Canvas width in pixels.
        height: Canvas height in pixels.
        cell_size: Grid cell side length in screen pixels (default 40.0px).
        bounds: Optional conformal viewport bounds. If None, derived from point extents.
        pad_x: Horizontal padding.
        pad_y: Vertical padding.

    Returns:
        Dictionary containing:
          - 'clusters': List of dicts for cells with count > 1:
              { 'cx', 'cy', 'count', 'min_lat', 'max_lat', 'min_lon', 'max_lon', 'cell_key' }
          - 'points': List of dicts for cells with count == 1:
              { 'x', 'y', 'lat', 'lon', 'original' }
          - 'visible_count': Total number of points inside viewport bounds.
          - 'clustered_sum': Sum of cluster counts + len(points). Guaranteed == visible_count.
    """
    # 1. Parse point list into uniform representation
    parsed_points: List[Tuple[float, float, Any]] = []
    for p in points:
        if isinstance(p, dict):
            loc = p.get("location") or {}
            lat = loc.get("lat") if loc.get("lat") is not None else p.get("lat")
            lon = loc.get("lon") if loc.get("lon") is not None else p.get("lon")
            if lat is not None and lon is not None:
                parsed_points.append((float(lat), float(lon), p))
        elif isinstance(p, (tuple, list)) and len(p) >= 2:
            parsed_points.append((float(p[0]), float(p[1]), p))

    if not parsed_points:
        return {
            "clusters": [],
            "points": [],
            "visible_count": 0,
            "clustered_sum": 0,
        }

    # 2. Determine bounds if not supplied
    if bounds is None:
        min_p_lat = min(pt[0] for pt in parsed_points)
        max_p_lat = max(pt[0] for pt in parsed_points)
        min_p_lon = min(pt[1] for pt in parsed_points)
        max_p_lon = max(pt[1] for pt in parsed_points)
        raw = {
            "min_lat": min_p_lat,
            "max_lat": max_p_lat,
            "min_lon": min_p_lon,
            "max_lon": max_p_lon,
        }
        active_bounds = normalize_conformal_bounds(raw, width, height, pad_x, pad_y)
    else:
        active_bounds = normalize_conformal_bounds(bounds, width, height, pad_x, pad_y)

    b_min_lat = active_bounds["min_lat"]
    b_max_lat = active_bounds["max_lat"]
    b_min_lon = active_bounds["min_lon"]
    b_max_lon = active_bounds["max_lon"]

    # 3. Filter visible points and bin into screen-space cells
    grid: Dict[Tuple[int, int], Dict[str, Any]] = {}
    visible_count = 0

    for lat, lon, orig in parsed_points:
        if lat < b_min_lat or lat > b_max_lat or lon < b_min_lon or lon > b_max_lon:
            continue

        visible_count += 1
        x, y = project_lat_lon(lat, lon, active_bounds, width, height, pad_x, pad_y)
        cell_x = int(math.floor(x / cell_size))
        cell_y = int(math.floor(y / cell_size))
        key = (cell_x, cell_y)

        if key not in grid:
            grid[key] = {
                "x_sum": 0.0,
                "y_sum": 0.0,
                "count": 0,
                "min_lat": lat,
                "max_lat": lat,
                "min_lon": lon,
                "max_lon": lon,
                "items": [],
            }

        cell = grid[key]
        cell["x_sum"] += x
        cell["y_sum"] += y
        cell["count"] += 1
        cell["items"].append({"x": x, "y": y, "lat": lat, "lon": lon, "orig": orig})
        if lat < cell["min_lat"]:
            cell["min_lat"] = lat
        if lat > cell["max_lat"]:
            cell["max_lat"] = lat
        if lon < cell["min_lon"]:
            cell["min_lon"] = lon
        if lon > cell["max_lon"]:
            cell["max_lon"] = lon

    # 4. Partition into clusters (count > 1) and individual points (count == 1)
    clusters: List[Dict[str, Any]] = []
    single_points: List[Dict[str, Any]] = []

    for key, cell in grid.items():
        cnt = cell["count"]
        if cnt == 1:
            item = cell["items"][0]
            single_points.append({
                "x": item["x"],
                "y": item["y"],
                "lat": item["lat"],
                "lon": item["lon"],
                "original": item["orig"],
            })
        else:
            clusters.append({
                "cx": cell["x_sum"] / cnt,
                "cy": cell["y_sum"] / cnt,
                "count": cnt,
                "min_lat": cell["min_lat"],
                "max_lat": cell["max_lat"],
                "min_lon": cell["min_lon"],
                "max_lon": cell["max_lon"],
                "cell_key": f"{key[0]}:{key[1]}",
            })

    cluster_count_sum = sum(c["count"] for c in clusters)
    total_counted = cluster_count_sum + len(single_points)

    # Invariant assertion
    assert total_counted == visible_count, (
        f"Clustering invariant failure: cluster_count ({cluster_count_sum}) + "
        f"singles ({len(single_points)}) != visible ({visible_count})"
    )

    return {
        "clusters": clusters,
        "points": single_points,
        "visible_count": visible_count,
        "clustered_sum": total_counted,
    }
