"""Unified live telemetry SQLite cache adapter for Meshtastic and MeshCore/Reticulum nodes.

Provides persistent caching, spatial bounding box queries with regional buffering,
protocol filtering, and sample fixture seeding for disaster response and live RF mesh monitoring.
Zero runtime dependencies beyond pydantic>=2.0.0 and standard library.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from meshscout.core.contracts import Coordinate, RegionalBounds


class TelemetryNode(BaseModel):
    """Pydantic v2 schema for live or cached RF mesh telemetry nodes."""

    node_id: str = Field(..., min_length=1, description="Unique node identifier or hex MAC/hash")
    protocol: str = Field(default="meshtastic", description="Mesh protocol ('meshtastic' or 'meshcore')")
    short_name: str = Field(..., description="Short broadcast name / callsign")
    long_name: str = Field(..., description="Full descriptive name or beacon title")
    coordinate: Coordinate = Field(..., description="Geodetic position and elevation")
    battery_pct: Optional[float] = Field(default=None, description="Battery state of charge percentage")
    voltage: Optional[float] = Field(default=None, description="Node battery or bus voltage")
    snr_db: Optional[float] = Field(default=None, description="Signal-to-noise ratio in decibels")
    rssi_dbm: Optional[float] = Field(default=None, description="Received signal strength indicator in dBm")
    hops_away: Optional[int] = Field(default=None, description="Mesh hop count from listening gateway")
    hardware_model: Optional[str] = Field(default=None, description="Hardware radio architecture or device model")
    channel: Optional[str] = Field(default=None, description="Active primary channel or frequency preset")
    last_heard_iso: str = Field(..., description="ISO 8601 UTC timestamp of last received telemetry packet")
    is_synthetic: bool = Field(default=False, description="Flag indicating synthetic or simulated node telemetry")
    raw_payload: Optional[str] = Field(default=None, description="Raw JSON or hex encoded payload string")

    @field_validator("protocol")
    @classmethod
    def normalize_protocol(cls, v: str) -> str:
        """Normalize protocol identifier to lowercase."""
        return v.strip().lower()

    @model_validator(mode="before")
    @classmethod
    def assemble_coordinate(cls, data: Any) -> Any:
        """Allow flat lat, lon, elevation_m in dictionary inputs to construct coordinate."""
        if isinstance(data, dict):
            if "coordinate" not in data and "lat" in data and "lon" in data:
                data = dict(data)
                data["coordinate"] = Coordinate(
                    lat=float(data["lat"]),
                    lon=float(data["lon"]),
                    elevation_m=float(data.get("elevation_m", 0.0)),
                )
        return data

    @property
    def lat(self) -> float:
        """Convenience property for latitude."""
        return self.coordinate.lat

    @property
    def lon(self) -> float:
        """Convenience property for longitude."""
        return self.coordinate.lon

    @property
    def elevation_m(self) -> float:
        """Convenience property for elevation in meters."""
        return self.coordinate.elevation_m


class UnifiedTelemetryCache:
    """Zero-dependency SQLite-backed unified telemetry cache for Meshtastic and MeshCore nodes."""

    def __init__(self, db_path: Optional[Union[str, Path]] = None) -> None:
        """Initialize SQLite database connection and verify table schema.

        Args:
            db_path: Path to SQLite database file. Defaults to ~/.meshscout/telemetry_cache.db.
                     Use ':memory:' for transient in-memory storage.
        """
        if db_path is None:
            self.db_path = Path.home() / ".meshscout" / "telemetry_cache.db"
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db_uri = str(self.db_path)
        elif str(db_path) == ":memory:":
            self.db_path = Path(":memory:")
            self._db_uri = ":memory:"
        else:
            self.db_path = Path(db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db_uri = str(self.db_path)

        self._conn: Optional[sqlite3.Connection] = sqlite3.connect(self._db_uri, check_same_thread=False)
        self._init_db()

    def _init_db(self) -> None:
        """Create schema, primary keys, and spatial/protocol indexes."""
        if not self._conn:
            return
        cursor = self._conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS telemetry_nodes (
                node_id TEXT PRIMARY KEY,
                protocol TEXT NOT NULL,
                short_name TEXT NOT NULL,
                long_name TEXT NOT NULL,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                elevation_m REAL NOT NULL,
                battery_pct REAL,
                voltage REAL,
                snr_db REAL,
                rssi_dbm REAL,
                hops_away INTEGER,
                hardware_model TEXT,
                channel TEXT,
                last_heard_iso TEXT NOT NULL,
                is_synthetic INTEGER NOT NULL DEFAULT 0,
                raw_payload TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_lat_lon ON telemetry_nodes (lat, lon);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_protocol ON telemetry_nodes (protocol);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_last_heard ON telemetry_nodes (last_heard_iso);")
        self._conn.commit()

    @staticmethod
    def _row_to_node(row: Tuple[Any, ...]) -> TelemetryNode:
        """Convert database tuple row into TelemetryNode model."""
        return TelemetryNode(
            node_id=row[0],
            protocol=row[1],
            short_name=row[2],
            long_name=row[3],
            coordinate=Coordinate(lat=row[4], lon=row[5], elevation_m=row[6]),
            battery_pct=row[7],
            voltage=row[8],
            snr_db=row[9],
            rssi_dbm=row[10],
            hops_away=row[11],
            hardware_model=row[12],
            channel=row[13],
            last_heard_iso=row[14],
            is_synthetic=bool(row[15]),
            raw_payload=row[16],
        )

    def upsert_node(self, node: TelemetryNode) -> bool:
        """Insert or update a telemetry node in the cache.

        Args:
            node: Validated TelemetryNode instance.

        Returns:
            True upon successful upsert.
        """
        if not self._conn:
            raise RuntimeError("Database connection is closed.")

        sql = """
            INSERT INTO telemetry_nodes (
                node_id, protocol, short_name, long_name,
                lat, lon, elevation_m, battery_pct, voltage,
                snr_db, rssi_dbm, hops_away, hardware_model,
                channel, last_heard_iso, is_synthetic, raw_payload,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(node_id) DO UPDATE SET
                protocol = excluded.protocol,
                short_name = excluded.short_name,
                long_name = excluded.long_name,
                lat = excluded.lat,
                lon = excluded.lon,
                elevation_m = excluded.elevation_m,
                battery_pct = excluded.battery_pct,
                voltage = excluded.voltage,
                snr_db = excluded.snr_db,
                rssi_dbm = excluded.rssi_dbm,
                hops_away = excluded.hops_away,
                hardware_model = excluded.hardware_model,
                channel = excluded.channel,
                last_heard_iso = excluded.last_heard_iso,
                is_synthetic = excluded.is_synthetic,
                raw_payload = excluded.raw_payload,
                updated_at = CURRENT_TIMESTAMP
        """
        params = (
            node.node_id,
            node.protocol,
            node.short_name,
            node.long_name,
            node.coordinate.lat,
            node.coordinate.lon,
            node.coordinate.elevation_m,
            node.battery_pct,
            node.voltage,
            node.snr_db,
            node.rssi_dbm,
            node.hops_away,
            node.hardware_model,
            node.channel,
            node.last_heard_iso,
            1 if node.is_synthetic else 0,
            node.raw_payload,
        )
        self._conn.execute(sql, params)
        self._conn.commit()
        return True

    def bulk_upsert_nodes(self, nodes: Sequence[TelemetryNode]) -> int:
        """Bulk insert or update a sequence of telemetry nodes.

        Args:
            nodes: Sequence of TelemetryNode instances.

        Returns:
            Number of nodes processed.
        """
        if not self._conn:
            raise RuntimeError("Database connection is closed.")
        if not nodes:
            return 0

        sql = """
            INSERT INTO telemetry_nodes (
                node_id, protocol, short_name, long_name,
                lat, lon, elevation_m, battery_pct, voltage,
                snr_db, rssi_dbm, hops_away, hardware_model,
                channel, last_heard_iso, is_synthetic, raw_payload,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(node_id) DO UPDATE SET
                protocol = excluded.protocol,
                short_name = excluded.short_name,
                long_name = excluded.long_name,
                lat = excluded.lat,
                lon = excluded.lon,
                elevation_m = excluded.elevation_m,
                battery_pct = excluded.battery_pct,
                voltage = excluded.voltage,
                snr_db = excluded.snr_db,
                rssi_dbm = excluded.rssi_dbm,
                hops_away = excluded.hops_away,
                hardware_model = excluded.hardware_model,
                channel = excluded.channel,
                last_heard_iso = excluded.last_heard_iso,
                is_synthetic = excluded.is_synthetic,
                raw_payload = excluded.raw_payload,
                updated_at = CURRENT_TIMESTAMP
        """
        param_list = [
            (
                node.node_id,
                node.protocol,
                node.short_name,
                node.long_name,
                node.coordinate.lat,
                node.coordinate.lon,
                node.coordinate.elevation_m,
                node.battery_pct,
                node.voltage,
                node.snr_db,
                node.rssi_dbm,
                node.hops_away,
                node.hardware_model,
                node.channel,
                node.last_heard_iso,
                1 if node.is_synthetic else 0,
                node.raw_payload,
            )
            for node in nodes
        ]
        with self._conn:
            self._conn.executemany(sql, param_list)
        return len(nodes)

    def get_node(self, node_id: str) -> Optional[TelemetryNode]:
        """Retrieve a single node by its unique node_id.

        Args:
            node_id: Node identifier string.

        Returns:
            TelemetryNode instance if found, None otherwise.
        """
        if not self._conn:
            raise RuntimeError("Database connection is closed.")

        query = """
            SELECT
                node_id, protocol, short_name, long_name,
                lat, lon, elevation_m, battery_pct, voltage,
                snr_db, rssi_dbm, hops_away, hardware_model,
                channel, last_heard_iso, is_synthetic, raw_payload
            FROM telemetry_nodes
            WHERE node_id = ?
        """
        cursor = self._conn.execute(query, (node_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_node(row)

    def query_nodes(
        self,
        bounds: Optional[RegionalBounds] = None,
        state_code: Optional[str] = None,
        buffer_km: float = 20.0,
        protocol: Optional[str] = None,
        limit: int = 500,
    ) -> List[TelemetryNode]:
        """Query active telemetry nodes filtered by geographic bounds and protocol.

        Args:
            bounds: Explicit bounding box. If None and state_code is provided,
                    the state's buffered boundary box is calculated.
            state_code: State/province code (e.g. 'VT', 'NH', 'CA_QC') to resolve if bounds is None.
            buffer_km: Outward buffer expansion in kilometers (default 20.0 km).
            protocol: Optional protocol filter ('meshtastic' or 'meshcore').
            limit: Maximum number of records to return (default 500).

        Returns:
            List of matching TelemetryNode objects sorted by last_heard_iso descending.
        """
        if not self._conn:
            raise RuntimeError("Database connection is closed.")

        target_bounds = bounds
        if target_bounds is None and state_code is not None:
            from meshscout.core.staging import calculate_buffered_region_bounds
            target_bounds = calculate_buffered_region_bounds(state_code, buffer_km=buffer_km)

        where_clauses: List[str] = []
        params: List[Any] = []

        if target_bounds is not None:
            where_clauses.append("lat >= ? AND lat <= ? AND lon >= ? AND lon <= ?")
            params.extend([target_bounds.min_lat, target_bounds.max_lat, target_bounds.min_lon, target_bounds.max_lon])

        if protocol is not None:
            where_clauses.append("LOWER(protocol) = ?")
            params.append(protocol.strip().lower())

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        query = f"""
            SELECT
                node_id, protocol, short_name, long_name,
                lat, lon, elevation_m, battery_pct, voltage,
                snr_db, rssi_dbm, hops_away, hardware_model,
                channel, last_heard_iso, is_synthetic, raw_payload
            FROM telemetry_nodes
            {where_sql}
            ORDER BY last_heard_iso DESC
            LIMIT ?
        """
        params.append(limit)

        cursor = self._conn.execute(query, params)
        rows = cursor.fetchall()
        return [self._row_to_node(r) for r in rows]

    def count_nodes_by_protocol(
        self,
        bounds: Optional[RegionalBounds] = None,
        state_code: Optional[str] = None,
        buffer_km: float = 20.0,
    ) -> Dict[str, int]:
        """Aggregate node counts grouped by mesh protocol within the spatial region.

        Args:
            bounds: Explicit bounding box.
            state_code: Optional state code to derive buffered bounds.
            buffer_km: Outward buffer expansion in kilometers.

        Returns:
            Dictionary mapping protocol names to integer counts.
        """
        if not self._conn:
            raise RuntimeError("Database connection is closed.")

        target_bounds = bounds
        if target_bounds is None and state_code is not None:
            from meshscout.core.staging import calculate_buffered_region_bounds
            target_bounds = calculate_buffered_region_bounds(state_code, buffer_km=buffer_km)

        where_clauses: List[str] = []
        params: List[Any] = []

        if target_bounds is not None:
            where_clauses.append("lat >= ? AND lat <= ? AND lon >= ? AND lon <= ?")
            params.extend([target_bounds.min_lat, target_bounds.max_lat, target_bounds.min_lon, target_bounds.max_lon])

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        query = f"""
            SELECT protocol, COUNT(*)
            FROM telemetry_nodes
            {where_sql}
            GROUP BY protocol
        """
        cursor = self._conn.execute(query, params)
        rows = cursor.fetchall()
        return {row[0]: row[1] for row in rows}

    def seed_from_sample_fixture(self, fixture_path: Optional[Union[str, Path]] = None) -> int:
        """Seed cache from sample JSON fixture.

        Args:
            fixture_path: Path to fixture file. Defaults to regional_live_telemetry_sample.json.

        Returns:
            Number of nodes seeded.
        """
        if fixture_path is None:
            resolved_path = Path(__file__).resolve().parent.parent.parent.parent / "fixtures" / "regional_live_telemetry_sample.json"
        else:
            resolved_path = Path(fixture_path)

        if not resolved_path.exists():
            raise FileNotFoundError(f"Fixture not found at {resolved_path}")

        with open(resolved_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            raw_nodes = data
        elif isinstance(data, dict):
            raw_nodes = data.get("nodes", data.get("telemetry_nodes", []))
        else:
            raise ValueError(f"Invalid fixture format in {resolved_path}: expected JSON list or dict with 'nodes'")

        nodes = [TelemetryNode.model_validate(item) for item in raw_nodes]
        return self.bulk_upsert_nodes(nodes)

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            finally:
                self._conn = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def __enter__(self) -> UnifiedTelemetryCache:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
