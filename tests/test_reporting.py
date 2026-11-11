"""Unit tests for MeshScout Deployment Dossier Generator and RFC 7946 GeoJSON Exporter."""

from __future__ import annotations

import json

from meshscout.core.contracts import (
    AccessDifficulty,
    Coordinate,
    LinkBudgetResult,
    SiteCandidate,
    SiteType,
)
from meshscout.core.optimizer import (
    RepeaterSelectionStep,
    SetCoverOptimizationResult,
)
from meshscout.core.scorer import (
    DesenseRiskLevel,
    EmitterSpec,
    score_site_viability,
)
from meshscout.reporting import (
    export_geojson_feature_collection,
    generate_deployment_dossier_markdown,
    generate_landowner_pitch_html,
    generate_portable_workbench_html,
)


def _sample_sites() -> tuple[SiteCandidate, SiteCandidate]:
    mansfield = SiteCandidate(
        site_id="VT-MANS-01",
        name="Mount Mansfield Ridge",
        location=Coordinate(lat=44.5437, lon=-72.8143, elevation_m=1339.0),
        site_type=SiteType.MOUNTAIN_PEAK,
        mast_height_m=15.0,
        has_grid_power=True,
        solar_exposure_pct=95.0,
        access_difficulty=AccessDifficulty.DRIVE_UP,
    )
    essex_wt = SiteCandidate(
        site_id="VT-ESSX-WT1",
        name="Essex Municipal Water Tower",
        location=Coordinate(lat=44.4906, lon=-73.1112, elevation_m=150.0),
        site_type=SiteType.WATER_TOWER,
        mast_height_m=22.0,
        has_grid_power=True,
        solar_exposure_pct=100.0,
        access_difficulty=AccessDifficulty.DRIVE_UP,
    )
    return mansfield, essex_wt


def _sample_link() -> LinkBudgetResult:
    return LinkBudgetResult(
        source_id="VT-MANS-01",
        target_id="VT-ESSX-WT1",
        distance_km=24.3,
        free_space_loss_db=119.38,
        diffraction_loss_db=0.0,
        total_path_loss_db=119.38,
        rx_power_dbm=-91.38,
        link_margin_db=43.62,
        has_line_of_sight=True,
        fresnel_clearance_ratio=3.42,
    )


class TestGeoJsonExport:
    """Tests for RFC 7946 GeoJSON FeatureCollection export."""

    def test_export_geojson_points_and_linestrings(self) -> None:
        s1, s2 = _sample_sites()
        link = _sample_link()

        v1 = score_site_viability(s1).value
        v2 = score_site_viability(s2).value
        assert v1 is not None and v2 is not None

        geojson = export_geojson_feature_collection(
            sites=[s1, s2],
            viability_scores={s1.site_id: v1, s2.site_id: v2},
            links=[link],
        )

        # Verify JSON serializability and RFC 7946 structure
        encoded = json.dumps(geojson)
        decoded = json.loads(encoded)
        assert decoded["type"] == "FeatureCollection"
        assert len(decoded["features"]) == 3

        point_features = [f for f in decoded["features"] if f["geometry"]["type"] == "Point"]
        line_features = [f for f in decoded["features"] if f["geometry"]["type"] == "LineString"]
        assert len(point_features) == 2
        assert len(line_features) == 1

        # Verify [lon, lat, elevation_m] coordinate ordering
        mans_feat = next(f for f in point_features if f["id"] == "VT-MANS-01")
        assert mans_feat["geometry"]["coordinates"] == [-72.8143, 44.5437, 1339.0]
        assert mans_feat["properties"]["site_type"] == "mountain_peak"
        assert mans_feat["properties"]["composite_score"] == v1.composite_score

        link_feat = line_features[0]
        assert link_feat["geometry"]["coordinates"] == [
            [-72.8143, 44.5437, 1339.0],
            [-73.1112, 44.4906, 150.0],
        ]
        assert link_feat["properties"]["link_margin_db"] == 43.62
        assert link_feat["properties"]["has_line_of_sight"] is True


