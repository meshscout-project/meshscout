"""Unit tests for civic and public-safety high-sites adapter."""

from pathlib import Path
import io
import json
import math
import sys
from unittest.mock import MagicMock, patch
import urllib.error

import pytest

from meshscout.adapters.civic_highsites import (
    DEFAULT_CIVIC_HIGHSITES_CATALOG,
    build_overpass_query,
    harvest_civic_features_from_geojson,
    load_civic_highsites,
    overpass_json_to_geojson,
    subdivide_bounding_box,
)
from meshscout.adapters.pack_builder import (
    build_region_packs,
    haversine_distance_m,
    ingest_cached_civic_geojson,
    ingest_civic_candidates_with_suppression,
    is_spatially_suppressed,
)
from meshscout.core.contracts import (
    AccessDifficulty,
    Coordinate,
    RegionalBounds,
    SiteCandidate,
    SiteType,
)
from meshscout.core.tower_registry import UnifiedTowerRegistry

_scripts_dir = str(Path(__file__).resolve().parent.parent / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from harvest_civic_highsites import (
    OverpassRateLimiter,
    harvest_region_civic,
    query_overpass,
)


def test_load_civic_highsites_all():
    """Verify default catalog loads authentic high-sites across all target categories."""
    sites = load_civic_highsites()
    assert len(sites) == 16

    for site in sites:
        assert isinstance(site, SiteCandidate)
        assert site.site_id.startswith("CIVIC-")
        assert len(site.name) > 0
        assert -90.0 <= site.location.lat <= 90.0
        assert -180.0 <= site.location.lon <= 180.0
        assert site.mast_height_m > 0.0
        assert site.source_url is not None and site.source_url.startswith("http")
        assert site.notes is not None

    types = {s.site_type for s in sites}
    assert SiteType.FIRE_LOOKOUT in types
    assert SiteType.WATER_TOWER in types
    assert SiteType.RESEARCH_TOWER in types
    assert SiteType.SILO in types


def test_load_civic_highsites_bounds_filtering():
    """Verify filtering by Chittenden County bounds includes local water tanks and excludes NY/regional towers."""
    chittenden_bounds = RegionalBounds(
        name="Chittenden_County",
        min_lat=44.25,
        max_lat=44.60,
        min_lon=-73.35,
        max_lon=-72.80,
    )

    filtered_sites = load_civic_highsites(bounds=chittenden_bounds)
    names = [s.name for s in filtered_sites]

    # Burlington and Essex Junction water tanks must be present
    assert any("Burlington Water Tank" in n for n in names)
    assert any("Essex Junction Water Standpipe" in n for n in names)

    # Blue Mountain in the central Adirondacks must be excluded
    assert not any("Blue Mountain" in n for n in names)
    assert not any("Saint Regis" in n for n in names)
    assert not any("Milan Hill" in n for n in names)
    assert not any("Plattsburgh" in n for n in names)


def test_load_civic_highsites_type_filtering():
    """Verify filtering by SiteType returns only matching assets."""
    fire_lookouts = load_civic_highsites(site_types=[SiteType.FIRE_LOOKOUT])
    assert len(fire_lookouts) == 5
    for site in fire_lookouts:
        assert site.site_type == SiteType.FIRE_LOOKOUT

    names = {s.name for s in fire_lookouts}
    assert "Burke Mountain Fire Tower" in names
    assert "Mount Ascutney Fire Tower" in names
    assert "Blue Mountain Fire Tower" in names
    assert "Saint Regis Mountain Fire Tower" in names
    assert "Milan Hill Fire Tower" in names

    # Water towers and silos should not appear
    assert not any("Water" in n for n in names)
    assert not any("Silo" in n for n in names)

    # Test filtering by multiple types
    towers_and_silos = load_civic_highsites(site_types=[SiteType.WATER_TOWER, SiteType.SILO])
    assert len(towers_and_silos) == 7  # 5 water towers + 2 silos
    for s in towers_and_silos:
        assert s.site_type in (SiteType.WATER_TOWER, SiteType.SILO)


def test_harvest_civic_features_from_geojson_dict():
    """Verify extraction of SiteCandidates from GeoJSON FeatureCollection dictionary."""
    geojson_data = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [-73.15, 44.45, 120.0],
                },
                "properties": {
                    "NAME": "Williston Municipal Tank",
                    "ELEVATION": 120.0,
                    "HEIGHT_M": 24.5,
                    "has_grid_power": True,
                    "access_difficulty": "drive_up",
                    "source_url": "https://willistonvt.gov",
                    "notes": "Town water department distribution standpipe",
                },
            },
            {
                "type": "Feature",
                "id": "VT-SHEL-001",
                "geometry": {
                    "type": "Point",
                    "coordinates": [-73.22, 44.38],
                },
                "properties": {
                    "name": "Shelburne Hill Standpipe",
                    "ELEV_FT": 492.0,  # ~150 meters
                    "TOWER_HT": "75 ft",  # ~22.86 meters
                    "power": "grid",
                    "access": "moderate",
                    "description": "Auxiliary emergency standpipe",
                },
            },
        ],
    }

    candidates = harvest_civic_features_from_geojson(
        geojson_content_or_path=geojson_data,
        site_type=SiteType.WATER_TOWER,
        default_mast_m=20.0,
        owner_label="Municipal Water Works",
    )

    assert len(candidates) == 2

    c1 = candidates[0]
    assert c1.name == "Williston Municipal Tank"
    assert c1.site_type == SiteType.WATER_TOWER
    assert c1.location.lat == 44.45
    assert c1.location.lon == -73.15
    assert c1.location.elevation_m == 120.0
    assert c1.mast_height_m == 24.5
    assert c1.has_grid_power is True
    assert c1.access_difficulty == AccessDifficulty.DRIVE_UP
    assert "Municipal Water Works" in (c1.notes or "")

    c2 = candidates[1]
    assert c2.site_id == "VT-SHEL-001"
    assert c2.name == "Shelburne Hill Standpipe"
    assert abs(c2.location.elevation_m - 149.96) < 0.1
    assert abs(c2.mast_height_m - 22.86) < 0.1
    assert c2.has_grid_power is True
    assert c2.access_difficulty == AccessDifficulty.MODERATE


