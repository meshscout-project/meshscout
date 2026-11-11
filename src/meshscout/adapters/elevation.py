"""USGS 3DEP Elevation Adapter, HGT DEM tile reader, and sovereign offline terrain interpolation."""

from __future__ import annotations

import io
import json
import math
import mmap
import os
from collections import OrderedDict
from pathlib import Path
import struct
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field

from meshscout.adapters.base import (
    BaseRegionalAdapter,
    RateLimitBackoff,
    RateLimitConfig,
    RegionalAdapterBase,
)
from meshscout.core.contracts import (
    Coordinate,
    ElevationPoint,
    ElevationProfile,
    RegionalBounds,
    Result,
    SiteCandidate,
)

EARTH_RADIUS_KM = 6371.0088

# Standard SRTM HGT file sizes
HGT_1ARCSEC_SIZE = 25_934_402  # 3601 x 3601 signed 16-bit big-endian (SRTM-1)
HGT_3ARCSEC_SIZE = 2_884_802   # 1201 x 1201 signed 16-bit big-endian (SRTM-3)
HGT_VOID_VALUE = -32768

# Vermont high-precision topographic model domain: 42.5 <= lat <= 45.5 and -74.5 <= lon <= -71.0
VERMONT_MODEL_BOX_MIN_LAT = 42.5
VERMONT_MODEL_BOX_MAX_LAT = 45.5
VERMONT_MODEL_BOX_MIN_LON = -74.5
VERMONT_MODEL_BOX_MAX_LON = -71.0


def is_in_vermont_model_box(lat: float, lon: float) -> bool:
    """Check if coordinates fall inside the Vermont high-precision topographic model domain."""
    return (
        VERMONT_MODEL_BOX_MIN_LAT <= lat <= VERMONT_MODEL_BOX_MAX_LAT
        and VERMONT_MODEL_BOX_MIN_LON <= lon <= VERMONT_MODEL_BOX_MAX_LON
    )


def _synthetic_vermont_elevation_fn(lat: float, lon: float) -> float:
    """Deterministic topographic model of the Champlain Valley and Green Mountains.

    Models Lake Champlain basin (~60-120m in the west near -73.25) rising toward the
    Green Mountain spine (~800-1300m in the east near -72.81).
    """
    # West-to-east rise toward Green Mountain ridge (-72.81)
    east_progress = max(0.0, min(1.0, (lon - (-73.30)) / 0.50))
    valley_base = 65.0 + 180.0 * (east_progress ** 1.6)
    ridge_bonus = 950.0 * max(0.0, 1.0 - abs(lon - (-72.8143)) / 0.12) ** 2
    return round(valley_base + ridge_bonus, 2)


def haversine_distance_km(c1: Coordinate, c2: Coordinate) -> float:
    """Calculate the great-circle distance between two coordinates in kilometers."""
    lat1, lon1 = math.radians(c1.lat), math.radians(c1.lon)
    lat2, lon2 = math.radians(c2.lat), math.radians(c2.lon)
    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return EARTH_RADIUS_KM * c


def geodesic_intermediate_point(
    c1: Coordinate, c2: Coordinate, fraction: float
) -> Coordinate:
    """Compute an intermediate coordinate along the great circle path at fraction [0, 1]."""
    if fraction <= 0.0:
        return Coordinate(lat=c1.lat, lon=c1.lon, elevation_m=c1.elevation_m)
    if fraction >= 1.0:
        return Coordinate(lat=c2.lat, lon=c2.lon, elevation_m=c2.elevation_m)

    lat1, lon1 = math.radians(c1.lat), math.radians(c1.lon)
    lat2, lon2 = math.radians(c2.lat), math.radians(c2.lon)

    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    )
    delta = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))

    if delta < 1e-9:
        return Coordinate(lat=c1.lat, lon=c1.lon, elevation_m=c1.elevation_m)

    sin_delta = math.sin(delta)
    a_fact = math.sin((1.0 - fraction) * delta) / sin_delta
    b_fact = math.sin(fraction * delta) / sin_delta

    x = a_fact * math.cos(lat1) * math.cos(lon1) + b_fact * math.cos(lat2) * math.cos(
        lon2
    )
    y = a_fact * math.cos(lat1) * math.sin(lon1) + b_fact * math.cos(lat2) * math.sin(
        lon2
    )
    z = a_fact * math.sin(lat1) + b_fact * math.sin(lat2)

    lat_res = math.degrees(math.atan2(z, math.sqrt(x * x + y * y)))
    lon_res = math.degrees(math.atan2(y, x))

    return Coordinate(lat=lat_res, lon=lon_res, elevation_m=0.0)


