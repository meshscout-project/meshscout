"""Living Mesh SQLite Registry (mesh_state.db) and 360-Degree Home Node Reach Analyzer.

Provides persistent state management for regional mesh repeaters, workspace preferences
(operator's last location, zoom, home coordinates, hardware/protocol/season presets),
privacy-fuzzed club snapshot sharing, and 360-degree home node azimuth and link reach
evaluation.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
import math
from pathlib import Path
import re
import shutil
import sqlite3
from typing import Any, Callable, Dict, Generator, List, Optional, Sequence, Tuple, Union
from pydantic import BaseModel, Field

from meshscout.core.contracts import (
    Coordinate,
    ElevationPoint,
    ElevationProfile,
    RadioConfig,
    Result,
    SiteCandidate,
    SiteType,
)
from meshscout.core.fresnel import analyze_fresnel_clearance, haversine_distance_km
from meshscout.core.itm import evaluate_point_to_point_link
from meshscout.core.scorer import score_site_viability

COMPASS_16_WINDS: Tuple[str, ...] = (
    "N",
    "NNE",
    "NE",
    "ENE",
    "E",
    "ESE",
    "SE",
    "SSE",
    "S",
    "SSW",
    "SW",
    "WSW",
    "W",
    "WNW",
    "NW",
    "NNW",
)


class DeploymentStatus(str, Enum):
    """Lifecycle deployment status of a mesh repeater or node site."""

    CANDIDATE = "candidate"
    TESTING = "testing"
    ACTIVE_ON_AIR = "active_on_air"
    BLOCKED = "blocked"
    DISMANTLED = "dismantled"


class WorkspacePreferences(BaseModel):
    """Persistent operator workspace preferences and last-used location state."""

    last_lat: float = Field(default=44.4759, ge=-90.0, le=90.0)
    last_lon: float = Field(default=-73.2121, ge=-180.0, le=180.0)
    last_elev_m: float = Field(default=61.0)
    last_zoom: int = Field(default=11, ge=1, le=20)
    last_region: str = Field(default="vt_chittenden", min_length=1)
    home_name: str = Field(default="Burlington Home Node", min_length=1)
    home_lat: float = Field(default=44.4759, ge=-90.0, le=90.0)
    home_lon: float = Field(default=-73.2121, ge=-180.0, le=180.0)
    home_elev_m: float = Field(default=61.0)
    home_height_agl_m: float = Field(default=8.0, ge=0.0)
    privacy_fuzz_enabled: bool = Field(default=True)
    hardware_preset: str = Field(default="RAK4631_SOLAR", min_length=1)
    protocol_profile: str = Field(default="MESHTASTIC_LONGFAST", min_length=1)
    season_profile: str = Field(default="WINTER_LEAF_OFF", min_length=1)


class RegisteredNode(BaseModel):
    """Persistent registered node or repeater high site in the Living Mesh Registry."""

    site_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    coordinate: Coordinate
    height_agl_m: float = Field(..., ge=0.0)
    site_type: SiteType = Field(default=SiteType.CUSTOM)
    status: DeploymentStatus = Field(default=DeploymentStatus.CANDIDATE)
    hardware_preset: str = Field(default="RAK4631_SOLAR", min_length=1)
    owner: Optional[str] = Field(default=None)
    is_public_land: bool = Field(default=False)
    notes: str = Field(default="")
    privacy_fuzzed: bool = Field(default=False)
    source_url: str = Field(default="")
    updated_at: str = Field(..., min_length=1)


class HomeTowerReachItem(BaseModel):
    """Evaluated RF link and azimuth reach from the operator's home node to a tower site."""

    site_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    site_type: SiteType
    status: DeploymentStatus
    distance_km: float = Field(..., ge=0.0)
    azimuth_deg: float = Field(..., ge=0.0, lt=360.0)
    cardinal_direction: str = Field(..., min_length=1)
    has_line_of_sight: bool
    fresnel_60pct_clear: bool
    rx_power_dbm: float
    link_margin_db: float
    viability_score: float = Field(..., ge=0.0, le=100.0)
    recommended_rank: int = Field(..., ge=1)