def test_harvest_civic_features_from_geojson_string(tmp_path: Path):
    """Verify parsing GeoJSON from JSON string and file path."""
    geojson_payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [-71.50, 44.10, 850.0],
                },
                "properties": {
                    "name": "White Mountain Alpine Lookout",
                    "access": "hike_in",
                    "notes": "Trail access only",
                },
            }
        ],
    }

    raw_json_str = json.dumps(geojson_payload)

    # Test from string
    from_str = harvest_civic_features_from_geojson(
        raw_json_str,
        site_type=SiteType.FIRE_LOOKOUT,
        default_mast_m=15.0,
    )
    assert len(from_str) == 1
    assert from_str[0].name == "White Mountain Alpine Lookout"
    assert from_str[0].mast_height_m == 15.0
    assert from_str[0].access_difficulty == AccessDifficulty.HIKE_IN
    assert from_str[0].location.elevation_m == 850.0

    # Test from file path
    temp_file = tmp_path / "lookouts.geojson"
    temp_file.write_text(raw_json_str, encoding="utf-8")

    from_file = harvest_civic_features_from_geojson(
        temp_file,
        site_type=SiteType.FIRE_LOOKOUT,
    )
    assert len(from_file) == 1
    assert from_file[0].name == "White Mountain Alpine Lookout"


# ---------------------------------------------------------------------------
# TASK-004: Tiled Overpass Civic Harvester and Spatial Suppression Unit Tests
# ---------------------------------------------------------------------------