class TestDeploymentDossierMarkdown:
    """Tests for Markdown field deployment dossier generation."""

    def test_generate_deployment_dossier_includes_tables_and_mermaid(self) -> None:
        s1, s2 = _sample_sites()
        link = _sample_link()

        # Co-locate a high-power 930 MHz paging emitter near s2 to verify cavity filter reporting
        emitter = EmitterSpec(
            emitter_id="WPVT-930",
            location=s2.location,
            frequency_mhz=930.0,
            erp_watts=400.0,
            service_type="paging",
        )
        v1 = score_site_viability(s1).value
        v2 = score_site_viability(s2, nearby_emitters=[emitter]).value
        assert v1 is not None and v2 is not None
        assert v2.requires_cavity_filter is True
        assert v2.desense_risk in (DesenseRiskLevel.HIGH, DesenseRiskLevel.CRITICAL)

        opt = SetCoverOptimizationResult(
            selected_sites=[s1, s2],
            selection_steps=[
                RepeaterSelectionStep(
                    step=1,
                    site=s1,
                    newly_covered_target_ids=["G1", "G2", "G3"],
                    newly_covered_weight=3.0,
                    cost=0.85,
                    efficiency_score=3.5294,
                    cumulative_coverage_fraction=0.75,
                    cumulative_weighted_coverage_fraction=0.75,
                ),
                RepeaterSelectionStep(
                    step=2,
                    site=s2,
                    newly_covered_target_ids=["G4"],
                    newly_covered_weight=1.0,
                    cost=0.85,
                    efficiency_score=1.1765,
                    cumulative_coverage_fraction=1.0,
                    cumulative_weighted_coverage_fraction=1.0,
                ),
            ],
            total_targets=4,
            covered_target_ids=["G1", "G2", "G3", "G4"],
            uncovered_target_ids=[],
            achieved_coverage_fraction=1.0,
            achieved_weighted_coverage_fraction=1.0,
            target_coverage_threshold=0.90,
            threshold_met=True,
            total_cost=1.70,
        )

        mermaid_seq = "sequenceDiagram\n    Orchestrator->>Subagent-ITM: Claim TASK-1004\n    Subagent-ITM-->>Orchestrator: Done"

        md = generate_deployment_dossier_markdown(
            region_name="Chittenden County, VT",
            optimization=opt,
            viability_scores=[v2, v1],
            links=[link],
            swarm_mermaid_diagram=mermaid_seq,
        )

        assert "# MeshScout Field Deployment Dossier: Chittenden County, VT" in md
        assert "## 1. Executive Summary" in md
        assert "## 2. Selected Repeater High-Site Schedule" in md
        assert "## 3. RF Co-Location and Hardware Readiness" in md
        assert "## 4. Point-to-Point Backhaul Link Budget Summary" in md
        assert "## 5. StigmeRig Swarm Telemetry" in md
        assert "VT-MANS-01" in md
        assert "VT-ESSX-WT1" in md
        assert "902-928 MHz bandpass cavity filter" in md
        assert "```mermaid" in md
        assert "Orchestrator->>Subagent-ITM: Claim TASK-1004" in md


class TestLandownerPitchHtml:
    """Tests for 1-page printable civic landowner pitch HTML generator."""

    def test_generate_landowner_pitch_html_contains_reassurances_and_metrics(self) -> None:
        _, essex_wt = _sample_sites()
        viability = score_site_viability(essex_wt).value
        assert viability is not None

        pitch_html = generate_landowner_pitch_html(
            site=essex_wt,
            viability=viability,
            hardware_label="RAK4631 Solar Repeater (1-Watt Enclosed Box)",
            coverage_gain_pct=42.5,
            contact_org="Chittenden County Mesh Resilience Group",
        )

        assert pitch_html.startswith("<!DOCTYPE html>")
        assert "</html>" in pitch_html
        assert "@media print" in pitch_html
        assert (
            "Civic Emergency Communications Host Brief — Essex Municipal Water Tower (VT-ESSX-WT1)"
            in pitch_html
        )
        assert "150m ASL" in pitch_html
        assert "22m AGL" in pitch_html
        assert "+42.5%" in pitch_html
        assert "FCC Part 15" in pitch_html
        assert "Zero Grid Power" in pitch_html
        assert "non-penetrating stainless hose/pipe clamps" in pitch_html
        assert "Chittenden County Mesh Resilience Group" in pitch_html
        assert f"{viability.composite_score:.1f}" in pitch_html