class HomeReachReport(BaseModel):
    """360-degree home node reach analysis and directional antenna alignment guidance."""

    home_coordinate: Coordinate
    home_height_agl_m: float = Field(..., ge=0.0)
    best_azimuth_deg: Optional[float] = Field(default=None)
    best_cardinal_direction: Optional[str] = Field(default=None)
    reachable_active_count: int = Field(..., ge=0)
    reachable_candidate_count: int = Field(..., ge=0)
    ranked_towers: List[HomeTowerReachItem] = Field(default_factory=list)


def _utc_now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _fuzz_coordinate(coord: Coordinate, grid_deg: float = 0.002) -> Coordinate:
    """Snap a private node coordinate to an approximate ~200m grid for privacy."""
    fuzzed_lat = round(round(coord.lat / grid_deg) * grid_deg, 4)
    fuzzed_lon = round(round(coord.lon / grid_deg) * grid_deg, 4)
    fuzzed_elev = round(coord.elevation_m, 0)
    return Coordinate(lat=fuzzed_lat, lon=fuzzed_lon, elevation_m=fuzzed_elev)


def compute_azimuth_bearing(c1: Coordinate, c2: Coordinate) -> Tuple[float, str]:
    """Compute initial forward azimuth bearing in degrees [0.0, 360.0) and 16-wind cardinal label."""
    lat1 = math.radians(c1.lat)
    lat2 = math.radians(c2.lat)
    dlon = math.radians(c2.lon - c1.lon)

    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)

    initial_bearing = math.degrees(math.atan2(x, y))
    azimuth_deg = round((initial_bearing + 360.0) % 360.0, 2)
    if azimuth_deg >= 360.0:
        azimuth_deg = 0.0

    sector_idx = int(math.floor(((azimuth_deg + 11.25) % 360.0) / 22.5)) % 16
    cardinal = COMPASS_16_WINDS[sector_idx]
    return (azimuth_deg, cardinal)


def _build_transect_profile(
    home_site: SiteCandidate,
    target_site: SiteCandidate,
    num_points: int = 15,
    elevation_fn: Optional[Callable[[float, float], float]] = None,
) -> ElevationProfile:
    """Build a synthetic or DEM-sampled ElevationProfile between home_site and target_site."""
    dist_km = haversine_distance_km(home_site.location, target_site.location)
    total_d_m = max(dist_km * 1000.0, 1.0)
    dist_km_safe = total_d_m / 1000.0

    points: List[ElevationPoint] = []
    steps = max(2, num_points)
    for i in range(steps):
        frac = i / (steps - 1)
        lat = home_site.location.lat + frac * (target_site.location.lat - home_site.location.lat)
        lon = home_site.location.lon + frac * (target_site.location.lon - home_site.location.lon)
        d_m = round(frac * total_d_m, 2)

        if i == 0:
            elev = home_site.location.elevation_m
        elif i == steps - 1:
            elev = target_site.location.elevation_m
        elif elevation_fn is not None:
            elev = float(elevation_fn(lat, lon))
        else:
            elev = (
                home_site.location.elevation_m
                + frac * (target_site.location.elevation_m - home_site.location.elevation_m)
            )

        points.append(
            ElevationPoint(
                distance_m=d_m,
                elevation_m=round(elev, 2),
                coordinate=Coordinate(lat=round(lat, 6), lon=round(lon, 6), elevation_m=round(elev, 2)),
            )
        )

    return ElevationProfile(
        source_site=home_site,
        target_site=target_site,
        distance_km=round(dist_km_safe, 4),
        points=points,
    )