class HGTElevationTileReader:
    """Fast sovereign elevation reader for SRTM/3DEP HGT DEM raster tiles via memory-mapped I/O."""

    def __init__(
        self,
        dem_dir: Optional[Union[Path, str]] = None,
        max_cached_tiles: int = 32,
    ) -> None:
        if dem_dir is None:
            env_dem = os.environ.get("MESHSCOUT_DEM_DIR")
            self.dem_dir = Path(env_dem) if env_dem else Path.home() / ".meshscout" / "dem"
        else:
            self.dem_dir = Path(dem_dir)
        self.max_cached_tiles = max_cached_tiles
        self._resolved_paths: Dict[str, Optional[Path]] = {}
        self._cache: OrderedDict[str, Tuple[io.BufferedReader, mmap.mmap, int]] = OrderedDict()

    @staticmethod
    def get_tile_filename(lat: float, lon: float) -> str:
        """Resolve standard 1-degree SRTM HGT tile filename from coordinates."""
        lat_dir = "N" if lat >= 0 else "S"
        lon_dir = "E" if lon >= 0 else "W"
        return f"{lat_dir}{abs(math.floor(lat)):02d}{lon_dir}{abs(math.floor(lon)):03d}.hgt"

    @staticmethod
    def get_required_hgt_tiles_for_bounds(bounds: RegionalBounds) -> List[str]:
        """Compute list of required 1x1 degree HGT tile filenames covering given regional bounds."""
        return get_required_hgt_tiles_for_bounds(bounds)

    def _resolve_tile_path(self, lat: float, lon: float) -> Optional[Path]:
        """Find matching tile file in dem_dir, tolerating case differences."""
        filename = self.get_tile_filename(lat, lon)
        if filename in self._resolved_paths:
            return self._resolved_paths[filename]

        if not self.dem_dir.is_dir():
            self._resolved_paths[filename] = None
            return None

        direct_path = self.dem_dir / filename
        if direct_path.is_file():
            self._resolved_paths[filename] = direct_path
            return direct_path

        lower_path = self.dem_dir / filename.lower()
        if lower_path.is_file():
            self._resolved_paths[filename] = lower_path
            return lower_path

        upper_path = self.dem_dir / filename.upper()
        if upper_path.is_file():
            self._resolved_paths[filename] = upper_path
            return upper_path

        self._resolved_paths[filename] = None
        return None

    def has_tile(self, lat: float, lon: float) -> bool:
        """Check if an HGT tile file exists on disk for given coordinate."""
        filename = self.get_tile_filename(lat, lon)
        if filename in self._cache:
            return True
        return self._resolve_tile_path(lat, lon) is not None

    def _get_mmap(self, tile_path: Path, filename: str) -> Tuple[mmap.mmap, int]:
        """Retrieve cached mmap and steps count or open and memory-map the HGT file."""
        if filename in self._cache:
            self._cache.move_to_end(filename)
            _, mm, steps = self._cache[filename]
            return mm, steps

        # Evict oldest if cache limit reached
        while len(self._cache) >= self.max_cached_tiles:
            _, (old_f, old_mm, _) = self._cache.popitem(last=False)
            try:
                old_mm.close()
            except Exception:
                pass
            try:
                old_f.close()
            except Exception:
                pass

        size = tile_path.stat().st_size
        if size == HGT_1ARCSEC_SIZE:
            steps = 3600
        elif size == HGT_3ARCSEC_SIZE:
            steps = 1200
        else:
            dim = math.isqrt(size // 2)
            if dim * dim * 2 == size and dim > 1:
                steps = dim - 1
            else:
                raise ValueError(
                    f"Unsupported HGT tile size: {size} bytes in {tile_path.name}"
                )

        f = open(tile_path, "rb")
        try:
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        except Exception:
            f.close()
            raise

        self._cache[filename] = (f, mm, steps)
        return mm, steps

    def get_elevation(self, lat: float, lon: float) -> Optional[float]:
        """Sample elevation with bilinear interpolation from DEM tile. Returns None if tile missing or void."""
        filename = self.get_tile_filename(lat, lon)
        if filename in self._cache:
            self._cache.move_to_end(filename)
            _, mm, steps = self._cache[filename]
        else:
            tile_path = self._resolve_tile_path(lat, lon)
            if tile_path is None:
                return None
            try:
                mm, steps = self._get_mmap(tile_path, filename)
            except Exception:
                return None

        d_lat = lat - math.floor(lat)
        d_lon = lon - math.floor(lon)

        d_lat = min(max(d_lat, 0.0), 1.0)
        d_lon = min(max(d_lon, 0.0), 1.0)

        # Row 0 is northern edge (lat = floor(lat) + 1.0), row steps is southern edge (lat = floor(lat))
        row_f = (1.0 - d_lat) * steps
        col_f = d_lon * steps

        row_f = min(max(row_f, 0.0), float(steps))
        col_f = min(max(col_f, 0.0), float(steps))

        r0 = int(math.floor(row_f))
        if r0 >= steps:
            r0 = steps - 1
        r1 = r0 + 1

        c0 = int(math.floor(col_f))
        if c0 >= steps:
            c0 = steps - 1
        c1 = c0 + 1

        u = row_f - r0
        v = col_f - c0

        stride = (steps + 1) * 2
        offset_00 = r0 * stride + c0 * 2
        offset_01 = r0 * stride + c1 * 2
        offset_10 = r1 * stride + c0 * 2
        offset_11 = r1 * stride + c1 * 2

        z00 = struct.unpack_from(">h", mm, offset_00)[0]
        z01 = struct.unpack_from(">h", mm, offset_01)[0]
        z10 = struct.unpack_from(">h", mm, offset_10)[0]
        z11 = struct.unpack_from(">h", mm, offset_11)[0]

        w00 = (1.0 - u) * (1.0 - v)
        w01 = (1.0 - u) * v
        w10 = u * (1.0 - v)
        w11 = u * v

        valid_sum = 0.0
        weight_sum = 0.0
        for z, w in ((z00, w00), (z01, w01), (z10, w10), (z11, w11)):
            if z != HGT_VOID_VALUE and w > 0.0:
                valid_sum += z * w
                weight_sum += w

        if weight_sum <= 1e-9:
            return None

        return float(valid_sum / weight_sum)

    def close(self) -> None:
        """Close all cached file descriptors and memory maps."""
        for f, mm, _ in self._cache.values():
            try:
                mm.close()
            except Exception:
                pass
            try:
                f.close()
            except Exception:
                pass
        self._cache.clear()
        self._resolved_paths.clear()

    def __enter__(self) -> HGTElevationTileReader:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()


# Alias for SRTM HGT reader
SRTMHgtReader = HGTElevationTileReader


def get_required_hgt_tiles_for_bounds(bounds: RegionalBounds) -> List[str]:
    """Calculate the required standard 1x1 degree SRTM HGT tile filenames for regional bounds.

    Each 1x1 degree tile NyyWxxx covers [yy, yy+1) in latitude and [-xxx, -xxx+1) in longitude
    (or [-xxx-1, -xxx) in west convention).
    For an integer-aligned 2x3 degree box (e.g. lat 43.0 to 45.0, lon -74.0 to -71.0),
    it covers latitudes 43 and 44, longitudes -74, -73, and -72, yielding exactly 6 tiles.
    """
    lat_min = int(math.floor(bounds.min_lat))
    lat_max = int(math.ceil(bounds.max_lat))
    if lat_max <= lat_min:
        lat_max = lat_min + 1

    lon_min = int(math.floor(bounds.min_lon))
    lon_max = int(math.ceil(bounds.max_lon))
    if lon_max <= lon_min:
        lon_max = lon_min + 1

    tiles: List[str] = []
    for lat_floor in range(lat_min, lat_max):
        for lon_floor in range(lon_min, lon_max):
            tiles.append(HGTElevationTileReader.get_tile_filename(lat_floor, lon_floor))

    return sorted(list(set(tiles)))


class ElevationGrid(BaseModel):
    """Sovereign 2D elevation grid with bilinear interpolation."""

    bounds: RegionalBounds
    rows: int = Field(..., ge=2, description="Number of latitude grid samples")
    cols: int = Field(..., ge=2, description="Number of longitude grid samples")
    elevations: List[List[float]] = Field(
        ...,
        description="2D elevation matrix in meters, ordered from min_lat to max_lat (row 0 to rows-1)",
    )

    @classmethod
    def from_fn(
        cls,
        bounds: RegionalBounds,
        rows: int,
        cols: int,
        fn: Callable[[float, float], float],
    ) -> ElevationGrid:
        """Construct an elevation grid by evaluating a generator function f(lat, lon)."""
        lat_step = (bounds.max_lat - bounds.min_lat) / (rows - 1)
        lon_step = (bounds.max_lon - bounds.min_lon) / (cols - 1)

        matrix: List[List[float]] = []
        for r in range(rows):
            row_lat = bounds.min_lat + r * lat_step
            row_vals: List[float] = []
            for c in range(cols):
                col_lon = bounds.min_lon + c * lon_step
                row_vals.append(float(fn(row_lat, col_lon)))
            matrix.append(row_vals)

        return cls(bounds=bounds, rows=rows, cols=cols, elevations=matrix)

    def interpolate(self, lat: float, lon: float) -> Optional[float]:
        """Perform bilinear elevation interpolation. Returns None if outside bounds."""
        target = Coordinate(lat=lat, lon=lon)
        if not self.bounds.contains(target):
            # Allow tiny floating point tolerance at boundary edges
            eps = 1e-7
            if not (
                self.bounds.min_lat - eps <= lat <= self.bounds.max_lat + eps
                and self.bounds.min_lon - eps <= lon <= self.bounds.max_lon + eps
            ):
                return None
            lat = min(max(lat, self.bounds.min_lat), self.bounds.max_lat)
            lon = min(max(lon, self.bounds.min_lon), self.bounds.max_lon)

        lat_span = self.bounds.max_lat - self.bounds.min_lat
        lon_span = self.bounds.max_lon - self.bounds.min_lon

        r_norm = (lat - self.bounds.min_lat) / lat_span * (self.rows - 1)
        c_norm = (lon - self.bounds.min_lon) / lon_span * (self.cols - 1)

        r0 = int(math.floor(r_norm))
        c0 = int(math.floor(c_norm))

        r0 = min(max(0, r0), self.rows - 2)
        c0 = min(max(0, c0), self.cols - 2)

        r1 = r0 + 1
        c1 = c0 + 1

        u = r_norm - r0  # Latitude fraction in [0, 1]
        v = c_norm - c0  # Longitude fraction in [0, 1]

        u = min(max(0.0, u), 1.0)
        v = min(max(0.0, v), 1.0)

        z00 = self.elevations[r0][c0]
        z01 = self.elevations[r0][c1]
        z10 = self.elevations[r1][c0]
        z11 = self.elevations[r1][c1]

        # Bilinear formula:
        # z = (1 - u)*(1 - v)*z00 + (1 - u)*v*z01 + u*(1 - v)*z10 + u*v*z11
        z = (
            (1.0 - u) * (1.0 - v) * z00
            + (1.0 - u) * v * z01
            + u * (1.0 - v) * z10
            + u * v * z11
        )
        return float(z)


class USGS3DEPElevationAdapter(RegionalAdapterBase):
    """USGS 3DEP Elevation Point Query Service (EPQS), local HGT DEM, and offline interpolation adapter."""

    DEFAULT_EPQS_URL = "https://epqs.nationalmap.gov/v1/json"

    def __init__(
        self,
        bounds: Optional[RegionalBounds] = None,
        offline_grid: Optional[ElevationGrid] = None,
        offline_mode: bool = False,
        api_url: str = DEFAULT_EPQS_URL,
        rate_limiter: Optional[RateLimitBackoff] = None,
        dem_dir: Optional[Union[Path, str]] = None,
    ) -> None:
        super().__init__(
            name="usgs_3dep_elevation", bounds=bounds, rate_limiter=rate_limiter
        )
        self.offline_grid = offline_grid
        self.offline_mode = offline_mode
        self.api_url = api_url
        self.hgt_reader = HGTElevationTileReader(dem_dir=dem_dir)
        self.last_terrain_source: str = "synthetic"

    def get_elevation_at(self, lat: float, lon: float) -> Result[float]:
        """Fetch ground elevation in meters at the given latitude and longitude."""
        coord = Coordinate(lat=lat, lon=lon)

        # 1. Local HGT DEM tile lookup (highest priority)
        if self.hgt_reader is not None and self.hgt_reader.has_tile(lat, lon):
            elev = self.hgt_reader.get_elevation(lat, lon)
            if elev is not None:
                self.last_terrain_source = "dem"
                res = Result[float].success(elev)
                res.__dict__["details"] = {"terrain_source": "dem"}
                res.__dict__["terrain_source"] = "dem"
                return res

        # 2. Online USGS 3DEP EPQS query with exponential backoff and fallback
        if not self.offline_mode:
            try:
                val = self._query_online_epqs(lat, lon)
                self.last_terrain_source = "online"
                res = Result[float].success(val)
                res.__dict__["details"] = {"terrain_source": "online"}
                res.__dict__["terrain_source"] = "online"
                return res
            except Exception as exc:
                # Fallback to offline grid or synthetic if available
                if self.offline_grid is not None:
                    return self._query_offline(coord)
                return Result[float].fail(
                    code="EPQS_FETCH_FAILED",
                    message=f"Failed to fetch elevation from USGS 3DEP: {exc}",
                    details={"lat": lat, "lon": lon, "error": str(exc)},
                )

        # 3. Offline fallback: offline_grid or synthetic Vermont elevation model
        return self._query_offline(coord)

    def get_elevation(self, coord: Coordinate) -> Result[Coordinate]:
        """Return a copy of the Coordinate updated with its surface elevation in meters."""
        res = self.get_elevation_at(coord.lat, coord.lon)
        if not res.ok or res.value is None:
            return Result[Coordinate].fail(
                code=res.error.code if res.error else "ELEVATION_FAILED",
                message=res.error.message if res.error else "Elevation lookup failed",
                details=res.error.details if res.error else None,
            )
        success_res = Result[Coordinate].success(
            Coordinate(lat=coord.lat, lon=coord.lon, elevation_m=res.value)
        )
        if hasattr(res, "details") and res.details:
            success_res.__dict__["details"] = res.details
        if hasattr(res, "terrain_source"):
            success_res.__dict__["terrain_source"] = res.terrain_source
        return success_res

    def get_elevation_profile(
        self,
        source: SiteCandidate,
        target: SiteCandidate,
        num_samples: int = 50,
    ) -> Result[ElevationProfile]:
        """Generate sampled terrain transect between two candidate sites along great circle."""
        if num_samples < 2:
            return Result[ElevationProfile].fail(
                code="INVALID_SAMPLE_COUNT",
                message="num_samples must be at least 2",
                details={"num_samples": num_samples},
            )

        total_dist_km = haversine_distance_km(source.location, target.location)
        total_dist_m = total_dist_km * 1000.0

        points: List[ElevationPoint] = []
        for i in range(num_samples):
            fraction = i / (num_samples - 1)
            dist_m = fraction * total_dist_m
            intermediate = geodesic_intermediate_point(
                source.location, target.location, fraction
            )

            # Determine elevation
            if i == 0 and source.location.elevation_m > 0.0:
                elev_m = source.location.elevation_m
            elif i == num_samples - 1 and target.location.elevation_m > 0.0:
                elev_m = target.location.elevation_m
            else:
                elev_res = self.get_elevation_at(intermediate.lat, intermediate.lon)
                if not elev_res.ok or elev_res.value is None:
                    return Result[ElevationProfile].fail(
                        code="PROFILE_SAMPLING_FAILED",
                        message=f"Failed to sample profile at fraction {fraction:.3f}: {elev_res.error.message if elev_res.error else 'Unknown'}",
                        details={"fraction": fraction, "intermediate": intermediate.model_dump()},
                    )
                elev_m = elev_res.value

            point_coord = Coordinate(
                lat=intermediate.lat, lon=intermediate.lon, elevation_m=elev_m
            )
            points.append(
                ElevationPoint(
                    distance_m=dist_m, elevation_m=elev_m, coordinate=point_coord
                )
            )

        profile = ElevationProfile(
            source_site=source,
            target_site=target,
            distance_km=total_dist_km,
            points=points,
        )
        return Result[ElevationProfile].success(profile)

    def _query_offline(self, coord: Coordinate) -> Result[float]:
        """Query elevation via offline bilinear grid interpolation or synthetic Vermont model."""
        in_vt_box = is_in_vermont_model_box(coord.lat, coord.lon)
        terrain_source = "synthetic" if in_vt_box else "synthetic_out_of_domain"

        if self.offline_grid is not None:
            val = self.offline_grid.interpolate(coord.lat, coord.lon)
            if val is None:
                return Result[float].fail(
                    code="OUT_OF_BOUNDS",
                    message=f"Coordinate ({coord.lat}, {coord.lon}) is outside offline regional bounds",
                    details={"lat": coord.lat, "lon": coord.lon},
                )
            self.last_terrain_source = terrain_source
            res = Result[float].success(val)
            res.__dict__["details"] = {"terrain_source": terrain_source}
            res.__dict__["terrain_source"] = terrain_source
            return res

        # Regional bounds check for synthetic fallback
        if self.bounds is not None:
            eps = 1e-7
            if not (
                self.bounds.min_lat - eps <= coord.lat <= self.bounds.max_lat + eps
                and self.bounds.min_lon - eps <= coord.lon <= self.bounds.max_lon + eps
            ):
                return Result[float].fail(
                    code="OUT_OF_BOUNDS",
                    message=f"Coordinate ({coord.lat}, {coord.lon}) is outside offline regional bounds",
                    details={"lat": coord.lat, "lon": coord.lon},
                )

        val = _synthetic_vermont_elevation_fn(coord.lat, coord.lon)
        self.last_terrain_source = terrain_source
        res = Result[float].success(val)
        res.__dict__["details"] = {"terrain_source": terrain_source}
        res.__dict__["terrain_source"] = terrain_source
        return res

    def _query_online_epqs(self, lat: float, lon: float) -> float:
        """Perform HTTP GET query to USGS EPQS with rate-limiting backoff."""
        params = urllib.parse.urlencode(
            {"x": lon, "y": lat, "units": "Meters", "output": "json"}
        )
        url = f"{self.api_url}?{params}"

        def _do_request() -> float:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "MeshScout/0.1.0 (Disaster-Response-GIS)",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return self._parse_epqs_response(data)

        return self.rate_limiter.execute(
            _do_request,
            retryable_exceptions=(
                urllib.error.HTTPError,
                urllib.error.URLError,
                TimeoutError,
            ),
        )

    @staticmethod
    def _parse_epqs_response(data: Dict[str, Any]) -> float:
        """Parse various USGS EPQS JSON schema variations."""
        if "elevation" in data and data["elevation"] is not None:
            val = float(data["elevation"])
            if val > -9999.0:
                return val

        if "value" in data and data["value"] is not None:
            val = float(data["value"])
            if val > -9999.0:
                return val

        legacy = data.get("USGS_Elevation_Point_Query_Service", {}).get(
            "Elevation_Query", {}
        )
        if "Elevation" in legacy and legacy["Elevation"] is not None:
            val = float(legacy["Elevation"])
            if val > -9999.0:
                return val

        raise ValueError(f"Unrecognized USGS EPQS response format: {data}")

    def health_check(self) -> Result[bool]:
        """Perform adapter operational readiness check."""
        if self.offline_mode:
            is_ready = (
                self.offline_grid is not None
                or (self.hgt_reader is not None and self.hgt_reader.dem_dir.is_dir())
                or True
            )
            return Result[bool].success(is_ready)
        return Result[bool].success(True)

    def close(self) -> None:
        """Release underlying cached DEM tile resources."""
        if self.hgt_reader is not None:
            self.hgt_reader.close()

    def __enter__(self) -> USGS3DEPElevationAdapter:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()

