"""FastAPI /api/v1 sub-router for topology resilience, channel slots, highpoints, CoT, and CSV."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from meshscout import commands
from meshscout.reporting import export_link_matrix_csv

MAX_CSV_UPLOAD_BYTES = 262_144


class BackboneResilienceRequest(BaseModel):
    """JSON body for POST /api/v1/topology/resilience."""

    region: str = Field(default="vt_chittenden")
    site_ids: Optional[List[str]] = Field(default=None)
    min_margin_db: float = Field(default=0.0)
    channel_name: str = Field(default="LongFast")
    protocol_key: str = Field(default="MESHTASTIC_LONGFAST")
    hardware_id: str = Field(default="RAK4631_SOLAR")


class CotExportRequest(BaseModel):
    """JSON body for POST /api/v1/export/cot."""

    region: str = Field(default="vt_chittenden")
    site_ids: Optional[List[str]] = Field(default=None)
    stale_minutes: int = Field(default=60, ge=1)


def build_resilience_router() -> APIRouter:
    """Create the stateless /api/v1 resilience, channel slot, highpoint, CoT, and CSV APIRouter."""
    sub_router = APIRouter()

    @sub_router.post("/api/v1/topology/resilience")
    def post_topology_resilience_endpoint(
        body: Optional[BackboneResilienceRequest] = None,
    ) -> Dict[str, Any]:
        """Evaluate backbone SPOFs, bridge edges, winter rollout BOM, and djb2 channel slot."""
        req = body or BackboneResilienceRequest()
        return commands.evaluate_backbone_resilience(
            region=req.region,
            site_ids=req.site_ids,
            min_margin_db=req.min_margin_db,
            channel_name=req.channel_name,
            protocol_key=req.protocol_key,
            hardware_id=req.hardware_id,
        )

    @sub_router.get("/api/v1/channel/slot")
    def get_channel_slot_endpoint(
        channel: str = Query(default="LongFast", description="Meshtastic channel name"),
        region: str = Query(default="US", description="Regulatory band plan code"),
        bw_khz: float = Query(default=250.0, description="Channel bandwidth in kHz"),
        channel_num: int = Query(default=0, description="Optional 1-indexed frequency slot override"),
    ) -> Dict[str, Any]:
        """Compute Meshtastic djb2 channel hash, 1-indexed frequency slot, and center frequency."""
        return commands.compute_channel_slot(
            channel_name=channel,
            region_code=region,
            bandwidth_khz=bw_khz,
            explicit_channel_num=channel_num,
        )

    @sub_router.get("/api/v1/sites/highpoint")
    def get_site_highpoint_endpoint(
        lat: float = Query(..., ge=-90.0, le=90.0, description="Origin latitude in decimal degrees"),
        lon: float = Query(..., ge=-180.0, le=180.0, description="Origin longitude in decimal degrees"),
        radius_m: float = Query(default=500.0, description="Local terrain search radius in meters"),
        step_m: float = Query(default=50.0, description="Grid sampling step size in meters"),
    ) -> Dict[str, Any]:
        """Snap a candidate site coordinate to the highest terrain point within radius_m."""
        return commands.snap_site_highpoint(
            lat=lat,
            lon=lon,
            radius_m=radius_m,
            step_m=step_m,
        )

    @sub_router.post("/api/v1/export/cot")
    def post_export_cot_endpoint(
        body: Optional[CotExportRequest] = None,
    ) -> Dict[str, Any]:
        """Export regional candidate repeater sites as ATAK Cursor-on-Target (CoT) 2.0 XML."""
        req = body or CotExportRequest()
        return commands.export_cot_bundle(
            region=req.region,
            site_ids=req.site_ids,
            stale_minutes=req.stale_minutes,
        )

    @sub_router.post("/api/v1/export/links.csv")
    async def post_export_links_csv_endpoint(request: Request) -> Response:
        """Export point-to-point RF link metrics as a downloadable text/csv matrix."""
        try:
            payload = await request.json()
        except Exception as exc:
            return JSONResponse(
                status_code=400,
                content={
                    "ok": False,
                    "error": {"code": "INVALID_JSON", "message": f"Invalid JSON payload: {exc}"},
                },
            )

        if isinstance(payload, list):
            links = payload
        elif isinstance(payload, dict) and isinstance(payload.get("links"), list):
            links = payload["links"]
        else:
            return JSONResponse(
                status_code=400,
                content={
                    "ok": False,
                    "error": {
                        "code": "INVALID_LINKS_PAYLOAD",
                        "message": "Expected a JSON list of link objects or {'links': [...]}",
                    },
                },
            )

        csv_body = export_link_matrix_csv(links)
        return Response(content=csv_body, media_type="text/csv")

    @sub_router.post("/api/v1/import/sites.csv")
    async def post_import_sites_csv_endpoint(request: Request) -> Response:
        """Parse and validate bulk candidate sites from a CSV request body (<=262,144 bytes)."""
        raw_bytes = await request.body()
        if len(raw_bytes) > MAX_CSV_UPLOAD_BYTES:
            return JSONResponse(
                status_code=413,
                content={
                    "ok": False,
                    "error": {
                        "code": "CSV_LIMIT_EXCEEDED",
                        "message": (
                            f"CSV payload ({len(raw_bytes)} bytes) exceeds limit of "
                            f"{MAX_CSV_UPLOAD_BYTES} bytes."
                        ),
                    },
                },
            )

        try:
            csv_text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            return JSONResponse(
                status_code=400,
                content={
                    "ok": False,
                    "error": {
                        "code": "INVALID_CSV_ROW",
                        "message": f"CSV payload is not valid UTF-8: {exc}",
                    },
                },
            )

        res = commands.import_sites_csv(csv_text)
        if res.get("ok"):
            return JSONResponse(status_code=200, content=res)

        err_code = res.get("error", {}).get("code", "")
        status_code = 413 if err_code == "CSV_LIMIT_EXCEEDED" else 400
        return JSONResponse(status_code=status_code, content=res)

    return sub_router


router: APIRouter = build_resilience_router()

__all__ = [
    "BackboneResilienceRequest",
    "CotExportRequest",
    "MAX_CSV_UPLOAD_BYTES",
    "build_resilience_router",
    "router",
]