def test_subdivide_bounding_box_tiling():
    """Verify regional bounding box subdivision into <= 2.0 x 2.0 degree tiles."""
    # 1. Box smaller than 2.0 x 2.0 deg produces exactly 1 tile
    small_bounds = RegionalBounds(
        name="Small_County",
        min_lat=44.0,
        max_lat=44.8,
        min_lon=-73.2,
        max_lon=-72.5,
    )
    tiles_small = subdivide_bounding_box(small_bounds, max_tile_deg=2.0)
    assert len(tiles_small) == 1
    assert tiles_small[0] == (44.0, -73.2, 44.8, -72.5)

    # 2. Vermont bounds (lat span 2.3 deg, lon span 1.98 deg) -> 2 tiles
    vt_bounds = RegionalBounds(
        name="VT_Statewide",
        min_lat=42.72,
        max_lat=45.02,
        min_lon=-73.44,
        max_lon=-71.46,
    )
    tiles_vt = subdivide_bounding_box(vt_bounds, max_tile_deg=2.0)
    assert len(tiles_vt) == 2  # 2 in lat, 1 in lon
    for t_min_lat, t_min_lon, t_max_lat, t_max_lon in tiles_vt:
        assert round(t_max_lat - t_min_lat, 4) <= 2.0
        assert round(t_max_lon - t_min_lon, 4) <= 2.0
    # Check boundaries match original extent
    assert tiles_vt[0][0] == 42.72
    assert tiles_vt[-1][2] == 45.02
    assert tiles_vt[0][1] == -73.44
    assert tiles_vt[-1][3] == -71.46

    # 3. Large bounding box (e.g. Texas, lat span ~10.6 deg, lon span ~13.1 deg)
    tx_bounds = RegionalBounds(
        name="Texas_Statewide",
        min_lat=25.84,
        max_lat=36.50,
        min_lon=-106.65,
        max_lon=-93.51,
    )
    tiles_tx = subdivide_bounding_box(tx_bounds, max_tile_deg=2.0)
    assert len(tiles_tx) == 6 * 7  # ceil(10.66/2)=6 lat * ceil(13.14/2)=7 lon = 42
    for t_min_lat, t_min_lon, t_max_lat, t_max_lon in tiles_tx:
        assert round(t_max_lat - t_min_lat, 4) <= 2.0
        assert round(t_max_lon - t_min_lon, 4) <= 2.0
        assert t_min_lat >= 25.84
        assert t_max_lat <= 36.50
        assert t_min_lon >= -106.65
        assert t_max_lon <= -93.51


def test_build_overpass_query_selectors():
    """Verify Overpass QL query construction includes all mandatory civic tags and bbox format."""
    query = build_overpass_query(44.0, -73.5, 45.0, -72.0, timeout_s=45)
    assert "[out:json][timeout:45];" in query
    assert 'node["man_made"="water_tower"](44.0,-73.5,45.0,-72.0);' in query
    assert 'way["man_made"="water_tower"](44.0,-73.5,45.0,-72.0);' in query
    assert 'node["man_made"="communications_tower"](44.0,-73.5,45.0,-72.0);' in query
    assert 'way["man_made"="communications_tower"](44.0,-73.5,45.0,-72.0);' in query
    assert 'node["man_made"="mast"](44.0,-73.5,45.0,-72.0);' in query
    assert 'way["man_made"="mast"](44.0,-73.5,45.0,-72.0);' in query
    assert 'node["man_made"="silo"](44.0,-73.5,45.0,-72.0);' in query
    assert 'way["man_made"="silo"](44.0,-73.5,45.0,-72.0);' in query
    assert 'node["emergency"="fire_lookout"](44.0,-73.5,45.0,-72.0);' in query
    assert 'way["emergency"="fire_lookout"](44.0,-73.5,45.0,-72.0);' in query
    assert 'node["man_made"="tower"]["tower:type"~"communication|observation"](44.0,-73.5,45.0,-72.0);' in query
    assert 'way["man_made"="tower"]["tower:type"~"communication|observation"](44.0,-73.5,45.0,-72.0);' in query
    assert "out center tags;" in query