def evaluate_home_node_reach(
    home_coord: Coordinate,
    home_height_agl_m: float,
    nodes: Sequence[RegisteredNode],
    radio: Optional[RadioConfig] = None,
    elevation_fn: Optional[Callable[[float, float], float]] = None,
) -> Result[HomeReachReport]:
    """Evaluate 360-degree point-to-point reach from the operator's home node to registered sites.

    Filters out `BLOCKED` and `DISMANTLED` sites, computes forward azimuth and 16-wind compass direction,
    evaluates Longley-Rice ITM link budget and Fresnel clearance, and ranks towers by:
      1. Reachability (`link_margin_db >= 0.0`)
      2. Active on-air status (`ACTIVE_ON_AIR` > `TESTING` > `CANDIDATE`)
      3. Direct Line-of-Sight (`has_line_of_sight`)
      4. Combined RF link margin and civic site viability score
    """
    if home_height_agl_m < 0.0:
        return Result.fail(
            code="INVALID_HOME_HEIGHT",
            message=f"home_height_agl_m must be non-negative, got {home_height_agl_m}",
        )

    if radio is None:
        radio = RadioConfig()

    home_candidate = SiteCandidate(
        site_id="HOME-NODE",
        name="Operator Home Node",
        location=home_coord,
        site_type=SiteType.BUILDING_ROOFTOP,
        mast_height_m=home_height_agl_m,
    )

    active_candidates = [
        n for n in nodes if n.status not in (DeploymentStatus.BLOCKED, DeploymentStatus.DISMANTLED)
    ]
    raw_items: List[HomeTowerReachItem] = []

    for node in active_candidates:
        target_candidate = SiteCandidate(
            site_id=node.site_id,
            name=node.name,
            location=node.coordinate,
            site_type=node.site_type,
            mast_height_m=node.height_agl_m,
            notes=node.notes,
        )

        profile = _build_transect_profile(
            home_site=home_candidate,
            target_site=target_candidate,
            num_points=15,
            elevation_fn=elevation_fn,
        )

        link_res = evaluate_point_to_point_link(profile=profile, radio=radio)
        if not link_res.ok or link_res.value is None:
            continue
        link = link_res.value

        fresnel_res = analyze_fresnel_clearance(
            profile=profile,
            frequency_mhz=radio.frequency_mhz,
        )
        fresnel_60 = (
            fresnel_res.value.fresnel_60pct_clear
            if (fresnel_res.ok and fresnel_res.value is not None)
            else (link.fresnel_clearance_ratio >= 0.60)
        )

        viability_res = score_site_viability(site=target_candidate)
        viability_score = (
            viability_res.value.composite_score
            if (viability_res.ok and viability_res.value is not None)
            else 70.0
        )

        az_deg, cardinal = compute_azimuth_bearing(home_coord, node.coordinate)

        raw_items.append(
            HomeTowerReachItem(
                site_id=node.site_id,
                name=node.name,
                site_type=node.site_type,
                status=node.status,
                distance_km=round(profile.distance_km, 3),
                azimuth_deg=az_deg,
                cardinal_direction=cardinal,
                has_line_of_sight=link.has_line_of_sight,
                fresnel_60pct_clear=fresnel_60,
                rx_power_dbm=link.rx_power_dbm,
                link_margin_db=link.link_margin_db,
                viability_score=viability_score,
                recommended_rank=1,
            )
        )

    status_priority: Dict[DeploymentStatus, int] = {
        DeploymentStatus.ACTIVE_ON_AIR: 3,
        DeploymentStatus.TESTING: 2,
        DeploymentStatus.CANDIDATE: 1,
        DeploymentStatus.BLOCKED: 0,
        DeploymentStatus.DISMANTLED: 0,
    }

    raw_items.sort(
        key=lambda item: (
            item.link_margin_db >= 0.0,
            status_priority.get(item.status, 0),
            item.has_line_of_sight,
            round(item.link_margin_db + 0.5 * item.viability_score, 4),
        ),
        reverse=True,
    )

    ranked_items: List[HomeTowerReachItem] = []
    for idx, item in enumerate(raw_items, start=1):
        ranked_items.append(item.model_copy(update={"recommended_rank": idx}))

    reachable_active = sum(
        1
        for item in ranked_items
        if item.link_margin_db >= 0.0 and item.status == DeploymentStatus.ACTIVE_ON_AIR
    )
    reachable_candidates = sum(
        1
        for item in ranked_items
        if item.link_margin_db >= 0.0
        and item.status in (DeploymentStatus.CANDIDATE, DeploymentStatus.TESTING)
    )

    best_az: Optional[float] = None
    best_card: Optional[str] = None
    for item in ranked_items:
        if item.link_margin_db >= 0.0:
            best_az = item.azimuth_deg
            best_card = item.cardinal_direction
            break

    return Result.success(
        HomeReachReport(
            home_coordinate=home_coord,
            home_height_agl_m=home_height_agl_m,
            best_azimuth_deg=best_az,
            best_cardinal_direction=best_card,
            reachable_active_count=reachable_active,
            reachable_candidate_count=reachable_candidates,
            ranked_towers=ranked_items,
        )
    )


WORKSPACE_ID_REGEX = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")


