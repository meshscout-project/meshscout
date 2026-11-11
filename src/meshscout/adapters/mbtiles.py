"""Offline MBTiles Map Archive Adapter for MeshScout.

Provides read-only access to standard MBTiles 1.3 SQLite archives for offline cartographic
tile rendering, adhering to TMS coordinate transformations and zero-runtime dependency requirements.
"""

from __future__ import annotations

import html
from pathlib import Path
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Union


class MBTilesReader:
    """Read-only SQLite adapter for MBTiles 1.3 raster and vector tile archives.

    Transforms standard slippy map XYZ coordinates to MBTiles TMS tile_row conventions:
    tile_row = (1 << z) - 1 - y
    """

    def __init__(self, mbtiles_path: Union[str, Path]) -> None:
        self._local = threading.local()
        self._connections: List[sqlite3.Connection] = []
        self._lock = threading.Lock()
        self._closed = False

        self.path = Path(mbtiles_path).resolve()
        if not self.path.is_file():
            raise FileNotFoundError(f"MBTiles archive not found: {self.path}")
        self._uri = f"file:{self.path.as_posix()}?mode=ro"
        # Verify connection can be opened
        self._get_connection()

    def _get_connection(self) -> sqlite3.Connection:
        if self._closed:
            raise RuntimeError("MBTiles connection is closed.")
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._uri, uri=True, check_same_thread=False)
            self._local.conn = conn
            with self._lock:
                self._connections.append(conn)
        return conn

    @property
    def _conn(self) -> Optional[sqlite3.Connection]:
        if self._closed:
            return None
        return self._get_connection()

    def get_metadata(self) -> Dict[str, str]:
        """Query metadata key-value pairs stored in the archive."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name, value FROM metadata")
        return {str(row[0]): str(row[1]) for row in cursor.fetchall()}

    def has_tile(self, z: int, x: int, y: int) -> bool:
        """Check whether a tile exists at zoom z and slippy coordinates (x, y)."""
        conn = self._get_connection()
        tile_row = (1 << z) - 1 - y
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM tiles WHERE zoom_level = ? AND tile_column = ? AND tile_row = ?",
            (z, x, tile_row),
        )
        return cursor.fetchone() is not None

    def get_tile_bytes(self, z: int, x: int, y: int) -> Optional[bytes]:
        """Retrieve raw tile binary data (typically PNG or PBF) at zoom z and slippy coordinates (x, y)."""
        conn = self._get_connection()
        tile_row = (1 << z) - 1 - y
        cursor = conn.cursor()
        cursor.execute(
            "SELECT tile_data FROM tiles WHERE zoom_level = ? AND tile_column = ? AND tile_row = ?",
            (z, x, tile_row),
        )
        row = cursor.fetchone()
        if row is not None and row[0] is not None:
            return bytes(row[0])
        return None

    def close(self) -> None:
        """Close the SQLite connection(s)."""
        self._closed = True
        lock = getattr(self, "_lock", None)
        if lock is not None:
            with lock:
                conns = getattr(self, "_connections", [])
                for conn in conns:
                    try:
                        conn.close()
                    except Exception:
                        pass
                conns.clear()
        local = getattr(self, "_local", None)
        if local is not None and hasattr(local, "conn"):
            local.conn = None

    def __del__(self) -> None:
        self.close()

    def __enter__(self) -> "MBTilesReader":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()


def generate_boundary_tile_svg(region_label: str = "OFFLINE BOUNDARY") -> bytes:
    """Generate brutalist dark slate/emerald SVG bytes (256x256) for missing or out-of-bounds offline tiles."""
    safe_label = html.escape(region_label)
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">\n'
        '<rect width="256" height="256" fill="#141917" stroke="#25332c" stroke-width="2"/>\n'
        '<text x="128" y="120" fill="#4ade80" font-family="monospace" font-size="12" font-weight="bold" text-anchor="middle">OFFLINE BOUNDARY</text>\n'
        f'<text x="128" y="145" fill="#94a3b8" font-family="monospace" font-size="10" text-anchor="middle">{safe_label}</text>\n'
        '<text x="128" y="170" fill="#64748b" font-family="monospace" font-size="9" text-anchor="middle">Switch Region Pack</text>\n'
        '</svg>'
    )
    return svg.encode("utf-8")