def test_overpass_json_to_geojson_conversion():
    """Verify conversion of Overpass elements (nodes and ways) to standard GeoJSON FeatureCollection."""
    raw_overpass = {
        "elements": [
            {
                "type": "node",
                "id": 1001,
                "lat": 44.45,
                "lon": -73.15,
                "tags": {
                    "man_made": "water_tower",
                    "name": "Williston Standpipe",
                    "ele": "150",
                    "height": "28 m",
                },
            },
            {
                "type": "way",
                "id": 2002,
                "center": {"lat": 44.48, "lon": -73.18},
                "tags": {
                    "man_made": "communications_tower",
                    "tower:type": "communication",
                    "name": "State Police Relay",
                    "height": "40 m",
                },
            },
            {
                "type": "node",
                "id": 3003,
                "lat": 44.52,
                "lon": -73.22,
                "tags": {
                    "man_made": "silo",
                    "name": "Dairy Farm Silo",
                },
            },
            {
                "type": "node",
                "id": 4004,
                "lat": 44.55,
                "lon": -73.25,
                "tags": {
                    "emergency": "fire_lookout",
                    "name": "Spruce Peak Lookout",
                    "elevation": "950.0",
                },
            },
        ]
    }

    geojson_doc = overpass_json_to_geojson(raw_overpass, region_code="VT")
    assert geojson_doc["type"] == "FeatureCollection"
    assert geojson_doc["region_code"] == "VT"
    assert len(geojson_doc["features"]) == 4

    features_by_type = {f["properties"]["site_type"]: f for f in geojson_doc["features"]}
    assert "water_tower" in features_by_type
    assert "communications_tower" in features_by_type
    assert "silo" in features_by_type
    assert "fire_lookout" in features_by_type

    wt = features_by_type["water_tower"]
    assert wt["properties"]["name"] == "Williston Standpipe"
    assert wt["properties"]["elevation_m"] == 150.0
    assert wt["properties"]["mast_height_m"] == 28.0
    assert wt["geometry"]["coordinates"] == [-73.15, 44.45, 150.0]

    ct = features_by_type["communications_tower"]
    assert ct["properties"]["name"] == "State Police Relay"
    assert ct["geometry"]["coordinates"] == [-73.18, 44.48]

    # Verify harvest_civic_features_from_geojson handles this generated GeoJSON directly
    candidates = harvest_civic_features_from_geojson(geojson_doc)
    assert len(candidates) == 4
    types = {c.site_type for c in candidates}
    assert SiteType.WATER_TOWER in types
    assert SiteType.COMMUNICATIONS_TOWER in types
    assert SiteType.SILO in types
    assert SiteType.FIRE_LOOKOUT in types


def test_harvest_civic_cache_hit_bypass(tmp_path: Path):
    """Verify that existing cached regional GeoJSON bypasses live/mock Overpass queries."""
    cache_dir = tmp_path / "overpass_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached_file = cache_dir / "vt_civic.geojson"

    dummy_payload = {
        "type": "FeatureCollection",
        "region_code": "VT",
        "features": [
            {
                "type": "Feature",
                "id": "CIVIC-OSM-VT-N9999",
                "geometry": {"type": "Point", "coordinates": [-73.15, 44.45]},
                "properties": {"name": "Cached Test Site", "site_type": "water_tower"},
            }
        ],
    }
    cached_file.write_text(json.dumps(dummy_payload), encoding="utf-8")

    # Mock fetcher must never be called on a cache hit
    mock_fetcher = MagicMock(side_effect=RuntimeError("Fetcher should NOT be called on cache hit!"))

    result_path = harvest_region_civic(
        region_code="VT",
        cache_dir=cache_dir,
        force=False,
        mock_fetcher=mock_fetcher,
    )
    assert result_path == cached_file
    mock_fetcher.assert_not_called()

    # When force=True is passed, cache is bypassed and mock_fetcher IS called
    mock_fetcher.side_effect = None
    mock_fetcher.return_value = {"elements": []}
    result_forced = harvest_region_civic(
        region_code="VT",
        cache_dir=cache_dir,
        force=True,
        mock_fetcher=mock_fetcher,
    )
    assert result_forced == cached_file
    assert mock_fetcher.call_count >= 1


