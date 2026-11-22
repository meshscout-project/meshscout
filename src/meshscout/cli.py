"""MeshScout Command-Line Interface (CLI) entrypoint.

Provides subcommands for offline-first regional repeater scouting (`scout`),
point-to-point link budget evaluation (`link`), site feasibility & desense
inspection (`feasibility`), and launching the MCP stdio server (`mcp`).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Optional, Sequence, Tuple

from meshscout.cli_tower_helpers import run_towers_subcommand
from meshscout.core.contracts import Coordinate
from meshscout.core.presets import CLIENT_ENVIRONMENT_PROFILES, build_radio_config
from meshscout.core.registry import LivingMeshRegistry, evaluate_home_node_reach
from meshscout.commands import (
    compute_channel_slot,
    evaluate_backbone_resilience,
    evaluate_link_budget,
    inspect_site_feasibility,
    load_regional_fixtures,
    scout_repeater_sites,
)
from meshscout.core.viewshed import _synthetic_vermont_elevation_fn
from meshscout.mcp_server import (
    MeshScoutMCPServer,
    create_fastmcp_app,
)


def _parse_coord_triplet(raw: str) -> Tuple[float, float, float]:
    """Parse 'LAT,LON,ELEV' or 'LAT,LON' into (lat, lon, elev_m)."""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) == 2:
        return (float(parts[0]), float(parts[1]), 100.0)
    if len(parts) == 3:
        return (float(parts[0]), float(parts[1]), float(parts[2]))
    raise ValueError(
        f"Expected coordinate format 'LAT,LON,ELEV' (e.g. '44.5437,-72.8143,1339.0'), got '{raw}'"
    )


def create_fallback_sse_app(
    server: Optional[MeshScoutMCPServer] = None,
    allowed_origins: Optional[Sequence[str]] = None,
    auth_token: Optional[str] = None,
) -> Any:
    """Create a fallback Starlette/FastAPI ASGI application providing SSE and messages endpoints."""
    try:
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import Response, StreamingResponse
        from starlette.routing import Route
    except ImportError:
        try:
            from fastapi import FastAPI as Starlette, Request  # type: ignore[import-not-found,no-redef]
            from fastapi.responses import Response, StreamingResponse  # type: ignore[import-not-found,no-redef]
            from starlette.routing import Route  # type: ignore[import-not-found,no-redef]
        except ImportError as exc:
            raise ImportError(
                "Fallback SSE server requires 'starlette' or 'fastapi' and 'uvicorn' installed."
            ) from exc

    import asyncio
    import os
    import uuid

    srv = server or MeshScoutMCPServer()
    sessions: dict[str, asyncio.Queue] = {}
    effective_token = auth_token or os.environ.get("MESHSCOUT_AUTH_TOKEN")
    effective_origins = set(allowed_origins) if allowed_origins else None

    def _check_auth_and_origin(request: Request) -> Optional[Response]:
        if effective_origins:
            origin = request.headers.get("origin")
            if origin and origin not in effective_origins:
                return Response(status_code=403, content="Forbidden: Origin not allowed")
        if effective_token:
            auth_header = request.headers.get("authorization", "")
            token = None
            if auth_header.startswith("Bearer "):
                token = auth_header[7:].strip()
            elif "token" in request.query_params:
                token = request.query_params["token"].strip()
            if not token or token != effective_token:
                return Response(status_code=401, content="Unauthorized: Invalid authentication token")
        return None

    async def handle_sse(request: Request) -> Response:
        auth_err = _check_auth_and_origin(request)
        if auth_err is not None:
            return auth_err

        session_id = str(uuid.uuid4())
        queue: asyncio.Queue = asyncio.Queue()
        sessions[session_id] = queue

        async def event_generator():
            yield f"event: endpoint\r\ndata: /messages?session_id={session_id}\r\n\r\n"
            try:
                while True:
                    msg = await queue.get()
                    if msg is None:
                        break
                    yield f"event: message\r\ndata: {msg}\r\n\r\n"
            except (asyncio.CancelledError, GeneratorExit):
                pass
            finally:
                sessions.pop(session_id, None)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    async def handle_messages(request: Request) -> Response:
        auth_err = _check_auth_and_origin(request)
        if auth_err is not None:
            return auth_err

        session_id = request.query_params.get("session_id")
        try:
            body = await request.json()
        except Exception:
            return Response(status_code=400, content="Invalid JSON payload")

        result = srv.handle_request(body)
        if result is not None:
            raw_resp = json.dumps(result)
            if session_id and session_id in sessions:
                await sessions[session_id].put(raw_resp)
                return Response(status_code=202, content="Accepted")
            return Response(
                status_code=200,
                content=raw_resp,
                media_type="application/json",
            )
        return Response(status_code=202, content="Accepted")

    routes = [
        Route("/sse", endpoint=handle_sse, methods=["GET"]),
        Route("/messages", endpoint=handle_messages, methods=["POST"]),
    ]
    return Starlette(routes=routes)


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argparse parser for MeshScout."""
    parser = argparse.ArgumentParser(
        prog="meshscout",
        description="Offline-first high-site and topology planning engine for LoRa/MeshCore disaster networks.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. scout subcommand
    p_scout = subparsers.add_parser(
        "scout",
        help="Scout and optimize regional repeater sites using minimum set-cover.",
    )
    p_scout.add_argument(
        "--region",
        default="vt_chittenden",
        help="Target region identifier (default: vt_chittenden)",
    )
    p_scout.add_argument(
        "--min-coverage",
        type=float,
        default=0.90,
        help="Target weighted coverage fraction in (0.0, 1.0] (default: 0.90)",
    )
    p_scout.add_argument(
        "--max-repeaters",
        type=int,
        default=5,
        help="Maximum number of repeaters to select (default: 5)",
    )
    p_scout.add_argument(
        "--delay",
        type=float,
        default=None,
        help="Fixed egress jitter delay in seconds (sets both min-delay and max-delay)",
    )
    p_scout.add_argument(
        "--min-delay",
        type=float,
        default=0.5,
        help="Minimum egress jitter delay in seconds for online API requests (default: 0.5)",
    )
    p_scout.add_argument(
        "--max-delay",
        type=float,
        default=1.5,
        help="Maximum egress jitter delay in seconds for online API requests (default: 1.5)",
    )
    p_scout.add_argument(
        "--no-delay",
        action="store_true",
        help="Disable rate-limiting delay for offline/cached local execution (ADR-024)",
    )
    p_scout.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Emit structured JSON output",
    )

    # 2. link subcommand
    p_link = subparsers.add_parser(
        "link",
        help="Evaluate point-to-point Fresnel clearance and ITM link budget.",
    )
    p_link.add_argument(
        "--source",
        required=True,
        help="Source coordinate as 'LAT,LON,ELEV_M' (e.g. '44.5437,-72.8143,1339.0')",
    )
    p_link.add_argument(
        "--target",
        required=True,
        help="Target coordinate as 'LAT,LON,ELEV_M' (e.g. '44.4900,-73.1100,105.0')",
    )
    p_link.add_argument(
        "--freq",
        type=float,
        default=915.0,
        help="Carrier frequency in MHz (default: 915.0)",
    )
    p_link.add_argument(
        "--tx-power",
        type=float,
        default=20.0,
        help="Transmit power in dBm (default: 20.0)",
    )
    p_link.add_argument(
        "--mode",
        choices=["client", "backhaul"],
        default=None,
        help="Dual-mode evaluation ('client' applies client clutter; 'backhaul' enforces 0.0 dB clutter)",
    )
    p_link.add_argument(
        "--source-preset",
        default=None,
        help="Hardware preset ID for source transceiver (default: STATION_G2_BACKBONE in dual-mode)",
    )
    p_link.add_argument(
        "--target-preset",
        default=None,
        help="Hardware preset ID for target transceiver (default: SENSECAP_T1000E in client mode, RAK4631_SOLAR in backhaul mode)",
    )
    p_link.add_argument(
        "--client-env",
        type=str.upper,
        choices=list(CLIENT_ENVIRONMENT_PROFILES.keys()),
        default=None,
        help="Client operating environment clutter profile (ignored with 0.0 dB clutter in backhaul mode)",
    )
    p_link.add_argument(
        "--protocol",
        default="MESHTASTIC_LONGFAST",
        help="Protocol modulation profile ID (default: MESHTASTIC_LONGFAST)",
    )
    p_link.add_argument(
        "--season",
        default="SUMMER_FOLIAGE",
        help="Seasonal foliage attenuation profile ID (default: SUMMER_FOLIAGE)",
    )
    p_link.add_argument(
        "--source-noise-db",
        type=float,
        default=0.0,
        help="Local RF noise floor degradation penalty at source site in dB (default: 0.0)",
    )
    p_link.add_argument(
        "--target-noise-db",
        type=float,
        default=0.0,
        help="Local RF noise floor degradation penalty at target site in dB (default: 0.0)",
    )
    p_link.add_argument(
        "--no-delay",
        action="store_true",
        help="Run in instant offline mode without egress delay",
    )
    p_link.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Emit structured JSON output",
    )

    # 2b. reach subcommand
    p_reach = subparsers.add_parser(
        "reach",
        help="Evaluate 360-degree client uplink and downlink reachability to regional towers.",
    )
    p_reach.add_argument(
        "--lat",
        type=float,
        default=None,
        help="Client or home node latitude in decimal degrees",
    )
    p_reach.add_argument(
        "--lon",
        type=float,
        default=None,
        help="Client or home node longitude in decimal degrees",
    )
    p_reach.add_argument(
        "--elev-m",
        type=float,
        default=None,
        help="Optional ground elevation in meters above sea level",
    )
    p_reach.add_argument(
        "--agl-m",
        type=float,
        default=None,
        help="Optional antenna height above ground in meters",
    )
    p_reach.add_argument(
        "--client-preset",
        default="SENSECAP_T1000E",
        help="Client hardware preset ID (default: SENSECAP_T1000E)",
    )
    p_reach.add_argument(
        "--client-env",
        type=str.upper,
        choices=list(CLIENT_ENVIRONMENT_PROFILES.keys()),
        default="OUTDOOR_CLEAR",
        help="Client operating environment clutter profile (default: OUTDOOR_CLEAR)",
    )
    p_reach.add_argument(
        "--protocol",
        default="MESHTASTIC_LONGFAST",
        help="Protocol modulation profile ID (default: MESHTASTIC_LONGFAST)",
    )
    p_reach.add_argument(
        "--season",
        default="SUMMER_FOLIAGE",
        help="Seasonal foliage attenuation profile ID (default: SUMMER_FOLIAGE)",
    )
    p_reach.add_argument(
        "--db-path",
        default=None,
        help="Optional path to SQLite mesh_state.db",
    )
    p_reach.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Emit structured JSON output",
    )

    # 3. feasibility subcommand
    p_feas = subparsers.add_parser(
        "feasibility",
        help="Inspect a candidate site's co-location desense risk and civic viability.",
    )
    p_feas.add_argument(
        "--site-id",
        required=True,
        help="Candidate site ID (e.g. VT-PEAK-01 or VT-VCGI-WT-001)",
    )
    p_feas.add_argument(
        "--emitter-watts",
        type=float,
        default=0.0,
        help="Co-located 850-900 MHz transmitter ERP in Watts (default: 0.0)",
    )
    p_feas.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Emit structured JSON output",
    )

    # 4. mcp subcommand
    p_mcp = subparsers.add_parser(
        "mcp",
        help="Start the MeshScout Model Context Protocol (MCP) server.",
    )
    p_mcp.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="MCP transport protocol ('stdio' or 'sse', default: 'stdio')",
    )
    p_mcp.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind host address for SSE transport (default: 127.0.0.1)",
    )
    p_mcp.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Bind TCP port for SSE transport (default: 8000)",
    )
    p_mcp.add_argument(
        "--stdio",
        action="store_true",
        default=False,
        help="Run MCP server over standard input/output (alias for --transport stdio)",
    )

    # 5. serve subcommand
    p_serve = subparsers.add_parser(
        "serve",
        help="Launch the interactive MeshScout Web Workbench (FastAPI + Uvicorn).",
    )
    p_serve.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind host address (default: 127.0.0.1, use 0.0.0.0 for Docker/LAN)",
    )
    p_serve.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Bind TCP port (default: 8080)",
    )
    p_serve.add_argument(
        "--db-path",
        default=None,
        help="Optional path to SQLite mesh_state.db (default: ~/.meshscout/mesh_state.db)",
    )

    # 6. stage subcommand
    p_stage = subparsers.add_parser(
        "stage",
        help="Stage offline regional field kit containing MBTiles basemap, DEM rasters, and living mesh database.",
    )
    p_stage.add_argument(
        "--region",
        default="VT",
        help="Target state or regional identifier (default: VT)",
    )
    p_stage.add_argument(
        "--buffer-km",
        type=float,
        default=20.0,
        help="Geographic boundary expansion buffer in kilometers (default: 20.0)",
    )
    p_stage.add_argument(
        "--output-dir",
        default="./MeshScout-Field-Kit",
        help="Destination directory for staged field kit assets (default: ./MeshScout-Field-Kit)",
    )
    p_stage.add_argument(
        "--min-zoom",
        type=int,
        default=7,
        help="Minimum offline tile zoom level (default: 7)",
    )
    p_stage.add_argument(
        "--max-zoom",
        type=int,
        default=12,
        help="Maximum offline tile zoom level (default: 12)",
    )
    p_stage.add_argument(
        "--no-dem",
        action="store_true",
        help="Exclude digital elevation model (DEM) rasters from field kit",
    )
    p_stage.add_argument(
        "--dry-run",
        action="store_true",
        help="Calculate tile counts and bounding box without downloading or writing files to disk",
    )
    p_stage.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Emit structured JSON output",
    )

    # 7. ingest-towers subcommand
    p_ingest = subparsers.add_parser(
        "ingest-towers",
        help="Ingest and index civic, FCC ASR, and Canadian ISED tower infrastructure into UnifiedTowerRegistry.",
    )
    p_ingest.add_argument(
        "--source",
        choices=["civic", "fcc", "ised", "all"],
        default="all",
        help="Tower infrastructure data source ('civic', 'fcc', 'ised', or 'all', default: 'all')",
    )
    p_ingest.add_argument(
        "--region",
        default=None,
        help="Optional regional bounding filter (e.g. 'VT', 'NH', 'NY', 'CA_QC', 'ME', or 'vt_chittenden')",
    )
    p_ingest.add_argument(
        "--ant-path",
        default=None,
        help="Optional path to FCC ANT/CO file",
    )
    p_ingest.add_argument(
        "--own-path",
        default=None,
        help="Optional path to FCC OWN/EN file",
    )
    p_ingest.add_argument(
        "--ised-path",
        default=None,
        help="Optional path to Canadian ISED SMS file",
    )
    p_ingest.add_argument(
        "--civic-catalog",
        default=None,
        help="Optional path to civic high-sites catalog JSON (defaults to fixtures/civic_highsites_catalog.json)",
    )
    p_ingest.add_argument(
        "--db-path",
        default=None,
        help="Optional path to SQLite towers DB (defaults to ~/.meshscout/towers.db)",
    )
    p_ingest.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Batch commit size for database insertions (default: 1000)",
    )
    p_ingest.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Emit structured JSON output",
    )

    # 8. sync-telemetry subcommand
    p_sync = subparsers.add_parser(
        "sync-telemetry",
        help="Sync live Meshtastic and MeshCore telemetry into regional offline cache.",
    )
    p_sync.add_argument(
        "--region",
        default="VT",
        help="Target region or state code (default: VT)",
    )
    p_sync.add_argument(
        "--buffer-km",
        type=float,
        default=20.0,
        help="Regional cross-border buffer radius in kilometers (default: 20.0)",
    )
    p_sync.add_argument(
        "--db-path",
        default=None,
        help="Optional SQLite DB path (defaults to ~/.meshscout/telemetry_cache.db)",
    )
    p_sync.add_argument(
        "--source",
        choices=["sample", "broker"],
        default="sample",
        help="Telemetry data source ('sample' or 'broker', default: 'sample')",
    )
    p_sync.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Emit structured JSON output",
    )

    # 9. regions subcommand
    p_regions = subparsers.add_parser(
        "regions",
        help="Manage regional tower data packs (list, install, update, remove).",
    )
    p_regions_subs = p_regions.add_subparsers(dest="regions_action", required=True)

    # regions list [--available] [--json] [--db-path DB_PATH]
    p_reg_list = p_regions_subs.add_parser("list", help="List installed or available regional data packs.")
    p_reg_list.add_argument(
        "--available",
        action="store_true",
        help="Query remote manifest and list all published regional packs available for download.",
    )
    p_reg_list.add_argument(
        "--country",
        default=None,
        help="Filter North American jurisdictions by country code ('US' or 'CA').",
    )
    p_reg_list.add_argument(
        "--manifest-url",
        default=None,
        help="Optional custom manifest.json URL.",
    )
    p_reg_list.add_argument(
        "--db-path",
        default=None,
        help="Optional SQLite database path.",
    )
    p_reg_list.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Emit structured JSON output.",
    )

    # regions install [REGIONS...] [--json] [--db-path DB_PATH]
    p_reg_install = p_regions_subs.add_parser("install", help="Download and install regional data packs.")
    p_reg_install.add_argument(
        "regions",
        nargs="+",
        help="One or more regional codes or pack identifiers to install (e.g. VT QC).",
    )
    p_reg_install.add_argument(
        "--manifest-url",
        default=None,
        help="Optional custom manifest.json URL.",
    )
    p_reg_install.add_argument(
        "--db-path",
        default=None,
        help="Optional SQLite database path.",
    )
    p_reg_install.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Emit structured JSON output.",
    )

    # regions update [--json] [--db-path DB_PATH]
    p_reg_update = p_regions_subs.add_parser("update", help="Update all currently installed packs to latest versions.")
    p_reg_update.add_argument(
        "--manifest-url",
        default=None,
        help="Optional custom manifest.json URL.",
    )
    p_reg_update.add_argument(
        "--db-path",
        default=None,
        help="Optional SQLite database path.",
    )
    p_reg_update.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Emit structured JSON output.",
    )

    # regions remove [REGIONS...] [--json] [--db-path DB_PATH]
    p_reg_remove = p_regions_subs.add_parser("remove", help="Remove an installed regional data pack.")
    p_reg_remove.add_argument(
        "regions",
        nargs="+",
        help="One or more region codes or pack IDs to remove (e.g. VT or towers-vt).",
    )
    p_reg_remove.add_argument(
        "--db-path",
        default=None,
        help="Optional SQLite database path.",
    )
    p_reg_remove.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Emit structured JSON output.",
    )

    # 10. towers subcommand
    p_towers = subparsers.add_parser(
        "towers",
        help="Manage, download, and ingest tower and infrastructure datasets.",
    )
    p_towers_subs = p_towers.add_subparsers(dest="towers_action", required=True)

    # towers ingest [source] [--source {fcc_asr,ised_sms,civic}] [--path/--input PATH] [--from-source] [--region REGION]
    p_tow_ingest = p_towers_subs.add_parser("ingest", help="Ingest raw tower data from source into registry.")
    p_tow_ingest.add_argument(
        "pos_source",
        nargs="?",
        choices=["fcc_asr", "ised_sms", "civic"],
        default=None,
        help="Authoritative dataset source to ingest (positional).",
    )
    p_tow_ingest.add_argument(
        "--source",
        choices=["fcc_asr", "ised_sms", "civic"],
        default=None,
        help="Authoritative dataset source to ingest.",
    )
    p_tow_ingest.add_argument(
        "--path",
        "--input",
        dest="path",
        default=None,
        help="Path to local source dataset file.",
    )
    p_tow_ingest.add_argument(
        "--from-source",
        action="store_true",
        help="Download dataset directly from authoritative source URL if --path is omitted.",
    )
    p_tow_ingest.add_argument(
        "--region",
        default=None,
        help="Optional administrative region filter (e.g. VT, CA_QC).",
    )
    p_tow_ingest.add_argument(
        "--db-path",
        default=None,
        help="Optional SQLite database path.",
    )
    p_tow_ingest.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Emit structured JSON output.",
    )

    # 11. packs subcommand
    p_packs = subparsers.add_parser(
        "packs",
        help="Build, validate, and publish regional data packs.",
    )
    p_packs_subs = p_packs.add_subparsers(dest="packs_action", required=True)

    # packs build [--regions REGIONS...] [--out-dir DIR] [--offline-fixtures]
    p_pack_build = p_packs_subs.add_parser("build", help="Build regional data packs and manifest.")
    p_pack_build.add_argument(
        "--regions",
        nargs="*",
        default=["VT"],
        help="Regions to build data packs for (default: VT, or 'all' for all 65 jurisdictions).",
    )
    p_pack_build.add_argument(
        "--all",
        action="store_true",
        help="Build data packs for all 65 North American jurisdictions.",
    )
    p_pack_build.add_argument(
        "--out-dir",
        default="dist/packs",
        help="Output directory for generated archives and manifest.json (default: dist/packs).",
    )
    p_pack_build.add_argument(
        "--offline-fixtures",
        action="store_true",
        help="Use offline sample fixtures without making external network calls.",
    )
    p_pack_build.add_argument(
        "--base-url",
        default=None,
        help="Optional base URL prefix for pack download URLs in manifest.",
    )
    p_pack_build.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Emit structured JSON output.",
    )

    # packs list
    p_pack_list = p_packs_subs.add_parser("list", help="List installed or available regional data packs.")
    p_pack_list.add_argument(
        "--available",
        action="store_true",
        help="Query remote manifest and list all published regional packs available for download.",
    )
    p_pack_list.add_argument(
        "--country",
        default=None,
        help="Filter North American jurisdictions by country code ('US' or 'CA').",
    )
    p_pack_list.add_argument(
        "--manifest-url",
        default=None,
        help="Optional custom manifest.json URL.",
    )
    p_pack_list.add_argument(
        "--db-path",
        default=None,
        help="Optional SQLite database path.",
    )
    p_pack_list.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Emit structured JSON output.",
    )

    # packs install [REGIONS...]
    p_pack_install = p_packs_subs.add_parser("install", help="Download and install regional data packs.")
    p_pack_install.add_argument(
        "regions",
        nargs="+",
        help="One or more regional codes to install (e.g. VT NH NY CA_QC).",
    )
    p_pack_install.add_argument(
        "--manifest-url",
        default=None,
        help="Optional custom manifest.json URL.",
    )
    p_pack_install.add_argument(
        "--db-path",
        default=None,
        help="Optional SQLite database path.",
    )
    p_pack_install.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Emit structured JSON output.",
    )

    # packs update
    p_pack_update = p_packs_subs.add_parser("update", help="Update all currently installed packs to latest versions.")
    p_pack_update.add_argument(
        "--manifest-url",
        default=None,
        help="Optional custom manifest.json URL.",
    )
    p_pack_update.add_argument(
        "--db-path",
        default=None,
        help="Optional SQLite database path.",
    )
    p_pack_update.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Emit structured JSON output.",
    )

    # packs remove [REGIONS...]
    p_pack_remove = p_packs_subs.add_parser("remove", help="Remove an installed regional data pack.")
    p_pack_remove.add_argument(
        "regions",
        nargs="+",
        help="One or more region codes or pack IDs to remove (e.g. VT or towers-vt).",
    )
    p_pack_remove.add_argument(
        "--db-path",
        default=None,
        help="Optional SQLite database path.",
    )
    p_pack_remove.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Emit structured JSON output.",
    )

    # 12. resilience subcommand
    p_resilience = subparsers.add_parser(
        "resilience",
        help="Evaluate backbone topology SPOFs, bridge links, and rollout BOM.",
    )
    p_resilience.add_argument(
        "--region",
        default="vt_chittenden",
        help="Target region identifier (default: vt_chittenden)",
    )
    p_resilience.add_argument(
        "--min-margin-db",
        type=float,
        default=0.0,
        help="Minimum link margin in dB for backbone connectivity (default: 0.0)",
    )
    p_resilience.add_argument(
        "--channel",
        default="LongFast",
        help="Meshtastic channel name (default: LongFast)",
    )
    p_resilience.add_argument(
        "--hardware",
        default="RAK4631_SOLAR",
        help="Hardware preset identifier for backbone nodes (default: RAK4631_SOLAR)",
    )
    p_resilience.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Emit structured JSON output.",
    )

    # 13. slot subcommand
    p_slot = subparsers.add_parser(
        "slot",
        help="Compute Meshtastic djb2 channel hash, frequency slot, and center frequency.",
    )
    p_slot.add_argument(
        "--channel",
        default="LongFast",
        help="Meshtastic channel name (default: LongFast)",
    )
    p_slot.add_argument(
        "--region",
        default="US",
        help="Meshtastic regulatory region code (default: US)",
    )
    p_slot.add_argument(
        "--bw-khz",
        type=float,
        default=250.0,
        help="LoRa channel bandwidth in kHz (default: 250.0)",
    )
    p_slot.add_argument(
        "--channel-num",
        type=int,
        default=0,
        help="Explicit 1-indexed channel number override, 0 for hash-derived (default: 0)",
    )
    p_slot.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Emit structured JSON output.",
    )

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entrypoint returning POSIX exit code (0 for success, non-zero for error)."""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1

    if args.command == "scout":
        res = scout_repeater_sites(
            region=args.region,
            min_coverage=args.min_coverage,
            max_repeaters=args.max_repeaters,
            no_delay=bool(args.no_delay),
        )
        if not res.get("ok"):
            sys.stderr.write(f"Error: {res.get('error', {}).get('message', 'Scout failed')}\n")
            return 1

        if args.output_json:
            sys.stdout.write(json.dumps(res, indent=2) + "\n")
        else:
            sys.stdout.write(
                f"Region: {res['region']} | Candidates: {res['total_candidates_evaluated']} | "
                f"Achieved Coverage: {res['achieved_coverage_fraction'] * 100:.1f}% "
                f"(Threshold Met: {res['threshold_met']})\n"
            )
            for item in res["selected_repeaters"]:
                sys.stdout.write(
                    f"  [{item['step']}] {item['site_id']} ({item['name']}) - "
                    f"Type: {item['site_type']}, Score: {item['viability_score']}, "
                    f"CumCov: {item['cumulative_coverage_fraction'] * 100:.1f}%\n"
                )
        return 0

    if args.command == "link":
        try:
            s_lat, s_lon, s_elev = _parse_coord_triplet(args.source)
            t_lat, t_lon, t_elev = _parse_coord_triplet(args.target)
        except ValueError as exc:
            sys.stderr.write(f"Error: {exc}\n")
            return 2

        res = evaluate_link_budget(
            source_lat=s_lat,
            source_lon=s_lon,
            source_elev_m=s_elev,
            target_lat=t_lat,
            target_lon=t_lon,
            target_elev_m=t_elev,
            frequency_mhz=args.freq,
            tx_power_dbm=args.tx_power,
            evaluation_mode=args.mode,
            source_preset=args.source_preset,
            target_preset=args.target_preset,
            client_env=args.client_env,
            protocol_profile=args.protocol,
            season_profile=args.season,
            source_noise_penalty_db=args.source_noise_db,
            target_noise_penalty_db=args.target_noise_db,
        )
        if not res.get("ok"):
            sys.stderr.write(f"Error: {res.get('error', {}).get('message', 'Link budget failed')}\n")
            return 1

        if args.output_json:
            sys.stdout.write(json.dumps(res, indent=2) + "\n")
        else:
            lb = res["link_budget"]
            fa = res["fresnel_analysis"]
            sys.stdout.write(
                f"Link Distance: {lb['distance_km']:.2f} km | LOS: {lb['has_line_of_sight']} | "
                f"60% Fresnel Clear: {fa['fresnel_60pct_clear']}\n"
                f"FSPL: {lb['free_space_loss_db']:.2f} dB | Diffraction Loss: {lb['diffraction_loss_db']:.2f} dB | "
                f"RX Power: {lb['rx_power_dbm']:.2f} dBm | Link Margin: {lb['link_margin_db']:.2f} dB\n"
            )
            if lb.get("reachability_state") is not None:
                sys.stdout.write(
                    f"Mode: {res.get('evaluation_mode', 'client')} | "
                    f"Reachability: {lb['reachability_state']} | "
                    f"Downlink Margin: {lb['downlink_margin_db']:.2f} dB | "
                    f"Uplink Margin: {lb['uplink_margin_db']:.2f} dB | "
                    f"Asymmetry Delta: {lb['asymmetry_delta_db']:.2f} dB\n"
                )
        return 0

    if args.command == "reach":
        registry = LivingMeshRegistry(db_path=args.db_path)
        prefs = registry.get_preferences()

        lat = float(args.lat) if args.lat is not None else prefs.home_lat
        lon = float(args.lon) if args.lon is not None else prefs.home_lon
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            sys.stderr.write(f"Error: Invalid latitude ({lat}) or longitude ({lon}).\n")
            return 1

        if args.elev_m is not None:
            elev_m = float(args.elev_m)
        elif args.lat is not None or args.lon is not None:
            elev_m = _synthetic_vermont_elevation_fn(lat, lon)
        else:
            elev_m = prefs.home_elev_m

        env_key = args.client_env.strip().upper()
        env_prof = CLIENT_ENVIRONMENT_PROFILES[env_key]
        agl_m = float(args.agl_m) if args.agl_m is not None else env_prof.default_agl_m

        eff_preset = args.client_preset.strip().upper()
        eff_protocol = args.protocol.strip().upper()
        eff_season = args.season.strip().upper()

        radio_res = build_radio_config(
            hardware_id=eff_preset,
            protocol_id=eff_protocol,
            season_id=eff_season,
        )
        if not radio_res.ok or radio_res.value is None:
            msg = radio_res.error.message if radio_res.error else "Invalid client radio preset"
            sys.stderr.write(f"Error: {msg}\n")
            return 1

        nodes = registry.list_nodes()
        if not nodes:
            _, candidates = load_regional_fixtures(region="vt_chittenden")
            registry.seed_candidates(candidates)
            nodes = registry.list_nodes()

        reach_res = evaluate_home_node_reach(
            home_coord=Coordinate(lat=lat, lon=lon, elevation_m=elev_m),
            home_height_agl_m=agl_m,
            nodes=nodes,
            client_radio=radio_res.value,
            client_env_loss_db=env_prof.clutter_loss_db,
            protocol_id=eff_protocol,
            season_id=eff_season,
            elevation_fn=_synthetic_vermont_elevation_fn,
        )
        if not reach_res.ok or reach_res.value is None:
            msg = reach_res.error.message if reach_res.error else "Reach evaluation failed"
            sys.stderr.write(f"Error: {msg}\n")
            return 1

        report_dict = reach_res.value.model_dump(mode="json")
        ranked = report_dict["ranked_towers"]
        two_way_count = sum(1 for t in ranked if t.get("reachability_state") == "two_way")
        alligator_count = sum(
            1 for t in ranked if t.get("reachability_state") == "hear_only_alligator"
        )
        payload = {
            "ok": True,
            "client_preset": eff_preset,
            "client_env": env_key,
            "client_env_loss_db": env_prof.clutter_loss_db,
            "protocol_profile": eff_protocol,
            "season_profile": eff_season,
            "two_way_count": two_way_count,
            "hear_only_alligator_count": alligator_count,
            **report_dict,
            "report": report_dict,
        }

        if args.output_json:
            sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        else:
            sys.stdout.write(
                f"Client Reach: ({lat:.4f}, {lon:.4f}, {elev_m:.1f}m + {agl_m:.1f}m AGL) | "
                f"Preset: {eff_preset} | Env: {env_key} ({env_prof.clutter_loss_db:.1f} dB)\n"
                f"Two-Way Towers: {two_way_count} | Hear-Only Alligator Towers: {alligator_count} | "
                f"Best Azimuth: {report_dict['best_azimuth_deg']} ({report_dict['best_cardinal_direction']})\n"
            )
            for item in ranked:
                sys.stdout.write(
                    f"  [{item['recommended_rank']}] [{item['reachability_state']}] "
                    f"{item['site_id']} ({item['name']}) - Dist: {item['distance_km']:.2f} km, "
                    f"Az: {item['azimuth_deg']:.1f} ({item['cardinal_direction']}), "
                    f"DL: {item['downlink_margin_db']:.2f} dB, UL: {item['uplink_margin_db']:.2f} dB\n"
                )
        return 0

    if args.command == "feasibility":
        res = inspect_site_feasibility(
            site_id=args.site_id,
            nearby_850_900mhz_erp_watts=args.emitter_watts,
        )
        if not res.get("ok"):
            sys.stderr.write(f"Error: {res.get('error', {}).get('message', 'Feasibility check failed')}\n")
            return 1

        if args.output_json:
            sys.stdout.write(json.dumps(res, indent=2) + "\n")
        else:
            v = res["viability"]
            sys.stdout.write(
                f"Site: {res['site_id']} ({res['name']}) [{res['site_type']}]\n"
                f"Composite Score: {v['composite_score']:.1f}/100 | "
                f"Desense Risk: {v['desense_risk']} | "
                f"Requires Cavity Filter: {v['requires_cavity_filter']}\n"
            )
        return 0

    if args.command == "mcp":
        transport = "stdio" if args.stdio else args.transport
        if transport == "stdio":
            server = MeshScoutMCPServer()
            server.run_stdio()
            return 0

        if transport == "sse":
            app = create_fastmcp_app(host=args.host, port=args.port)
            if hasattr(app, "run") and not isinstance(app, MeshScoutMCPServer):
                if hasattr(app, "settings"):
                    app.settings.host = args.host
                    app.settings.port = args.port
                app.run(transport="sse")
                return 0

            # Fallback without FastMCP
            try:
                import uvicorn
            except ImportError:
                sys.stderr.write(
                    "Error: SSE transport requires 'uvicorn' to be installed.\n"
                )
                return 1

            try:
                fallback_app = create_fallback_sse_app()
                uvicorn.run(fallback_app, host=args.host, port=args.port)
                return 0
            except Exception as exc:
                sys.stderr.write(f"Error starting SSE MCP server: {exc}\n")
                return 1

        return 1

    if args.command == "serve":
        import uvicorn
        from meshscout.web.app import create_web_app

        app = create_web_app(db_path=args.db_path)
        uvicorn.run(app, host=args.host, port=args.port)
        return 0

    if args.command == "stage":
        from meshscout.core.staging import stage_offline_region

        res = stage_offline_region(
            state_code=args.region,
            output_dir=args.output_dir,
            buffer_km=args.buffer_km,
            min_zoom=args.min_zoom,
            max_zoom=args.max_zoom,
            include_dem=not args.no_dem,
            dry_run=args.dry_run,
        )
        if not res.ok:
            msg = res.error.message if res.error else "Stage failed"
            sys.stderr.write(f"Error: {msg}\n")
            return 1

        val = res.value or {}
        if getattr(args, "output_json", False):
            sys.stdout.write(json.dumps(val, indent=2) + "\n")
        else:
            b = val.get("bounds", {})
            mode_str = "DRY RUN (Simulated)" if val.get("dry_run") else "COMPLETED"
            sys.stdout.write("============================================================\n")
            sys.stdout.write(f" MeshScout Field Kit Staging: {val.get('state_code')} [{mode_str}]\n")
            sys.stdout.write("============================================================\n")
            sys.stdout.write(f" Buffer:        {val.get('buffer_km', 20.0)} km\n")
            sys.stdout.write(
                f" Bounding Box:  {b.get('min_lat', 0):.4f}, {b.get('min_lon', 0):.4f} to "
                f"{b.get('max_lat', 0):.4f}, {b.get('max_lon', 0):.4f}\n"
            )
            sys.stdout.write(
                f" Zoom Range:    {val.get('min_zoom', 7)} to {val.get('max_zoom', 12)}\n"
            )
            est_mb = val.get("est_bytes", 0) / (1024 * 1024)
            sys.stdout.write(
                f" Total Tiles:   {val.get('total_tiles', 0):,} (~{est_mb:.2f} MB est.)\n"
            )
            if val.get("dry_run"):
                sys.stdout.write(" Planned Assets:\n")
                for item in val.get("planned_files", []):
                    sys.stdout.write(f"   - {item}\n")
            else:
                sys.stdout.write(f" Tiles Written: {val.get('tiles_written', 0):,}\n")
                sys.stdout.write(f" MBTiles Path:  {val.get('mbtiles_path')}\n")
                sys.stdout.write(f" Mesh DB:       {val.get('mesh_db_path')}\n")
                sys.stdout.write(f" DEM Synced:    {val.get('dem_tiles_copied', 0)} tiles\n")
            sys.stdout.write("============================================================\n")
        return 0

    if args.command == "ingest-towers":
        from meshscout.adapters.civic_highsites import (
            DEFAULT_CIVIC_HIGHSITES_CATALOG,
            load_civic_highsites,
        )
        from meshscout.adapters.fcc_asr_bulk import (
            classify_tower_ownership,
            parse_fcc_asr_bulk,
        )
        from meshscout.adapters.ised_sms import parse_ised_sms_records
        from meshscout.adapters.regions import resolve_regional_bounds
        from meshscout.core.contracts import SiteType
        from meshscout.core.tower_registry import (
            UnifiedTowerRegistry,
            resolve_friction_tier,
        )

        bounds = None
        if args.region:
            reg_res = resolve_regional_bounds(args.region)
            if not reg_res.ok and "_" in args.region:
                parts = args.region.split("_", 1)
                reg_res = resolve_regional_bounds(parts[0], parts[1])
            if not reg_res.ok:
                msg = reg_res.error.message if reg_res.error else f"Invalid region '{args.region}'"
                sys.stderr.write(f"Error: {msg}\n")
                return 1
            bounds = reg_res.value

        registry = UnifiedTowerRegistry(db_path=args.db_path)
        tier_counts = {1: 0, 2: 0, 3: 0}
        source_counts: dict[str, int] = {}

        def _commit_batch(
            candidates: Sequence[Any],
            source_tag: str,
            default_owner: str = "",
            default_category: str = "",
        ) -> int:
            count = 0
            batch_size = max(1, args.batch_size)
            for i in range(0, len(candidates), batch_size):
                chunk = candidates[i : i + batch_size]
                with registry.conn:
                    for cand in chunk:
                        owner = default_owner
                        owner_cat = (
                            "agricultural"
                            if cand.site_type == SiteType.SILO
                            else default_category
                        )
                        if cand.notes:
                            for part in cand.notes.split(" | "):
                                if part.startswith("Owner: ") or part.startswith("Licensee: "):
                                    owner = part.split(": ", 1)[1].strip()
                                elif part.startswith("Owner Category: "):
                                    owner_cat = part.split(": ", 1)[1].strip()
                        tier = resolve_friction_tier(cand.site_type, owner_cat)
                        tier_int = int(tier.value if hasattr(tier, "value") else tier)
                        registry.upsert_tower(
                            cand,
                            owner=owner,
                            owner_category=owner_cat,
                            source_dataset=source_tag,
                            friction_tier=tier,
                        )
                        tier_counts[tier_int] += 1
                        count += 1
            source_counts[source_tag] = count
            return count

        # 1. Civic source
        if args.source in ("civic", "all"):
            catalog_path = Path(args.civic_catalog) if args.civic_catalog else DEFAULT_CIVIC_HIGHSITES_CATALOG
            if catalog_path.exists():
                civic_candidates = load_civic_highsites(catalog_path=catalog_path, bounds=bounds)
                _commit_batch(
                    civic_candidates,
                    "civic",
                    default_owner="Civic/Public",
                    default_category="civic_public_safety",
                )
            elif args.source == "civic":
                sys.stderr.write(f"Error: Civic catalog not found at {catalog_path}\n")
                return 1

        # 2. FCC source
        if args.source in ("fcc", "all"):
            if args.ant_path:
                fcc_candidates = parse_fcc_asr_bulk(
                    ant_path_or_content=args.ant_path,
                    own_path_or_content=args.own_path,
                    bounds=bounds,
                )
                _commit_batch(
                    fcc_candidates,
                    "fcc_asr",
                    default_owner="Commercial Carrier",
                    default_category="commercial_carrier",
                )
            elif args.source == "fcc":
                sys.stderr.write("Error: --ant-path is required when source is 'fcc'\n")
                return 1

        # 3. ISED source
        if args.source in ("ised", "all"):
            if args.ised_path:
                ised_candidates = parse_ised_sms_records(
                    content_or_path=args.ised_path,
                    bounds=bounds,
                )
                _commit_batch(
                    ised_candidates,
                    "ised_sms",
                    default_owner="Canadian Carrier",
                    default_category="commercial_carrier",
                )
            elif args.source == "ised":
                sys.stderr.write("Error: --ised-path is required when source is 'ised'\n")
                return 1

        total = sum(tier_counts.values())
        if getattr(args, "output_json", False):
            summary = {
                "ok": True,
                "source": args.source,
                "region": args.region,
                "total_ingested": total,
                "by_friction_tier": {
                    "tier_1_civic": tier_counts[1],
                    "tier_2_agricultural": tier_counts[2],
                    "tier_3_commercial": tier_counts[3],
                },
                "by_source": source_counts,
            }
            sys.stdout.write(json.dumps(summary, indent=2) + "\n")
        else:
            sys.stdout.write("============================================================\n")
            sys.stdout.write(" MeshScout Tower Ingestion Summary\n")
            sys.stdout.write("============================================================\n")
            sys.stdout.write(f" Source:            {args.source}\n")
            sys.stdout.write(f" Region Filter:     {args.region or 'All / Unbounded'}\n")
            sys.stdout.write(f" Total Ingested:    {total:,}\n")
            sys.stdout.write("------------------------------------------------------------\n")
            sys.stdout.write(" Ingested by Friction Tier:\n")
            sys.stdout.write(f"   - Tier 1 Civic:          {tier_counts[1]:,} sites\n")
            sys.stdout.write(f"   - Tier 2 Ag / Utility:   {tier_counts[2]:,} sites\n")
            sys.stdout.write(f"   - Tier 3 Commercial:     {tier_counts[3]:,} sites\n")
            sys.stdout.write("============================================================\n")
        return 0

    if args.command == "sync-telemetry":
        from meshscout.adapters.telemetry_cache import UnifiedTelemetryCache
        from meshscout.adapters.mqtt_live import sync_telemetry_from_broker

        cache = UnifiedTelemetryCache(db_path=args.db_path)
        try:
            if args.source == "sample":
                count = cache.seed_from_sample_fixture()
                sync_res = {"ok": True, "count": count, "source": "sample", "region": args.region}
            else:
                sync_res = sync_telemetry_from_broker(
                    state_code=args.region,
                    cache=cache,
                    db_path=args.db_path,
                )

            counts = cache.count_nodes_by_protocol(state_code=args.region, buffer_km=args.buffer_km)
            total = sum(counts.values())

            if not sync_res.get("ok"):
                if getattr(args, "output_json", False):
                    summary = {
                        "ok": False,
                        "source": args.source,
                        "region": args.region,
                        "buffer_km": args.buffer_km,
                        "total_cached": total,
                        "by_protocol": counts,
                        "error": sync_res.get("error"),
                    }
                    sys.stdout.write(json.dumps(summary, indent=2) + "\n")
                else:
                    sys.stderr.write(f"Error: Telemetry sync failed: {sync_res.get('error')}\n")
                return 1

            if getattr(args, "output_json", False):
                summary = {
                    "ok": True,
                    "source": args.source,
                    "region": args.region,
                    "buffer_km": args.buffer_km,
                    "total_cached": total,
                    "by_protocol": counts,
                    "sync_details": sync_res,
                }
                sys.stdout.write(json.dumps(summary, indent=2) + "\n")
            else:
                sys.stdout.write("============================================================\n")
                sys.stdout.write(" MeshScout Telemetry Cache Sync Summary\n")
                sys.stdout.write("============================================================\n")
                sys.stdout.write(f" Source:            {args.source}\n")
                sys.stdout.write(f" Region Filter:     {args.region or 'All / Unbounded'}\n")
                sys.stdout.write(f" Regional Buffer:   {args.buffer_km:.1f} km\n")
                sys.stdout.write(f" Total Cached:      {total:,} nodes\n")
                sys.stdout.write("------------------------------------------------------------\n")
                sys.stdout.write(" Cached Nodes by Protocol:\n")
                if counts:
                    for proto, count_val in sorted(counts.items()):
                        sys.stdout.write(f"   - {proto.capitalize():<18}: {count_val:,} nodes\n")
                else:
                    sys.stdout.write("   (No nodes found in specified region/buffer)\n")
                sys.stdout.write("============================================================\n")
            return 0
        finally:
            cache.close()

    if args.command == "regions" or (args.command == "packs" and getattr(args, "packs_action", None) != "build"):
        from meshscout.adapters.pack_client import DEFAULT_MANIFEST_URL, PackClient
        from meshscout.core.packs import list_installed_packs, uninstall_region_pack
        from meshscout.core.tower_registry import UnifiedTowerRegistry

        action = getattr(args, "regions_action", None) or getattr(args, "packs_action", None)
        manifest_url = getattr(args, "manifest_url", None) or DEFAULT_MANIFEST_URL
        client = PackClient(manifest_url=manifest_url)
        registry = UnifiedTowerRegistry(db_path=args.db_path)
        try:
            if action == "list":
                if getattr(args, "country", None):
                    from meshscout.adapters.regions import list_north_america_regions

                    regions_data = list_north_america_regions(country=args.country)
                    if getattr(args, "output_json", False):
                        sys.stdout.write(json.dumps(regions_data, indent=2) + "\n")
                    else:
                        sys.stdout.write("============================================================\n")
                        sys.stdout.write(f" MeshScout North American Regions ({args.country.upper()})\n")
                        sys.stdout.write("============================================================\n")
                        for reg in regions_data:
                            code = reg.get("state_code") or reg.get("code")
                            sys.stdout.write(f"  - {code:<6} | {reg['name']} ({reg['country']})\n")
                        sys.stdout.write("============================================================\n")
                    return 0

                if args.available:
                    res = client.list_available_packs()
                    if not res.ok:
                        err_msg = res.error.message if res.error else "Failed to retrieve available packs"
                        sys.stderr.write(f"Error: {err_msg}\n")
                        return 1
                    packs = res.value or []
                    if getattr(args, "output_json", False):
                        sys.stdout.write(json.dumps([p.model_dump() for p in packs], indent=2) + "\n")
                    else:
                        sys.stdout.write("============================================================\n")
                        sys.stdout.write(" MeshScout Available Regional Data Packs\n")
                        sys.stdout.write("============================================================\n")
                        if not packs:
                            sys.stdout.write(" No packs found in remote manifest.\n")
                        for p in packs:
                            size_kb = p.size_bytes / 1024
                            sys.stdout.write(
                                f"  - {p.pack_id:<15} [v{p.pack_version}] Region: {p.region_code:<6} | "
                                f"{p.row_count:,} towers | {size_kb:.1f} KB\n"
                            )
                        sys.stdout.write("============================================================\n")
                        sys.stdout.write(" Sources: FCC ASR | ISED TAFL (OGL-Canada-2.0) | © OpenStreetMap contributors (ODbL-1.0)\n")
                        sys.stdout.write("============================================================\n")
                    return 0
                else:
                    installed = list_installed_packs(registry)
                    if getattr(args, "output_json", False):
                        sys.stdout.write(json.dumps(installed, indent=2) + "\n")
                    else:
                        sys.stdout.write("============================================================\n")
                        sys.stdout.write(" MeshScout Installed Regional Data Packs\n")
                        sys.stdout.write("============================================================\n")
                        if not installed:
                            sys.stdout.write(" No regional packs currently installed.\n")
                        for p in installed:
                            sys.stdout.write(
                                f"  - {p['pack_id']:<15} [v{p['pack_version']}] Region: {p['region_code']:<6} | "
                                f"Installed: {p.get('installed_at', 'unknown')}\n"
                            )
                        sys.stdout.write("------------------------------------------------------------\n")
                        sys.stdout.write(" Sources: FCC ASR | ISED TAFL (OGL-Canada-2.0) | © OpenStreetMap contributors (ODbL-1.0)\n")
                        sys.stdout.write("============================================================\n")
                    return 0

            elif action == "install":
                results = []
                all_ok = True
                for reg in args.regions:
                    res = client.install_pack(registry, reg)
                    if res.ok and res.value:
                        results.append({"region": reg, "ok": True, "pack": res.value.model_dump()})
                    else:
                        all_ok = False
                        msg = res.error.message if res.error else "Install failed"
                        results.append({"region": reg, "ok": False, "error": msg})

                if getattr(args, "output_json", False):
                    sys.stdout.write(json.dumps({"ok": all_ok, "results": results}, indent=2) + "\n")
                else:
                    for r in results:
                        if r["ok"]:
                            p = r["pack"]
                            sys.stdout.write(
                                f"Successfully installed pack '{p['pack_id']}' "
                                f"({p['row_count']} towers registered, v{p['pack_version']})\n"
                            )
                        else:
                            sys.stderr.write(f"Failed to install pack '{r['region']}': {r['error']}\n")
                return 0 if all_ok else 1

            elif action == "update":
                up_res = client.update_installed_packs(registry)
                if getattr(args, "output_json", False):
                    sys.stdout.write(json.dumps(up_res, indent=2) + "\n")
                else:
                    sys.stdout.write("============================================================\n")
                    sys.stdout.write(" MeshScout Regional Packs Update Summary\n")
                    sys.stdout.write("============================================================\n")
                    sys.stdout.write(f" Updated:    {len(up_res.get('updated', []))}\n")
                    for u in up_res.get("updated", []):
                        sys.stdout.write(f"   - {u['pack_id']}: v{u.get('old_version')} -> v{u.get('new_version')}\n")
                    sys.stdout.write(f" Up to date: {len(up_res.get('up_to_date', []))}\n")
                    for u in up_res.get("up_to_date", []):
                        sys.stdout.write(f"   - {u['pack_id']} (v{u.get('version')})\n")
                    if up_res.get("failed"):
                        sys.stdout.write(f" Failed:     {len(up_res['failed'])}\n")
                        for f in up_res["failed"]:
                            sys.stdout.write(f"   - {f['pack_id']}: {f.get('error')}\n")
                    sys.stdout.write("============================================================\n")
                return 0 if up_res.get("ok", False) else 1

            elif action == "remove":
                installed = list_installed_packs(registry)
                installed_ids = {p["pack_id"]: p for p in installed}
                raw_regions = getattr(args, "regions", None) or [getattr(args, "region", "")]
                total_removed = 0
                results = []
                for r_item in raw_regions:
                    target_pack_id = r_item
                    if target_pack_id not in installed_ids and f"towers-{target_pack_id.lower()}" in installed_ids:
                        target_pack_id = f"towers-{target_pack_id.lower()}"

                    removed = uninstall_region_pack(registry, target_pack_id)
                    total_removed += removed
                    results.append({"pack_id": target_pack_id, "removed_towers": removed})

                if getattr(args, "output_json", False):
                    sys.stdout.write(
                        json.dumps({"ok": True, "results": results, "total_removed_towers": total_removed}, indent=2) + "\n"
                    )
                else:
                    for res in results:
                        sys.stdout.write(
                            f"Uninstalled pack '{res['pack_id']}': removed {res['removed_towers']} unreferenced tower(s).\n"
                        )
                return 0
        finally:
            registry.close()

    if args.command == "towers":
        return run_towers_subcommand(args)

    if args.command == "packs":
        from meshscout.adapters.pack_builder import build_region_packs

        if args.packs_action == "build":
            if getattr(args, "all", False):
                regions = ["ALL"]
            else:
                regions = args.regions if args.regions else ["VT"]
            try:
                manifest = build_region_packs(
                    regions=regions,
                    out_dir=args.out_dir,
                    offline_fixtures=bool(args.offline_fixtures),
                    base_url=args.base_url,
                )
                if getattr(args, "output_json", False):
                    sys.stdout.write(manifest.to_json(indent=2) + "\n")
                else:
                    sys.stdout.write("============================================================\n")
                    sys.stdout.write(f" Successfully built {len(manifest.packs)} regional data pack(s)\n")
                    sys.stdout.write("============================================================\n")
                    sys.stdout.write(f" Destination: {args.out_dir}\n")
                    for p_id, p in manifest.packs.items():
                        size_kb = p.size_bytes / 1024
                        sys.stdout.write(
                            f"   - {p_id:<15} Region: {p.region_code:<6} | {p.row_count:,} towers | "
                            f"{size_kb:.1f} KB | SHA-256: {p.sha256[:10]}...\n"
                        )
                    sys.stdout.write(f" Manifest: {Path(args.out_dir) / 'manifest.json'}\n")
                    sys.stdout.write("============================================================\n")
                return 0
            except Exception as exc:
                sys.stderr.write(f"Error building regional packs: {exc}\n")
                return 1

    if args.command == "resilience":
        res = evaluate_backbone_resilience(
            region=args.region,
            min_margin_db=args.min_margin_db,
            channel_name=args.channel,
            hardware_id=args.hardware,
        )
        if not res.get("ok"):
            sys.stderr.write(
                f"Error: {(res.get('error') or {}).get('message', 'Resilience evaluation failed')}\n"
            )
            return 1

        if args.output_json:
            sys.stdout.write(json.dumps(res, indent=2) + "\n")
        else:
            report = res["report"]
            bom = report.get("rollout_bom") or {}
            sys.stdout.write(
                f"Region: {res['region']} | Nodes: {report['node_count']} | "
                f"Edges: {report['edge_count']} | Components: {report['connected_components']} | "
                f"Biconnected Score: {report['biconnected_score']} | "
                f"Estimated Total USD: ${float(bom.get('estimated_total_usd', 0.0)):.2f}\n"
            )
        return 0

    if args.command == "slot":
        res = compute_channel_slot(
            channel_name=args.channel,
            region_code=args.region,
            bandwidth_khz=args.bw_khz,
            explicit_channel_num=args.channel_num,
        )
        if not res.get("ok"):
            sys.stderr.write(
                f"Error: {(res.get('error') or {}).get('message', 'Channel slot computation failed')}\n"
            )
            return 1

        if args.output_json:
            sys.stdout.write(json.dumps(res, indent=2) + "\n")
        else:
            sys.stdout.write(
                f"Channel: {res['channel_name']} | Region: {res['region_code']} | "
                f"Frequency Slot: {res['frequency_slot']} (slot_index={res['slot_index']}) | "
                f"Center Freq: {res['center_freq_mhz']} MHz\n"
            )
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
