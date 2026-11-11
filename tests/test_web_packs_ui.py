"""Tests for MeshScout web packs UI, map density clustering, and ODbL attribution.

Verifies:
  - Screen-space grid clustering performance (< 1.0s on 5,000 synthetic coordinates)
  - Exact cluster and point count sum conservation (sum == visible_count)
  - Conformal geodetic bounds fitting math
  - ODbL 1.0 license attribution chip presence and conditional visibility
  - Regional packs Tab 8 UI attributes (file size, site count, license tags, zoom button)
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import random
import time
from typing import List, Tuple

import pytest
from fastapi.testclient import TestClient

from meshscout.web.app import create_web_app
from meshscout.web.clustering import (
    cluster_points_screen_grid,
    normalize_conformal_bounds,
    project_lat_lon,
)


@pytest.fixture()
def temp_db_path(tmp_path: Path) -> Path:
    """Provide an isolated temporary SQLite database path per test."""
    return tmp_path / "test_workbench.db"


@pytest.fixture()
def client(temp_db_path: Path) -> TestClient:
    """Create a FastAPI TestClient backed by an isolated database."""
    app = create_web_app(db_path=temp_db_path)
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. High-Density Clustering on 5,000 Synthetic Coordinates
# ---------------------------------------------------------------------------

def test_clustering_performance_and_exact_sum_on_5000_coordinates() -> None:
    """Verify clustering algorithm completes in < 1.0s on 5,000 synthetic coordinates and sums exactly to 5,000."""
    rng = random.Random(42)
    # Generate 5,000 coordinates in a realistic regional boundary (e.g. VT/NY/NH)
    bounds = {
        "min_lat": 42.7,
        "max_lat": 45.1,
        "min_lon": -73.5,
        "max_lon": -71.5,
    }

    synthetic_points: List[Tuple[float, float]] = []
    for _ in range(5000):
        lat = rng.uniform(bounds["min_lat"] + 0.05, bounds["max_lat"] - 0.05)
        lon = rng.uniform(bounds["min_lon"] + 0.05, bounds["max_lon"] - 0.05)
        synthetic_points.append((lat, lon))

    start = time.perf_counter()
    result = cluster_points_screen_grid(
        synthetic_points,
        width=900.0,
        height=440.0,
        cell_size=40.0,
        bounds=bounds,
    )
    elapsed = time.perf_counter() - start

    # Requirement 1: completes in < 1.0s
    assert elapsed < 1.0, f"Clustering took {elapsed:.4f}s, exceeding 1.0s threshold"

    # Requirement 2: total cluster counts and individual point counts sum exactly to 5,000
    visible_count = result["visible_count"]
    assert visible_count == 5000, f"Expected 5000 visible points, got {visible_count}"

    clusters = result["clusters"]
    points = result["points"]
    total_cluster_badge_counts = sum(c["count"] for c in clusters)
    total_sum = total_cluster_badge_counts + len(points)

    assert total_sum == 5000, (
        f"Sum mismatch: clusters ({total_cluster_badge_counts}) + "
        f"individual points ({len(points)}) = {total_sum}, expected 5000"
    )
    assert result["clustered_sum"] == 5000

    # Ensure clusters are formed
    assert len(clusters) > 0, "High density 5,000 points should form multiple clusters"
    for c in clusters:
        assert c["count"] > 1, "Cluster bubbles must contain more than 1 point"
        assert 0.0 <= c["cx"] <= 900.0, f"Cluster cx ({c['cx']}) outside viewport width"
        assert 0.0 <= c["cy"] <= 440.0, f"Cluster cy ({c['cy']}) outside viewport height"


def test_clustering_edge_cases() -> None:
    """Verify clustering handles empty inputs and single isolated points correctly."""
    # Empty input
    res_empty = cluster_points_screen_grid([])
    assert res_empty["visible_count"] == 0
    assert res_empty["clustered_sum"] == 0
    assert len(res_empty["clusters"]) == 0
    assert len(res_empty["points"]) == 0

    # Single point
    single = [(44.4759, -73.2121)]
    res_single = cluster_points_screen_grid(single)
    assert res_single["visible_count"] == 1
    assert res_single["clustered_sum"] == 1
    assert len(res_single["clusters"]) == 0
    assert len(res_single["points"]) == 1
    assert res_single["points"][0]["lat"] == pytest.approx(44.4759)

    # Two co-located points
    colocated = [(44.4759, -73.2121), (44.4759, -73.2121)]
    res_colocated = cluster_points_screen_grid(colocated)
    assert res_colocated["visible_count"] == 2
    assert res_colocated["clustered_sum"] == 2
    assert len(res_colocated["clusters"]) == 1
    assert res_colocated["clusters"][0]["count"] == 2
    assert len(res_colocated["points"]) == 0


# ---------------------------------------------------------------------------
# 2. Conformal Geodetic Bounds Fitting Math
# ---------------------------------------------------------------------------

def test_bounds_fitting_math_preserves_extents_and_aspect_ratio() -> None:
    """Verify normalize_conformal_bounds ensures 1:1 metric aspect ratio and encloses target box."""
    raw = {
        "min_lat": 42.7268,
        "max_lat": 45.0167,
        "min_lon": -73.4379,
        "max_lon": -71.5033,
    }

    norm = normalize_conformal_bounds(raw, width=900.0, height=440.0, pad_x=42.0, pad_y=28.0)

    # 1. Output must strictly enclose raw input bounds
    assert norm["min_lat"] <= raw["min_lat"], "Normalized min_lat must be <= raw min_lat"
    assert norm["max_lat"] >= raw["max_lat"], "Normalized max_lat must be >= raw max_lat"
    assert norm["min_lon"] <= raw["min_lon"], "Normalized min_lon must be <= raw min_lon"
    assert norm["max_lon"] >= raw["max_lon"], "Normalized max_lon must be >= raw max_lon"

    # 2. Centroid alignment
    center_lat_raw = (raw["min_lat"] + raw["max_lat"]) / 2.0
    center_lon_raw = (raw["min_lon"] + raw["max_lon"]) / 2.0
    center_lat_norm = (norm["min_lat"] + norm["max_lat"]) / 2.0
    center_lon_norm = (norm["min_lon"] + norm["max_lon"]) / 2.0
    assert center_lat_norm == pytest.approx(center_lat_raw, abs=1e-5)
    assert center_lon_norm == pytest.approx(center_lon_raw, abs=1e-5)

    # 3. Conformal aspect ratio check
    usable_w = 900.0 - 42.0 * 2.0
    usable_h = 440.0 - 28.0 * 2.0
    cos_phi = math.cos(math.radians(center_lat_norm))
    norm_span_lat = norm["max_lat"] - norm["min_lat"]
    norm_span_lon_eq = (norm["max_lon"] - norm["min_lon"]) * cos_phi

    ratio = (usable_w / norm_span_lon_eq) / (usable_h / norm_span_lat)
    assert ratio == pytest.approx(1.0, rel=1e-4), "Conformal scale must be 1:1 between lat and eq-lon"


def test_project_lat_lon_within_screen_bounds() -> None:
    """Verify projection corners map accurately to padded canvas viewport."""
    bounds = {
        "min_lat": 40.0,
        "max_lat": 50.0,
        "min_lon": -80.0,
        "max_lon": -70.0,
    }
    w, h, px, py = 900.0, 440.0, 40.0, 20.0

    # Top-left (max_lat, min_lon) -> (px, py)
    tl_x, tl_y = project_lat_lon(50.0, -80.0, bounds, w, h, px, py)
    assert tl_x == pytest.approx(px)
    assert tl_y == pytest.approx(py)

    # Bottom-right (min_lat, max_lon) -> (w - px, h - py)
    br_x, br_y = project_lat_lon(40.0, -70.0, bounds, w, h, px, py)
    assert br_x == pytest.approx(w - px)
    assert br_y == pytest.approx(h - py)


# ---------------------------------------------------------------------------
# 3. Attribution Presence & ODbL Badge Verification
# ---------------------------------------------------------------------------

def test_attribution_presence_in_html_and_css(client: TestClient) -> None:
    """Verify ODbL 1.0 attribution chip is present in index.html and styles.css."""
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text

    # Attribution chip element in DOM
    assert 'id="odbl-attribution-chip"' in html
    assert "OpenStreetMap contributors (ODbL 1.0)" in html

    # Regional packs tab in DOM
    assert 'id="tab-packs"' in html
    assert 'id="installed-packs-list"' in html
    assert 'id="available-packs-list"' in html

    # Stylesheet checks
    css_resp = client.get("/static/styles.css")
    assert css_resp.status_code == 200
    css = css_resp.text
    assert ".odbl-attribution-chip" in css
    assert ".pack-badge-license" in css
    assert ".tower-cluster-marker" in css


def test_app_js_clustering_and_zoom_features(client: TestClient) -> None:
    """Verify app.js contains screen-space grid clustering, zoom-to-pack, and ODbL attribution handling."""
    resp = client.get("/static/app.js")
    assert resp.status_code == 200
    js = resp.text

    # Zoom to pack functionality
    assert "zoomToPackBounds" in js
    assert "zoom-pack-btn" in js
    assert "Zoom to pack" in js

    # Screen-space grid clustering logic
    assert "tower-cluster-marker" in js
    assert "visibleTowers.length > 1000" in js
    assert "data-cluster-count" in js

    # ODbL Attribution logic
    assert "odbl-attribution-chip" in js
    assert "hasVisibleCivic" in js
    assert "extractPackLicenses" in js


# ---------------------------------------------------------------------------
# 4. Regional Packs API Endpoint Integrity
# ---------------------------------------------------------------------------

def test_packs_api_returns_license_and_bounds_metadata(client: TestClient) -> None:
    """Verify /api/v1/packs response structure includes licenses, site counts, and bounding boxes."""
    resp = client.get("/api/v1/packs")
    assert resp.status_code == 200
    data = resp.json()

    assert data["ok"] is True
    assert "installed" in data
    assert "available" in data

    # Verify installed packs list structure
    installed = data["installed"]
    assert isinstance(installed, list)
    for p in installed:
        assert "pack_id" in p
        assert "region_code" in p
        assert "row_count" in p or "site_count" in p
        assert "licenses" in p
        assert "bounds" in p

    # Verify available packs list structure
    available = data["available"]
    assert isinstance(available, list)
    for p in available:
        assert "pack_id" in p
        assert "region_code" in p
        assert "row_count" in p or "site_count" in p
        assert "licenses" in p
        assert "bounds" in p