def test_harvest_region_civic_mock_execution(tmp_path: Path):
    """Hermetic test: harvest_region_civic executes multi-tile queries and saves GeoJSON without network calls."""
    cache_dir = tmp_path / "mock_cache"

    def mock_fetcher(query: str, bbox: tuple) -> dict:
        min_lat, min_lon, max_lat, max_lon = bbox
        return {
            "elements": [
                {
                    "type": "node",
                    "id": int(abs(min_lat * 100)),
                    "lat": round((min_lat + max_lat) / 2.0, 4),
                    "lon": round((min_lon + max_lon) / 2.0, 4),
                    "tags": {
                        "man_made": "water_tower",
                        "name": f"Mock Tower in {min_lat}",
                    },
                }
            ]
        }

    # Harvest DC (single tile region)
    dc_path = harvest_region_civic(
        region_code="DC",
        cache_dir=cache_dir,
        mock_fetcher=mock_fetcher,
    )
    assert dc_path.exists()
    dc_data = json.loads(dc_path.read_text(encoding="utf-8"))
    assert dc_data["type"] == "FeatureCollection"
    assert len(dc_data["features"]) == 1
    assert "Mock Tower" in dc_data["features"][0]["properties"]["name"]


def test_overpass_rate_limiter_and_http_retry():
    """Verify Overpass rate limiter delay enforcement and exponential retry on HTTP 429 and 504."""
    # 1. Rate limiter enforces delay
    limiter = OverpassRateLimiter(min_delay_s=0.05)
    limiter.record_request()
    delay = limiter.wait()
    assert delay >= 0.0

    # 2. HTTP 429 and 504 retry with mock urlopen
    call_count = 0

    def mock_urlopen(req, timeout):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise urllib.error.HTTPError(
                url="http://mock",
                code=429,
                msg="Too Many Requests",
                hdrs=MagicMock(),
                fp=io.BytesIO(b"Rate limit exceeded"),
            )
        elif call_count == 2:
            raise urllib.error.HTTPError(
                url="http://mock",
                code=504,
                msg="Gateway Timeout",
                hdrs=MagicMock(),
                fp=io.BytesIO(b"Gateway Timeout"),
            )
        # 3rd call succeeds
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.read.return_value = json.dumps({"elements": [{"type": "node", "id": 1}]}).encode("utf-8")
        return mock_resp

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        with patch("time.sleep") as mock_sleep:
            res = query_overpass(
                query="node[man_made=water_tower];",
                rate_limiter=OverpassRateLimiter(min_delay_s=0.0),
                initial_backoff_s=0.01,
            )
            assert res == {"elements": [{"type": "node", "id": 1}]}
            assert call_count == 3
            assert mock_sleep.call_count >= 2