class TestPortableWorkbenchHtml:
    """Tests for self-contained single-file portable workbench HTML generator."""

    def test_generate_portable_workbench_html_embeds_sites_svg_and_links(self) -> None:
        s1, s2 = _sample_sites()
        link = _sample_link()

        workbench_html = generate_portable_workbench_html(
            region_name="Chittenden County, VT",
            sites=[s1, s2],
            links=[link],
            home_summary={"Home ZIP": "05452", "Best High Site": "VT-ESSX-WT1"},
        )

        assert workbench_html.startswith("<!DOCTYPE html>")
        assert "</html>" in workbench_html
        assert "<svg" in workbench_html
        assert "Chittenden County, VT" in workbench_html
        assert "VT-MANS-01" in workbench_html
        assert "Mount Mansfield Ridge" in workbench_html
        assert "VT-ESSX-WT1" in workbench_html
        assert "Essex Municipal Water Tower" in workbench_html
        assert "24.30 km" in workbench_html
        assert "43.6 dB" in workbench_html
        assert "05452" in workbench_html


class TestGpxAndKmlExport:
    """Tests for GPX 1.1 waypoints and KML 2.2 network export."""

    def test_export_gpx_waypoints_structure(self) -> None:
        from meshscout.reporting import export_gpx_waypoints

        s1, s2 = _sample_sites()
        home = Coordinate(lat=44.4906, lon=-73.1112, elevation_m=108.0)
        gpx = export_gpx_waypoints([s1, s2], include_home=home, home_name="My Essex Home")

        assert gpx.startswith('<?xml version="1.0" encoding="UTF-8"?>')
        assert "<gpx" in gpx
        assert "</gpx>" in gpx
        assert "<wpt lat=\"44.543700\" lon=\"-72.814300\">" in gpx
        assert "<name>Mount Mansfield Ridge [VT-MANS-01]</name>" in gpx
        assert "<name>My Essex Home</name>" in gpx
        assert "<ele>108.0</ele>" in gpx

    def test_export_kml_document_structure(self) -> None:
        from meshscout.reporting import export_kml_document

        s1, s2 = _sample_sites()
        home = Coordinate(lat=44.4906, lon=-73.1112, elevation_m=108.0)
        kml = export_kml_document(
            sites=[s1, s2],
            active_links=[(s1, s2, 18.5)],
            include_home=home,
            home_name="My Essex Home",
        )

        assert kml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
        assert "<kml" in kml
        assert "</kml>" in kml
        assert "<Placemark>" in kml
        assert "Mount Mansfield Ridge [VT-MANS-01]" in kml
        assert "<LineString>" in kml
        assert "Estimated Link Margin: +18.5 dB" in kml

    def test_generate_link_survey_html_structure(self) -> None:
        from meshscout.core.contracts import DowntiltAnalysisResult, RadioConfig
        from meshscout.reporting import generate_link_survey_html

        s1, s2 = _sample_sites()
        link = LinkBudgetResult(
            source_id=s1.site_id,
            target_id=s2.site_id,
            distance_km=14.5,
            free_space_loss_db=114.5,
            diffraction_loss_db=6.0,
            total_path_loss_db=120.5,
            rx_power_dbm=-98.5,
            link_margin_db=35.5,
            has_line_of_sight=True,
            fresnel_clearance_ratio=1.45,
            downtilt_analysis=DowntiltAnalysisResult(
                look_down_angle_deg=2.4,
                vertical_beamwidth_deg=16.0,
                is_overshooting=False,
                margin_loss_db=0.0,
                recommendation="Aligned within beamwidth",
            ),
        )
        radio = RadioConfig(tx_power_dbm=22.0, antenna_gain_dbi=5.8)
        html_doc = generate_link_survey_html(source=s1, target=s2, link=link, radio=radio)

        assert "<!DOCTYPE html>" in html_doc
        assert "RF Link Engineering Survey Dossier" in html_doc
        assert "VT-MANS-01" in html_doc
        assert "14.50 km" in html_doc
        assert "+35.5 dB" in html_doc
        assert "Look-Down Angle:" in html_doc
        assert "2.40°" in html_doc
        assert "CLEAR LINE-OF-SIGHT" in html_doc
        assert "Field Deployment Pre-Flight Checklist" in html_doc