def list_available_workspaces(base_dir: Optional[Union[Path, str]] = None) -> List[str]:
    """Scan and return a sorted list of valid workspace identifiers containing a mesh_state.db file.

    If mesh_state.db exists in the base directory root, 'default' is included in the returned list.
    """
    root = Path.home() / ".meshscout" if base_dir is None else Path(base_dir)
    workspaces: set[str] = set()

    if (root / "mesh_state.db").is_file():
        workspaces.add("default")

    workspaces_dir = root / "workspaces"
    if workspaces_dir.is_dir():
        for entry in workspaces_dir.iterdir():
            if entry.is_dir() and WORKSPACE_ID_REGEX.match(entry.name):
                if (entry / "mesh_state.db").is_file():
                    workspaces.add(entry.name)

    return sorted(workspaces)


class LivingMeshRegistry:
    """SQLite-backed Living Mesh Registry (`mesh_state.db`) in WAL mode."""

    def __init__(
        self,
        db_path: Optional[Path | str] = None,
        workspace_id: str = "default",
    ) -> None:
        if not isinstance(workspace_id, str) or not WORKSPACE_ID_REGEX.match(workspace_id):
            raise ValueError(
                f"Invalid workspace_id: {workspace_id!r}. Must match regex '^[a-zA-Z0-9_-]{{1,32}}$' and contain no path traversal characters."
            )
        self.workspace_id = workspace_id
        if db_path is not None:
            self.db_path = Path(db_path)
        elif workspace_id == "default":
            self.db_path = Path.home() / ".meshscout" / "mesh_state.db"
        else:
            self.db_path = Path.home() / ".meshscout" / "workspaces" / workspace_id / "mesh_state.db"

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        bak_path = self.db_path.with_suffix(".db.bak-v05")
        if self.db_path.exists() and not bak_path.exists():
            shutil.copy2(self.db_path, bak_path)

        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workspace_prefs (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    last_lat REAL NOT NULL,
                    last_lon REAL NOT NULL,
                    last_elev_m REAL NOT NULL,
                    last_zoom INTEGER NOT NULL,
                    last_region TEXT NOT NULL,
                    home_name TEXT NOT NULL,
                    home_lat REAL NOT NULL,
                    home_lon REAL NOT NULL,
                    home_elev_m REAL NOT NULL,
                    home_height_agl_m REAL NOT NULL,
                    privacy_fuzz_enabled INTEGER NOT NULL,
                    hardware_preset TEXT NOT NULL,
                    protocol_profile TEXT NOT NULL,
                    season_profile TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mesh_nodes (
                    site_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    lat REAL NOT NULL,
                    lon REAL NOT NULL,
                    elevation_m REAL NOT NULL,
                    height_agl_m REAL NOT NULL,
                    site_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    hardware_preset TEXT NOT NULL,
                    owner TEXT,
                    is_public_land INTEGER NOT NULL DEFAULT 0,
                    notes TEXT NOT NULL DEFAULT '',
                    privacy_fuzzed INTEGER NOT NULL DEFAULT 0,
                    source_url TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                """
            )
            columns = [
                row["name"]
                for row in conn.execute("PRAGMA table_info(mesh_nodes);").fetchall()
            ]
            if "source_url" not in columns:
                conn.execute(
                    "ALTER TABLE mesh_nodes ADD COLUMN source_url TEXT NOT NULL DEFAULT '';"
                )
            # Ensure singleton default row exists
            row = conn.execute("SELECT id FROM workspace_prefs WHERE id = 1;").fetchone()
            if row is None:
                defaults = WorkspacePreferences()
                conn.execute(
                    """
                    INSERT INTO workspace_prefs (
                        id, last_lat, last_lon, last_elev_m, last_zoom, last_region,
                        home_name, home_lat, home_lon, home_elev_m, home_height_agl_m,
                        privacy_fuzz_enabled, hardware_preset, protocol_profile, season_profile
                    ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        defaults.last_lat,
                        defaults.last_lon,
                        defaults.last_elev_m,
                        defaults.last_zoom,
                        defaults.last_region,
                        defaults.home_name,
                        defaults.home_lat,
                        defaults.home_lon,
                        defaults.home_elev_m,
                        defaults.home_height_agl_m,
                        1 if defaults.privacy_fuzz_enabled else 0,
                        defaults.hardware_preset,
                        defaults.protocol_profile,
                        defaults.season_profile,
                    ),
                )
            conn.commit()

    def get_preferences(self) -> WorkspacePreferences:
        """Retrieve persistent operator workspace preferences."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM workspace_prefs WHERE id = 1;").fetchone()
            if row is None:
                return WorkspacePreferences()
            return WorkspacePreferences(
                last_lat=float(row["last_lat"]),
                last_lon=float(row["last_lon"]),
                last_elev_m=float(row["last_elev_m"]),
                last_zoom=int(row["last_zoom"]),
                last_region=str(row["last_region"]),
                home_name=str(row["home_name"]),
                home_lat=float(row["home_lat"]),
                home_lon=float(row["home_lon"]),
                home_elev_m=float(row["home_elev_m"]),
                home_height_agl_m=float(row["home_height_agl_m"]),
                privacy_fuzz_enabled=bool(row["privacy_fuzz_enabled"]),
                hardware_preset=str(row["hardware_preset"]),
                protocol_profile=str(row["protocol_profile"]),
                season_profile=str(row["season_profile"]),
            )

    def save_preferences(self, prefs: WorkspacePreferences) -> WorkspacePreferences:
        """Persist operator workspace preferences to the singleton row (`id = 1`)."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workspace_prefs (
                    id, last_lat, last_lon, last_elev_m, last_zoom, last_region,
                    home_name, home_lat, home_lon, home_elev_m, home_height_agl_m,
                    privacy_fuzz_enabled, hardware_preset, protocol_profile, season_profile
                ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    last_lat = excluded.last_lat,
                    last_lon = excluded.last_lon,
                    last_elev_m = excluded.last_elev_m,
                    last_zoom = excluded.last_zoom,
                    last_region = excluded.last_region,
                    home_name = excluded.home_name,
                    home_lat = excluded.home_lat,
                    home_lon = excluded.home_lon,
                    home_elev_m = excluded.home_elev_m,
                    home_height_agl_m = excluded.home_height_agl_m,
                    privacy_fuzz_enabled = excluded.privacy_fuzz_enabled,
                    hardware_preset = excluded.hardware_preset,
                    protocol_profile = excluded.protocol_profile,
                    season_profile = excluded.season_profile;
                """,
                (
                    prefs.last_lat,
                    prefs.last_lon,
                    prefs.last_elev_m,
                    prefs.last_zoom,
                    prefs.last_region,
                    prefs.home_name,
                    prefs.home_lat,
                    prefs.home_lon,
                    prefs.home_elev_m,
                    prefs.home_height_agl_m,
                    1 if prefs.privacy_fuzz_enabled else 0,
                    prefs.hardware_preset,
                    prefs.protocol_profile,
                    prefs.season_profile,
                ),
            )
            conn.commit()
        return self.get_preferences()

    def seed_candidates(self, candidates: Sequence[SiteCandidate]) -> int:
        """Upsert regional SiteCandidate items without overwriting user status, preset, or notes."""
        if not candidates:
            return 0
        now_iso = _utc_now_iso()
        upserted = 0
        with self._connect() as conn:
            for cand in candidates:
                is_public = cand.site_type in (
                    SiteType.MOUNTAIN_PEAK,
                    SiteType.FIRE_LOOKOUT,
                    SiteType.WATER_TOWER,
                )
                source_url = getattr(cand, "source_url", "") or ""
                conn.execute(
                    """
                    INSERT INTO mesh_nodes (
                        site_id, name, lat, lon, elevation_m, height_agl_m,
                        site_type, status, hardware_preset, owner,
                        is_public_land, notes, privacy_fuzzed, source_url, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(site_id) DO UPDATE SET
                        name = excluded.name,
                        lat = excluded.lat,
                        lon = excluded.lon,
                        elevation_m = excluded.elevation_m,
                        height_agl_m = excluded.height_agl_m,
                        site_type = excluded.site_type,
                        source_url = CASE
                            WHEN mesh_nodes.source_url = '' THEN excluded.source_url
                            ELSE mesh_nodes.source_url
                        END,
                        notes = CASE
                            WHEN mesh_nodes.notes = '' THEN excluded.notes
                            ELSE mesh_nodes.notes
                        END;
                    """,
                    (
                        cand.site_id,
                        cand.name,
                        cand.location.lat,
                        cand.location.lon,
                        cand.location.elevation_m,
                        cand.mast_height_m,
                        cand.site_type.value,
                        DeploymentStatus.CANDIDATE.value,
                        "RAK4631_SOLAR",
                        None,
                        1 if is_public else 0,
                        cand.notes or "",
                        0,
                        source_url,
                        now_iso,
                    ),
                )
                upserted += 1
            conn.commit()
        return upserted

    @staticmethod
    def _row_to_node(row: sqlite3.Row) -> RegisteredNode:
        return RegisteredNode(
            site_id=str(row["site_id"]),
            name=str(row["name"]),
            coordinate=Coordinate(
                lat=float(row["lat"]),
                lon=float(row["lon"]),
                elevation_m=float(row["elevation_m"]),
            ),
            height_agl_m=float(row["height_agl_m"]),
            site_type=SiteType(str(row["site_type"])),
            status=DeploymentStatus(str(row["status"])),
            hardware_preset=str(row["hardware_preset"]),
            owner=str(row["owner"]) if row["owner"] is not None else None,
            is_public_land=bool(row["is_public_land"]),
            notes=str(row["notes"]),
            privacy_fuzzed=bool(row["privacy_fuzzed"]),
            source_url=str(row["source_url"]) if "source_url" in row.keys() else "",
            updated_at=str(row["updated_at"]),
        )

    def list_nodes(self, status: Optional[DeploymentStatus] = None) -> List[RegisteredNode]:
        """List registered nodes, optionally filtered by DeploymentStatus."""
        with self._connect() as conn:
            if status is None:
                rows = conn.execute(
                    "SELECT * FROM mesh_nodes ORDER BY site_id ASC;"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM mesh_nodes WHERE status = ? ORDER BY site_id ASC;",
                    (status.value,),
                ).fetchall()
        return [self._row_to_node(r) for r in rows]

    def update_node_status(
        self,
        site_id: str,
        status: DeploymentStatus,
        notes: Optional[str] = None,
        hardware_preset: Optional[str] = None,
    ) -> Result[RegisteredNode]:
        """Update deployment status, notes, or hardware preset for an existing node."""
        now_iso = _utc_now_iso()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM mesh_nodes WHERE site_id = ?;", (site_id,)
            ).fetchone()
            if row is None:
                return Result.fail(
                    code="NODE_NOT_FOUND",
                    message=f"Site ID '{site_id}' does not exist in mesh_nodes registry.",
                )

            new_notes = notes if notes is not None else str(row["notes"])
            new_preset = (
                hardware_preset if hardware_preset is not None else str(row["hardware_preset"])
            )

            conn.execute(
                """
                UPDATE mesh_nodes
                SET status = ?, notes = ?, hardware_preset = ?, updated_at = ?
                WHERE site_id = ?;
                """,
                (status.value, new_notes, new_preset, now_iso, site_id),
            )
            conn.commit()
            updated_row = conn.execute(
                "SELECT * FROM mesh_nodes WHERE site_id = ?;", (site_id,)
            ).fetchone()
            return Result.success(self._row_to_node(updated_row))

    def insert_node(self, node: RegisteredNode) -> Result[RegisteredNode]:
        """Insert or update a registered node in the Living Mesh SQLite database."""
        now_iso = _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO mesh_nodes (
                    site_id, name, lat, lon, elevation_m, height_agl_m,
                    site_type, status, hardware_preset, owner,
                    is_public_land, notes, privacy_fuzzed, source_url, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(site_id) DO UPDATE SET
                    name = excluded.name,
                    lat = excluded.lat,
                    lon = excluded.lon,
                    elevation_m = excluded.elevation_m,
                    height_agl_m = excluded.height_agl_m,
                    site_type = excluded.site_type,
                    status = excluded.status,
                    hardware_preset = excluded.hardware_preset,
                    notes = excluded.notes,
                    source_url = excluded.source_url,
                    updated_at = excluded.updated_at;
                """,
                (
                    node.site_id,
                    node.name,
                    node.coordinate.lat,
                    node.coordinate.lon,
                    node.coordinate.elevation_m,
                    node.height_agl_m,
                    node.site_type.value,
                    node.status.value,
                    node.hardware_preset,
                    node.owner,
                    1 if node.is_public_land else 0,
                    node.notes,
                    1 if node.privacy_fuzzed else 0,
                    node.source_url,
                    now_iso,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM mesh_nodes WHERE site_id = ?;", (node.site_id,)
            ).fetchone()
            return Result.success(self._row_to_node(row))

    def reconcile_dismantled_sites(self, dismantled_ids: Sequence[str]) -> int:
        """Mark registered nodes as dismantled if found in dismantled_ids.

        Runs UPDATE mesh_nodes SET status = 'dismantled', updated_at = ?
        WHERE site_id = ? AND status != 'dismantled' for each id.

        Returns:
            Total count of updated rows.
        """
        if not dismantled_ids:
            return 0
        now_iso = _utc_now_iso()
        total_updated = 0
        with self._connect() as conn:
            for s_id in dismantled_ids:
                cur = conn.execute(
                    """
                    UPDATE mesh_nodes
                    SET status = 'dismantled', updated_at = ?
                    WHERE site_id = ? AND status != 'dismantled';
                    """,
                    (now_iso, s_id),
                )
                total_updated += cur.rowcount
            conn.commit()
        return total_updated

    def export_snapshot(self, fuzz_private_nodes: bool = True) -> Dict[str, Any]:
        """Export JSON-serializable club mesh state snapshot, optionally fuzzing non-public nodes."""
        nodes = self.list_nodes()
        prefs = self.get_preferences()
        exported_nodes: List[Dict[str, Any]] = []

        for node in nodes:
            if fuzz_private_nodes and not node.is_public_land:
                fuzzed_coord = _fuzz_coordinate(node.coordinate)
                node_out = node.model_copy(
                    update={"coordinate": fuzzed_coord, "privacy_fuzzed": True}
                )
            else:
                node_out = node
            exported_nodes.append(node_out.model_dump(mode="json"))

        return {
            "schema_version": "1.0",
            "exported_at": _utc_now_iso(),
            "fuzz_private_nodes": fuzz_private_nodes,
            "region": prefs.last_region,
            "nodes": exported_nodes,
        }

    def import_snapshot(self, payload: Dict[str, Any]) -> Result[int]:
        """Import club mesh state snapshot into SQLite registry."""
        if not isinstance(payload, dict) or "nodes" not in payload:
            return Result.fail(
                code="INVALID_SNAPSHOT_PAYLOAD",
                message="Snapshot payload must be a dictionary containing a 'nodes' list.",
            )

        raw_nodes = payload.get("nodes")
        if not isinstance(raw_nodes, list):
            return Result.fail(
                code="INVALID_SNAPSHOT_NODES",
                message="Snapshot 'nodes' field must be a list of serialized RegisteredNode objects.",
            )

        imported_count = 0
        try:
            with self._connect() as conn:
                for raw in raw_nodes:
                    node = RegisteredNode.model_validate(raw)
                    conn.execute(
                        """
                        INSERT INTO mesh_nodes (
                            site_id, name, lat, lon, elevation_m, height_agl_m,
                            site_type, status, hardware_preset, owner,
                            is_public_land, notes, privacy_fuzzed, source_url, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(site_id) DO UPDATE SET
                            name = excluded.name,
                            lat = excluded.lat,
                            lon = excluded.lon,
                            elevation_m = excluded.elevation_m,
                            height_agl_m = excluded.height_agl_m,
                            site_type = excluded.site_type,
                            status = excluded.status,
                            hardware_preset = excluded.hardware_preset,
                            owner = excluded.owner,
                            is_public_land = excluded.is_public_land,
                            notes = excluded.notes,
                            privacy_fuzzed = excluded.privacy_fuzzed,
                            source_url = excluded.source_url,
                            updated_at = excluded.updated_at;
                        """,
                        (
                            node.site_id,
                            node.name,
                            node.coordinate.lat,
                            node.coordinate.lon,
                            node.coordinate.elevation_m,
                            node.height_agl_m,
                            node.site_type.value,
                            node.status.value,
                            node.hardware_preset,
                            node.owner,
                            1 if node.is_public_land else 0,
                            node.notes,
                            1 if node.privacy_fuzzed else 0,
                            node.source_url,
                            node.updated_at,
                        ),
                    )
                    imported_count += 1
                conn.commit()
            return Result.success(imported_count)
        except Exception as exc:
            return Result.fail(
                code="SNAPSHOT_IMPORT_ERROR",
                message=f"Failed to import snapshot: {exc}",
            )