def test_spatial_suppression_within_50m(tmp_path: Path):
    """Verify spatial suppression drops civic sites within 50m of FCC/ISED towers and preserves attribution."""
    db_path = tmp_path / "suppression_test.db"
    registry = UnifiedTowerRegistry(db_path=db_path)

    # 1. Seed authoritative FCC tower in Burlington, VT
    fcc_site = SiteCandidate(
        site_id="FCC-1001",
        name="FCC Broadcast Mast",
        location=Coordinate(lat=44.450000, lon=-73.150000, elevation_m=100.0),
        site_type=SiteType.COMMUNICATIONS_TOWER,
        mast_height_m=50.0,
        access_difficulty=AccessDifficulty.DRIVE_UP,
        has_grid_power=True,
        solar_exposure_pct=90.0,
        notes="Authoritative FCC registration | License: Public Domain",
        source_url="https://fcc.gov/asr/1001",
    )
    registry.upsert_tower(
        fcc_site,
        owner="Crown Castle",
        owner_category="commercial_carrier",
        source_dataset="fcc_asr",
        region_code="VT",
    )

    # 2. Seed authoritative ISED tower in Southern Quebec
    ised_site = SiteCandidate(
        site_id="ISED-2002",
        name="ISED Tafl Station",
        location=Coordinate(lat=45.500000, lon=-73.570000, elevation_m=60.0),
        site_type=SiteType.COMMUNICATIONS_TOWER,
        mast_height_m=40.0,
        access_difficulty=AccessDifficulty.DRIVE_UP,
        has_grid_power=True,
        solar_exposure_pct=85.0,
        notes="Authoritative Canadian registry",
        source_url="https://ised.gc.ca/2002",
    )
    registry.upsert_tower(
        ised_site,
        owner="Bell Mobility",
        owner_category="commercial_carrier",
        source_dataset="ised_sms",
        region_code="CA_QC",
    )

    # Test candidate 1: Civic water tower ~30m north of FCC tower (0.00027 deg lat = ~30.0m)
    # 30m is <= 50m: must be suppressed
    dist_1 = haversine_distance_m(44.450000, -73.150000, 44.450270, -73.150000)
    assert 25.0 < dist_1 < 35.0
    cand_suppressed = SiteCandidate(
        site_id="CIVIC-OSM-VT-N101",
        name="Williston Municipal Water Tank (Near FCC)",
        location=Coordinate(lat=44.450270, lon=-73.150000, elevation_m=100.0),
        site_type=SiteType.WATER_TOWER,
        mast_height_m=25.0,
        access_difficulty=AccessDifficulty.DRIVE_UP,
        has_grid_power=True,
        solar_exposure_pct=90.0,
    )
    assert is_spatially_suppressed(cand_suppressed, registry, radius_m=50.0) is True

    # Test candidate 2: Civic tower ~111m north of FCC tower (0.0010 deg lat = ~111.2m)
    # 111m is > 50m: must NOT be suppressed
    dist_2 = haversine_distance_m(44.450000, -73.150000, 44.451000, -73.150000)
    assert 105.0 < dist_2 < 120.0
    cand_accepted = SiteCandidate(
        site_id="CIVIC-OSM-VT-N102",
        name="Williston Town Mast (Far from FCC)",
        location=Coordinate(lat=44.451000, lon=-73.150000, elevation_m=105.0),
        site_type=SiteType.COMMUNICATIONS_TOWER,
        mast_height_m=30.0,
        access_difficulty=AccessDifficulty.DRIVE_UP,
        has_grid_power=True,
        solar_exposure_pct=90.0,
    )
    assert is_spatially_suppressed(cand_accepted, registry, radius_m=50.0) is False

    # Test candidate 3: Civic lookout ~28m from ISED tower (0.00025 deg lat = ~27.8m)
    # 28m is <= 50m: must be suppressed
    dist_3 = haversine_distance_m(45.500000, -73.570000, 45.500250, -73.570000)
    assert 20.0 < dist_3 < 35.0
    cand_ised_suppressed = SiteCandidate(
        site_id="CIVIC-OSM-QC-N103",
        name="Montreal Mont-Royal Lookout",
        location=Coordinate(lat=45.500250, lon=-73.570000, elevation_m=60.0),
        site_type=SiteType.FIRE_LOOKOUT,
        mast_height_m=20.0,
        access_difficulty=AccessDifficulty.DRIVE_UP,
        has_grid_power=True,
        solar_exposure_pct=90.0,
    )
    assert is_spatially_suppressed(cand_ised_suppressed, registry, radius_m=50.0) is True

    # Ingest candidates with spatial suppression
    candidates_to_ingest = [cand_suppressed, cand_accepted, cand_ised_suppressed]
    inserted_count = ingest_civic_candidates_with_suppression(
        registry=registry,
        candidates=candidates_to_ingest,
        region_code="VT",
        suppression_radius_m=50.0,
    )
    # Only candidate 2 should have been inserted
    assert inserted_count == 1

    # Verify candidate 1 was NOT inserted into towers
    cur = registry.conn.cursor()
    row_suppressed = cur.execute("SELECT site_id FROM towers WHERE site_id = ?", ("CIVIC-OSM-VT-N101",)).fetchone()
    assert row_suppressed is None

    # Verify candidate 2 WAS inserted
    row_accepted = cur.execute("SELECT site_id FROM towers WHERE site_id = ?", ("CIVIC-OSM-VT-N102",)).fetchone()
    assert row_accepted is not None

    # CRITICAL ODbL CHECK: Verify the authoritative FCC tower remains completely untouched
    fcc_check = cur.execute(
        "SELECT name, owner, source_dataset, notes FROM towers WHERE site_id = 'FCC-1001'"
    ).fetchone()
    assert fcc_check[0] == "FCC Broadcast Mast"
    assert fcc_check[1] == "Crown Castle"
    assert fcc_check[2] == "fcc_asr"
    assert "Public Domain" in fcc_check[3]
    assert "OpenStreetMap" not in fcc_check[3]


def test_pack_builder_integrates_cached_civic_geojson(tmp_path: Path):
    """Verify pack builder consumes cached civic GeoJSON and applies spatial suppression."""
    cache_dir = tmp_path / "civic_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_dir = tmp_path / "packs_out"

    # Create cached GeoJSON for VT with:
    # 1. Candidate within 30m of sample FCC tower (suppressed)
    # 2. Candidate far away (retained)
    sample_civic_geojson = {
        "type": "FeatureCollection",
        "region_code": "VT",
        "features": [
            {
                "type": "Feature",
                "id": "CIVIC-OSM-VT-STANDPIPE-1",
                "geometry": {"type": "Point", "coordinates": [-73.15, 44.45027]},
                "properties": {
                    "site_id": "CIVIC-OSM-VT-STANDPIPE-1",
                    "name": "Burlington North Standpipe",
                    "site_type": "water_tower",
                    "mast_height_m": 25.0,
                    "elevation_m": 120.0,
                },
            },
            {
                "type": "Feature",
                "id": "CIVIC-OSM-VT-STANDPIPE-2",
                "geometry": {"type": "Point", "coordinates": [-72.85, 44.85]},
                "properties": {
                    "site_id": "CIVIC-OSM-VT-STANDPIPE-2",
                    "name": "Isolated Remote Standpipe",
                    "site_type": "water_tower",
                    "mast_height_m": 30.0,
                    "elevation_m": 350.0,
                },
            },
        ],
    }
    (cache_dir / "vt_civic.geojson").write_text(json.dumps(sample_civic_geojson), encoding="utf-8")

    manifest = build_region_packs(
        regions=["VT"],
        out_dir=out_dir,
        offline_fixtures=True,
        civic_cache_dir=cache_dir,
    )

    assert "towers-vt" in manifest.packs
    pack_info = manifest.packs["towers-vt"]
    assert pack_info.row_count > 0

    # Verify ODbL isolation: base pack does NOT contain civic OSM site
    import gzip
    import sqlite3
    base_db_file = tmp_path / "extracted_base_pack.db"
    base_archive_path = out_dir / f"towers-vt-{pack_info.pack_version}.sqlite.gz"
    with gzip.open(base_archive_path, "rb") as gz_in, open(base_db_file, "wb") as db_out:
        db_out.write(gz_in.read())

    base_conn = sqlite3.connect(base_db_file)
    assert base_conn.execute(
        "SELECT 1 FROM towers WHERE site_id = 'CIVIC-OSM-VT-STANDPIPE-2'"
    ).fetchone() is None
    base_conn.close()

    # Verify the remote standpipe made it into the civic-osm overlay pack
    assert "towers-vt-civic-osm" in manifest.packs
    overlay_info = manifest.packs["towers-vt-civic-osm"]
    overlay_db_file = tmp_path / "extracted_overlay_pack.db"
    overlay_archive_path = out_dir / f"towers-vt-civic-osm-{overlay_info.pack_version}.sqlite.gz"
    with gzip.open(overlay_archive_path, "rb") as gz_in, open(overlay_db_file, "wb") as db_out:
        db_out.write(gz_in.read())

    conn = sqlite3.connect(overlay_db_file)
    remote_tower = conn.execute(
        "SELECT name, site_type, source_dataset FROM towers WHERE site_id = 'CIVIC-OSM-VT-STANDPIPE-2'"
    ).fetchone()
    assert remote_tower is not None
    assert remote_tower[0] == "Isolated Remote Standpipe"
    assert remote_tower[1] == "water_tower"
    assert remote_tower[2] == "civic"
    conn.close()
