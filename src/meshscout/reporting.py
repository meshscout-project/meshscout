"""Deployment Dossier Markdown Generator and RFC 7946 GeoJSON Exporter for MeshScout."""

from __future__ import annotations

import html
from typing import Any, Dict, List, Optional, Sequence

from meshscout.core.contracts import (
    Coordinate,
    LinkBudgetResult,
    RadioConfig,
    SiteCandidate,
)
from meshscout.core.optimizer import SetCoverOptimizationResult
from meshscout.core.scorer import SiteViabilityScore, score_site_viability


def export_geojson_feature_collection(
    sites: Sequence[SiteCandidate],
    viability_scores: Optional[Dict[str, SiteViabilityScore]] = None,
    links: Sequence[LinkBudgetResult] = (),
    site_lookup: Optional[Dict[str, SiteCandidate]] = None,
) -> Dict[str, Any]:
    """Generate an RFC 7946 compliant GeoJSON FeatureCollection for sites and RF links.

    Point features use `[lon, lat, elevation_m]` coordinate order and embed site
    viability and desense metadata. LineString features represent point-to-point RF
    links between resolved sites.
    """
    score_map: Dict[str, SiteViabilityScore] = viability_scores or {}
    lookup: Dict[str, SiteCandidate] = {s.site_id: s for s in sites}
    if site_lookup:
        lookup.update(site_lookup)

    features: List[Dict[str, Any]] = []

    for site in sites:
        v_score = score_map.get(site.site_id)
        props: Dict[str, Any] = {
            "feature_kind": "repeater_site",
            "site_id": site.site_id,
            "name": site.name,
            "site_type": site.site_type.value,
            "mast_height_m": site.mast_height_m,
            "has_grid_power": site.has_grid_power,
            "solar_exposure_pct": site.solar_exposure_pct,
            "access_difficulty": site.access_difficulty.value,
            "composite_score": v_score.composite_score if v_score else None,
            "access_and_ownership_score": v_score.access_and_ownership_score if v_score else None,
            "structural_and_power_score": v_score.structural_and_power_score if v_score else None,
            "rf_cleanliness_score": v_score.rf_cleanliness_score if v_score else None,
            "desense_risk": v_score.desense_risk.value if v_score else None,
            "requires_cavity_filter": v_score.requires_cavity_filter if v_score else None,
            "recommended_hardware_notes": v_score.recommended_hardware_notes if v_score else [],
        }
        features.append(
            {
                "type": "Feature",
                "id": site.site_id,
                "geometry": {
                    "type": "Point",
                    "coordinates": [
                        site.location.lon,
                        site.location.lat,
                        site.location.elevation_m,
                    ],
                },
                "properties": props,
            }
        )

    for link in links:
        src = lookup.get(link.source_id)
        dst = lookup.get(link.target_id)
        if src is None or dst is None:
            continue
        link_id = f"LINK-{link.source_id}-{link.target_id}"
        features.append(
            {
                "type": "Feature",
                "id": link_id,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [src.location.lon, src.location.lat, src.location.elevation_m],
                        [dst.location.lon, dst.location.lat, dst.location.elevation_m],
                    ],
                },
                "properties": {
                    "feature_kind": "rf_link",
                    "source_id": link.source_id,
                    "target_id": link.target_id,
                    "distance_km": link.distance_km,
                    "free_space_loss_db": link.free_space_loss_db,
                    "diffraction_loss_db": link.diffraction_loss_db,
                    "total_path_loss_db": link.total_path_loss_db,
                    "rx_power_dbm": link.rx_power_dbm,
                    "link_margin_db": link.link_margin_db,
                    "has_line_of_sight": link.has_line_of_sight,
                    "fresnel_clearance_ratio": link.fresnel_clearance_ratio,
                },
            }
        )

    return {
        "type": "FeatureCollection",
        "features": features,
    }


def generate_deployment_dossier_markdown(
    region_name: str,
    optimization: SetCoverOptimizationResult,
    viability_scores: Sequence[SiteViabilityScore],
    links: Sequence[LinkBudgetResult] = (),
    swarm_mermaid_diagram: Optional[str] = None,
) -> str:
    """Render an actionable Markdown field deployment dossier for regional mesh rollout."""
    lines: List[str] = []
    achieved_pct = round(optimization.achieved_weighted_coverage_fraction * 100.0, 1)
    target_pct = round(optimization.target_coverage_threshold * 100.0, 1)
    status_label = "MET" if optimization.threshold_met else "PARTIAL"

    lines.append(f"# MeshScout Field Deployment Dossier: {region_name}")
    lines.append("")
    lines.append("## 1. Executive Summary")
    lines.append("")
    lines.append(f"This dossier defines the high-site repeater topology for {region_name}.")
    lines.append(
        f"The selected repeater network achieves {achieved_pct}% weighted basin coverage against a {target_pct}% target ({status_label})."
    )
    lines.append("")
    lines.append(f"- **Target Region**: {region_name}")
    lines.append(f"- **Selected Repeaters**: {len(optimization.selected_sites)}")
    lines.append(
        f"- **Covered Basin Grid Points**: {len(optimization.covered_target_ids)} / {optimization.total_targets}"
    )
    lines.append(f"- **Weighted Coverage Achieved**: {achieved_pct}% (Target: {target_pct}%)")
    lines.append(f"- **Total Deployment Cost Index**: {optimization.total_cost:.2f}")
    lines.append("")

    lines.append("## 2. Selected Repeater High-Site Schedule")
    lines.append("")
    lines.append(
        "| Step | Site ID | Name | Type | Coordinates (Lat, Lon) | Elev (m) | Mast (m) | Access | Cumulative Coverage |"
    )
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    if optimization.selection_steps:
        for step in optimization.selection_steps:
            s = step.site
            cum_pct = round(step.cumulative_weighted_coverage_fraction * 100.0, 1)
            lines.append(
                f"| {step.step} | `{s.site_id}` | {s.name} | `{s.site_type.value}` | "
                f"{s.location.lat:.4f}, {s.location.lon:.4f} | {s.location.elevation_m:.1f} | "
                f"{s.mast_height_m:.1f} | `{s.access_difficulty.value}` | {cum_pct}% |"
            )
    else:
        for idx, s in enumerate(optimization.selected_sites, start=1):
            lines.append(
                f"| {idx} | `{s.site_id}` | {s.name} | `{s.site_type.value}` | "
                f"{s.location.lat:.4f}, {s.location.lon:.4f} | {s.location.elevation_m:.1f} | "
                f"{s.mast_height_m:.1f} | `{s.access_difficulty.value}` | {achieved_pct}% |"
            )
    lines.append("")

    lines.append("## 3. RF Co-Location and Hardware Readiness")
    lines.append("")
    lines.append(
        "Civic assets such as water towers and silos rank above commercial telecom towers."
    )
    lines.append(
        "Sites near high-power 850-940 MHz transmitters require bandpass cavity filters."
    )
    lines.append("")
    lines.append(
        "| Site ID | Viability Score | Ownership Score | RF Cleanliness | Desense Risk | Cavity Filter | Hardware Notes |"
    )
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    for vs in viability_scores:
        cavity_str = "YES" if vs.requires_cavity_filter else "NO"
        notes_str = "; ".join(vs.recommended_hardware_notes) if vs.recommended_hardware_notes else "Standard LoRa deployment"
        lines.append(
            f"| `{vs.site.site_id}` | {vs.composite_score:.1f} | {vs.access_and_ownership_score:.1f} | "
            f"{vs.rf_cleanliness_score:.1f} | `{vs.desense_risk.value}` | **{cavity_str}** | {notes_str} |"
        )
    lines.append("")

    lines.append("## 4. Point-to-Point Backhaul Link Budget Summary")
    lines.append("")
    if links:
        lines.append(
            "| Source | Target | Distance (km) | Path Loss (dB) | RX Power (dBm) | Link Margin (dB) | LOS | Fresnel Ratio |"
        )
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for lk in links:
            los_str = "CLEAR" if lk.has_line_of_sight else "OBSTRUCTED"
            lines.append(
                f"| `{lk.source_id}` | `{lk.target_id}` | {lk.distance_km:.2f} | "
                f"{lk.total_path_loss_db:.1f} | {lk.rx_power_dbm:.1f} | "
                f"{lk.link_margin_db:.1f} | {los_str} | {lk.fresnel_clearance_ratio:.2f} |"
            )
    else:
        lines.append("No point-to-point backhaul links were evaluated for this run.")
    lines.append("")

    if swarm_mermaid_diagram:
        lines.append("## 5. StigmeRig Swarm Telemetry")
        lines.append("")
        lines.append("The diagram below records multi-agent task claims and state handoffs.")
        lines.append("")
        stripped = swarm_mermaid_diagram.strip()
        if stripped.startswith("```"):
            lines.append(stripped)
        else:
            lines.append("```mermaid")
            lines.append(stripped)
            lines.append("```")
        lines.append("")

    lines.append("## Dataset Attributions and Licensing")
    lines.append("")
    lines.append("- **FCC ASR**: Federal Communications Commission Antenna Structure Registration (Public Domain).")
    lines.append("- **ISED TAFL**: Innovation, Science and Economic Development Canada (Open Government Licence - Canada 2.0).")
    lines.append("- **© OpenStreetMap contributors**: Open Database License (ODbL 1.0).")
    lines.append("")

    return "\n".join(lines)


def generate_landowner_pitch_html(
    site: SiteCandidate,
    viability: Optional[SiteViabilityScore] = None,
    hardware_label: str = "RAK4631 Solar Repeater (1-Watt Enclosed Box)",
    coverage_gain_pct: float = 35.0,
    contact_org: str = "Vermont Community Emergency Mesh Initiative",
) -> str:
    """Generate a printable 1-page civic landowner host brief in self-contained HTML."""
    resolved_viability = viability
    if resolved_viability is None:
        scored = score_site_viability(site)
        resolved_viability = scored.value

    site_name = html.escape(site.name)
    site_id = html.escape(site.site_id)
    site_type_raw = html.escape(site.site_type.value)
    site_type_label = html.escape(site.site_type.value.replace("_", " ").title())
    hw_label = html.escape(hardware_label)
    org_label = html.escape(contact_org)

    elev_str = f"{site.location.elevation_m:.0f}m"
    mast_str = f"{site.mast_height_m:.0f}m"
    gain_str = f"+{coverage_gain_pct:.1f}%"

    if resolved_viability is not None:
        comp_score_str = f"{resolved_viability.composite_score:.1f} / 100"
        rf_score_str = f"{resolved_viability.rf_cleanliness_score:.1f} / 100"
        desense_str = html.escape(resolved_viability.desense_risk.value.upper())
        cavity_str = (
            "Required (902-928 MHz Bandpass Filter)"
            if resolved_viability.requires_cavity_filter
            else "Not Required (Clean RF Environment)"
        )
        hw_notes = (
            "; ".join(html.escape(n) for n in resolved_viability.recommended_hardware_notes)
            if resolved_viability.recommended_hardware_notes
            else "Standard weatherproof solar enclosure installation."
        )
    else:
        comp_score_str = "N/A"
        rf_score_str = "N/A"
        desense_str = "LOW"
        cavity_str = "Not Required"
        hw_notes = "Standard weatherproof solar enclosure installation."

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Civic Emergency Communications Host Brief — {site_name} ({site_id})</title>
<style>
  :root {{
    --ink: #1b2430;
    --muted: #4b5563;
    --border: #cbd5e1;
    --accent: #1e4d2b;
    --bg-card: #f8fafc;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: Georgia, "Times New Roman", serif;
    color: var(--ink);
    background: #ffffff;
    margin: 0;
    padding: 24px;
    line-height: 1.45;
  }}
  .page {{
    max-width: 800px;
    margin: 0 auto;
    border: 1px solid var(--border);
    padding: 28px 32px;
  }}
  header {{
    border-bottom: 2px solid var(--accent);
    padding-bottom: 12px;
    margin-bottom: 16px;
  }}
  .eyebrow {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--accent);
    font-weight: 700;
    margin: 0 0 4px 0;
  }}
  h1 {{
    font-size: 1.45rem;
    margin: 0 0 6px 0;
    color: var(--ink);
  }}
  .meta-line {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 0.85rem;
    color: var(--muted);
    margin: 0;
  }}
  h2 {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 1.0rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--accent);
    margin: 18px 0 8px 0;
    border-bottom: 1px solid var(--border);
    padding-bottom: 4px;
  }}
  p.overview {{
    font-size: 0.96rem;
    margin: 8px 0 14px 0;
  }}
  .facts-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    margin: 12px 0 18px 0;
  }}
  .fact-card {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-left: 4px solid var(--accent);
    padding: 10px 12px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }}
  .fact-card h3 {{
    font-size: 0.9rem;
    margin: 0 0 4px 0;
    color: var(--ink);
  }}
  .fact-card p {{
    font-size: 0.82rem;
    margin: 0;
    color: var(--muted);
  }}
  table.tech-summary {{
    width: 100%;
    border-collapse: collapse;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 0.84rem;
    margin-bottom: 16px;
  }}
  table.tech-summary th, table.tech-summary td {{
    border: 1px solid var(--border);
    padding: 6px 10px;
    text-align: left;
  }}
  table.tech-summary th {{
    background: var(--bg-card);
    width: 32%;
    color: var(--ink);
  }}
  .signoff {{
    margin-top: 18px;
    padding: 12px 14px;
    border: 1px dashed var(--border);
    background: #fcfcfd;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 0.84rem;
  }}
  .signoff-lines {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    margin-top: 14px;
  }}
  .sig-field {{
    border-top: 1px solid var(--ink);
    padding-top: 4px;
    font-size: 0.78rem;
    color: var(--muted);
  }}
  @media print {{
    body {{
      padding: 0;
      background: #ffffff;
    }}
    .page {{
      border: none;
      padding: 12px;
      max-width: 100%;
    }}
    .fact-card {{
      break-inside: avoid;
    }}
  }}
</style>
</head>
<body>
<div class="page">
  <header>
    <p class="eyebrow">Community Resilience &amp; Landowner Information Sheet</p>
    <h1>Civic Emergency Communications Host Brief — {site_name} ({site_id})</h1>
    <p class="meta-line">
      Structure Type: <strong>{site_type_label}</strong> (<code>{site_type_raw}</code>) |
      Coordinates: {site.location.lat:.4f}, {site.location.lon:.4f} |
      Elevation: <strong>{elev_str} ASL + {mast_str} AGL</strong> |
      Hardware Package: <strong>{hw_label}</strong>
    </p>
  </header>

  <section>
    <h2>1. Plain-English Overview: Why This Structure Matters</h2>
    <p class="overview">
      Positioned at <strong>{elev_str} ASL</strong> with a <strong>{mast_str} AGL</strong> structure profile,
      <strong>{site_name}</strong> (<code>{site_type_raw}</code>) provides unobstructed line-of-sight over surrounding terrain.
      Hosting a micro-power relay here delivers an estimated <strong>{gain_str} valley basin reach</strong> for off-grid
      emergency text-messaging coverage when cellular towers and internet lines fail during floods or winter ice storms.
    </p>
  </section>

  <section>
    <h2>2. Zero-Burden Host Facts</h2>
    <div class="facts-grid">
      <div class="fact-card">
        <h3>Physical Footprint</h3>
        <p>
          Compact weatherproof enclosure (<code>6" x 4" x 2"</code>, <code>&lt; 2 lbs</code>) with a slim fiberglass whip antenna
          (<code>24 inches</code>), attached via non-penetrating stainless hose/pipe clamps (zero drilling into tanks or silos).
        </p>
      </div>
      <div class="fact-card">
        <h3>Zero Grid Power Required</h3>
        <p>
          Self-contained 10W solar panel + winter-rated battery (<code>~45 milliwatts</code> draw — less than an LED nightlight).
          No wiring into farm, silo, or municipal electrical panels is needed.
        </p>
      </div>
      <div class="fact-card">
        <h3>FCC Part 15 License-Free &amp; Safe</h3>
        <p>
          Operates on the 915 MHz ISM band at <code>&lt;= 1 Watt</code> (identical band and power class to cordless home phones
          and smart water meters; zero interference with farm or municipal telemetry).
        </p>
      </div>
      <div class="fact-card">
        <h3>Zero Cost or Liability to Host</h3>
        <p>
          Volunteers install, maintain, and remove the unit upon request at any time. No lease lock-in, utility bills,
          or maintenance obligations for the property owner or town selectboard.
        </p>
      </div>
    </div>
  </section>

  <section>
    <h2>3. Technical &amp; RF Cleanliness Summary</h2>
    <table class="tech-summary">
      <tbody>
        <tr>
          <th>Proposed Hardware Unit</th>
          <td>{hw_label}</td>
        </tr>
        <tr>
          <th>Site Viability Composite Score</th>
          <td>{comp_score_str} (RF Cleanliness: {rf_score_str})</td>
        </tr>
        <tr>
          <th>Co-Location Desense Risk</th>
          <td>{desense_str} — Cavity Filter Status: {cavity_str}</td>
        </tr>
        <tr>
          <th>Engineering &amp; Mounting Notes</th>
          <td>{hw_notes}</td>
        </tr>
      </tbody>
    </table>
  </section>

  <section class="signoff">
    <strong>4. Site-Walk Request &amp; Host Point of Contact — {org_label}</strong>
    <p style="margin: 6px 0 10px 0;">
      We respectfully request a brief 15-minute on-site walk with the property owner, silo operator, or water district
      superintendent to inspect clamp attachment points prior to any installation.
    </p>
    <div class="signoff-lines">
      <div class="sig-field">Host / Landowner Representative &amp; Phone/Email</div>
      <div class="sig-field">Coordinator ({org_label}) &amp; Date</div>
    </div>
  </section>
</div>
</body>
</html>"""


def generate_link_survey_html(
    source: SiteCandidate,
    target: SiteCandidate,
    link: LinkBudgetResult,
    radio: Optional[RadioConfig] = None,
    org_name: str = "Vermont Community Emergency Mesh Initiative",
) -> str:
    """Generate a printable 1-page technical link survey dossier and field engineering brief."""
    src_name = html.escape(source.name)
    src_id = html.escape(source.site_id)
    tgt_name = html.escape(target.name)
    tgt_id = html.escape(target.site_id)
    org_label = html.escape(org_name)

    dt = link.downtilt_analysis
    dt_angle_str = f"{dt.look_down_angle_deg:.2f}°" if dt else "0.00°"
    dt_hpbw_str = f"{dt.vertical_beamwidth_deg:.1f}°" if dt else "N/A"
    dt_status_str = "⚠ OVERSHOOT WARNING" if (dt and dt.is_overshooting) else "ALIGNED"
    dt_rec = html.escape(dt.recommendation) if dt else "Antennas coplanar"

    los_badge = "CLEAR LINE-OF-SIGHT" if link.has_line_of_sight else "DIFFRACTED / NLOS"
    margin_color = "#22c55e" if link.link_margin_db >= 10 else ("#f59e0b" if link.link_margin_db >= 0 else "#ef4444")

    tx_power = f"{radio.tx_power_dbm:.1f} dBm" if radio else "22.0 dBm"
    ant_gain = f"{radio.antenna_gain_dbi:.1f} dBi" if radio else "5.8 dBi"
    cable_loss = f"{radio.cable_loss_db:.1f} dB" if radio else "0.5 dB"
    rx_sens = f"{radio.rx_sensitivity_dbm:.1f} dBm" if radio else "-134.0 dBm"
    freq = f"{radio.frequency_mhz:.1f} MHz" if radio else "915.0 MHz"

    from meshscout.core.provisioning import (
        ProvisioningTarget,
        generate_site_provisioning,
    )

    prov_mt = generate_site_provisioning(source, target=ProvisioningTarget.MESHTASTIC)
    prov_ret = generate_site_provisioning(source, target=ProvisioningTarget.RETICULUM)
    mt_url = html.escape(prov_mt.raw_url_or_text)
    ret_stanza = html.escape(prov_ret.raw_url_or_text)
    qr_svg = prov_mt.inline_svg_qr

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Link Survey — {src_id} to {tgt_id}</title>
<style>
  @page {{ size: letter portrait; margin: 12mm; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace;
    background: #ffffff;
    color: #0f172a;
    line-height: 1.45;
    margin: 0;
    padding: 16px;
    font-size: 13px;
  }}
  .survey-card {{
    border: 2px solid #0f172a;
    padding: 16px 20px;
    max-width: 820px;
    margin: 0 auto;
  }}
  .survey-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 2px solid #0f172a;
    padding-bottom: 10px;
    margin-bottom: 14px;
  }}
  .survey-title {{
    font-size: 18px;
    font-weight: 800;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    margin: 0;
  }}
  .survey-meta {{
    font-size: 11px;
    color: #475569;
    text-transform: uppercase;
    font-weight: 600;
  }}
  .grid-2 {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    margin-bottom: 14px;
  }}
  .node-box {{
    background: #f8fafc;
    border: 1px solid #cbd5e1;
    padding: 10px 12px;
  }}
  .node-box h4 {{
    margin: 0 0 6px 0;
    font-size: 13px;
    font-weight: 700;
    color: #0f172a;
    border-bottom: 1px dashed #cbd5e1;
    padding-bottom: 4px;
  }}
  .node-field {{
    display: flex;
    justify-content: space-between;
    font-size: 11.5px;
    margin: 3px 0;
  }}
  .node-label {{
    color: #64748b;
    font-weight: 500;
  }}
  .node-val {{
    font-family: monospace;
    font-weight: 700;
  }}
  .rf-summary-table {{
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 14px;
  }}
  .rf-summary-table th, .rf-summary-table td {{
    border: 1px solid #cbd5e1;
    padding: 6px 10px;
    font-size: 12px;
    text-align: left;
  }}
  .rf-summary-table th {{
    background: #0f172a;
    color: #ffffff;
    font-weight: 600;
  }}
  .margin-highlight {{
    font-size: 15px;
    font-weight: 800;
    color: {margin_color};
  }}
  .checklist {{
    background: #f1f5f9;
    border: 1px solid #cbd5e1;
    padding: 10px 14px;
    margin-top: 14px;
  }}
  .provisioning-section {{
    background: #f8fafc;
    border: 1px solid #cbd5e1;
    padding: 12px 14px;
    margin-top: 14px;
  }}
  .provisioning-section h4 {{
    margin: 0 0 10px 0;
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
    color: #0f172a;
    border-bottom: 1px dashed #cbd5e1;
    padding-bottom: 4px;
  }}
  .prov-grid {{
    display: flex;
    gap: 16px;
    align-items: flex-start;
  }}
  .prov-qr {{
    flex-shrink: 0;
    border: 1px solid #cbd5e1;
    background: #ffffff;
    padding: 6px;
    text-align: center;
  }}
  .prov-details {{
    flex-grow: 1;
    min-width: 0;
  }}
  .prov-url-box {{
    background: #ffffff;
    border: 1px solid #e2e8f0;
    padding: 6px 8px;
    font-family: monospace;
    font-size: 11px;
    word-break: break-all;
    margin: 4px 0 8px 0;
  }}
  .prov-code {{
    background: #0f172a;
    color: #f8fafc;
    padding: 8px 10px;
    font-family: monospace;
    font-size: 11px;
    white-space: pre;
    overflow-x: auto;
    border-radius: 4px;
    margin: 4px 0;
  }}
  .checklist h4 {{
    margin: 0 0 8px 0;
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
  }}
  .checklist-item {{
    font-size: 11.5px;
    margin: 4px 0;
  }}
  @media print {{
    body {{ padding: 0; }}
    .survey-card {{ border: 1px solid #000; box-shadow: none; }}
  }}
</style>
</head>
<body>
<div class="survey-card">
  <div class="survey-header">
    <div>
      <h1 class="survey-title">RF Link Engineering Survey Dossier</h1>
      <div class="survey-meta">{org_label} // Longley-Rice ITM Benchmark</div>
    </div>
    <div style="text-align: right;">
      <span style="display:inline-block;padding:4px 8px;border:1px solid #0f172a;font-weight:700;font-size:11px;">
        {los_badge}
      </span>
    </div>
  </div>

  <div class="grid-2">
    <div class="node-box">
      <h4>ORIGIN: {src_name} ({src_id})</h4>
      <div class="node-field"><span class="node-label">Structure:</span><span class="node-val">{source.site_type.value}</span></div>
      <div class="node-field"><span class="node-label">Coordinates:</span><span class="node-val">{source.location.lat:.4f}°N, {source.location.lon:.4f}°W</span></div>
      <div class="node-field"><span class="node-label">Ground Elev ASL:</span><span class="node-val">{source.location.elevation_m:.1f} m</span></div>
      <div class="node-field"><span class="node-label">Mast Height AGL:</span><span class="node-val">{source.mast_height_m:.1f} m</span></div>
      <div class="node-field"><span class="node-label">Total Radiation Alt:</span><span class="node-val">{source.location.elevation_m + source.mast_height_m:.1f} m</span></div>
    </div>

    <div class="node-box">
      <h4>TARGET: {tgt_name} ({tgt_id})</h4>
      <div class="node-field"><span class="node-label">Structure:</span><span class="node-val">{target.site_type.value}</span></div>
      <div class="node-field"><span class="node-label">Coordinates:</span><span class="node-val">{target.location.lat:.4f}°N, {target.location.lon:.4f}°W</span></div>
      <div class="node-field"><span class="node-label">Ground Elev ASL:</span><span class="node-val">{target.location.elevation_m:.1f} m</span></div>
      <div class="node-field"><span class="node-label">Mast Height AGL:</span><span class="node-val">{target.mast_height_m:.1f} m</span></div>
      <div class="node-field"><span class="node-label">Total Radiation Alt:</span><span class="node-val">{target.location.elevation_m + target.mast_height_m:.1f} m</span></div>
    </div>
  </div>

  <table class="rf-summary-table">
    <thead>
      <tr>
        <th>Distance</th>
        <th>Free Space (FSPL)</th>
        <th>Diffraction Loss</th>
        <th>Total Path Loss</th>
        <th>RX Signal Power</th>
        <th>Link Fade Margin</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td><strong>{link.distance_km:.2f} km</strong></td>
        <td>{link.free_space_loss_db:.1f} dB</td>
        <td>{link.diffraction_loss_db:.1f} dB</td>
        <td><strong>{link.total_path_loss_db:.1f} dB</strong></td>
        <td>{link.rx_power_dbm:.1f} dBm</td>
        <td class="margin-highlight">{link.link_margin_db:+.1f} dB</td>
      </tr>
    </tbody>
  </table>

  <div class="grid-2">
    <div class="node-box">
      <h4>Fresnel &amp; Downtilt Alignment</h4>
      <div class="node-field"><span class="node-label">Fresnel Clearance Ratio:</span><span class="node-val">{link.fresnel_clearance_ratio:.2f} F1</span></div>
      <div class="node-field"><span class="node-label">Look-Down Angle:</span><span class="node-val">{dt_angle_str}</span></div>
      <div class="node-field"><span class="node-label">Vertical HPBW:</span><span class="node-val">{dt_hpbw_str}</span></div>
      <div class="node-field"><span class="node-label">Alignment Status:</span><span class="node-val">{dt_status_str}</span></div>
      <div style="font-size:11px;color:#64748b;margin-top:4px;">{dt_rec}</div>
    </div>

    <div class="node-box">
      <h4>Radio &amp; Frequency Parameters</h4>
      <div class="node-field"><span class="node-label">Operating Frequency:</span><span class="node-val">{freq}</span></div>
      <div class="node-field"><span class="node-label">Transmitter Power:</span><span class="node-val">{tx_power}</span></div>
      <div class="node-field"><span class="node-label">Antenna Gain (each):</span><span class="node-val">{ant_gain}</span></div>
      <div class="node-field"><span class="node-label">Cable / Feedline Loss:</span><span class="node-val">{cable_loss}</span></div>
      <div class="node-field"><span class="node-label">Receiver Sensitivity:</span><span class="node-val">{rx_sens}</span></div>
    </div>
  </div>

  <div class="provisioning-section">
    <h4>Multi-Protocol Radio Provisioning &amp; Field QR</h4>
    <div class="prov-grid">
      <div class="prov-qr">
        {qr_svg}
        <div style="font-size: 10px; color: #64748b; margin-top: 4px; font-weight: 600;">Scan for Meshtastic Channel</div>
      </div>
      <div class="prov-details">
        <div style="font-weight: 700; font-size: 11.5px; color: #334155;">Meshtastic Channel URL (Origin Node):</div>
        <div class="prov-url-box">{mt_url}</div>
        <div style="font-weight: 700; font-size: 11.5px; color: #334155; margin-top: 6px;">Reticulum RNode Interface Stanza (rns.conf):</div>
        <div class="prov-code">{ret_stanza}</div>
      </div>
    </div>
  </div>

  <div class="checklist">
    <h4>Field Deployment Pre-Flight Checklist</h4>
    <div class="checklist-item">[ &nbsp; ] Physical mast clearance verified against power lines and surrounding tree canopy.</div>
    <div class="checklist-item">[ &nbsp; ] Coaxial lightning surge arrestor grounded to building ground rod (&lt; 25 Ohms).</div>
    <div class="checklist-item">[ &nbsp; ] Cavity bandpass filter installed if co-located with high-power VHF/UHF public safety transmitters.</div>
    <div class="checklist-item">[ &nbsp; ] RSSI / SNR wardrive test packet recorded and verified on field handheld tracker.</div>
  </div>
</div>
</body>
</html>"""


def _build_elevation_svg(sites: Sequence[SiteCandidate]) -> str:
    """Render an inline SVG bar chart of candidate site ground + mast elevations."""
    if not sites:
        return '<svg width="640" height="120" viewBox="0 0 640 120" xmlns="http://www.w3.org/2000/svg"><text x="20" y="60" fill="#64748b" font-family="sans-serif" font-size="13">No sites provided for elevation overview.</text></svg>'

    width = 680
    height = 190
    pad_left = 55
    pad_right = 25
    pad_top = 25
    pad_bottom = 45
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    totals = [max(1.0, s.location.elevation_m + s.mast_height_m) for s in sites]
    max_elev = max(totals)
    n = len(sites)
    slot_w = plot_w / max(1, n)
    bar_w = min(56.0, max(16.0, slot_w * 0.55))

    elements: List[str] = [
        f'<svg width="100%" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Site Elevation Overview">',
        f'<rect x="0" y="0" width="{width}" height="{height}" rx="6" fill="#0f172a"/>',
        f'<line x1="{pad_left}" y1="{pad_top + plot_h}" x2="{width - pad_right}" y2="{pad_top + plot_h}" stroke="#334155" stroke-width="1"/>',
        f'<text x="{pad_left - 8}" y="{pad_top + 8}" text-anchor="end" fill="#94a3b8" font-family="monospace" font-size="10">{max_elev:.0f}m</text>',
        f'<text x="{pad_left - 8}" y="{pad_top + plot_h}" text-anchor="end" fill="#94a3b8" font-family="monospace" font-size="10">0m</text>',
    ]

    for idx, site in enumerate(sites):
        total_m = site.location.elevation_m + site.mast_height_m
        ratio = max(0.04, total_m / max_elev)
        bar_h = ratio * plot_h
        cx = pad_left + idx * slot_w + slot_w / 2.0
        bx = cx - bar_w / 2.0
        by = pad_top + plot_h - bar_h
        label = html.escape(site.site_id)
        elements.append(
            f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" rx="3" fill="#38bdf8"/>'
        )
        elements.append(
            f'<text x="{cx:.1f}" y="{by - 5:.1f}" text-anchor="middle" fill="#e2e8f0" font-family="monospace" font-size="10">{total_m:.0f}m</text>'
        )
        elements.append(
            f'<text x="{cx:.1f}" y="{pad_top + plot_h + 16:.1f}" text-anchor="middle" fill="#cbd5e1" font-family="sans-serif" font-size="10">{label}</text>'
        )

    elements.append("</svg>")
    return "\n".join(elements)


def generate_portable_workbench_html(
    region_name: str,
    sites: Sequence[SiteCandidate],
    links: Sequence[LinkBudgetResult] = (),
    home_summary: Optional[Dict[str, Any]] = None,
) -> str:
    """Generate a 100% self-contained single-file HTML report for offline club sharing."""
    safe_region = html.escape(region_name)
    svg_chart = _build_elevation_svg(sites)

    site_rows: List[str] = []
    for s in sites:
        notes_lower = (s.notes or "").lower()
        is_active = "active" in notes_lower or "online" in notes_lower or "deployed" in notes_lower
        badge_cls = "badge-active" if is_active else "badge-candidate"
        badge_txt = "ACTIVE NODE" if is_active else "CANDIDATE"
        power_txt = "Grid AC" if s.has_grid_power else f"Solar ({s.solar_exposure_pct:.0f}%)"
        site_rows.append(
            "<tr>"
            f"<td><code>{html.escape(s.site_id)}</code></td>"
            f"<td><strong>{html.escape(s.name)}</strong></td>"
            f"<td><span class='badge {badge_cls}'>{badge_txt}</span></td>"
            f"<td><code>{html.escape(s.site_type.value)}</code></td>"
            f"<td>{s.location.lat:.4f}, {s.location.lon:.4f}</td>"
            f"<td>{s.location.elevation_m:.1f} m</td>"
            f"<td>{s.mast_height_m:.1f} m</td>"
            f"<td>{power_txt}</td>"
            f"<td><code>{html.escape(s.access_difficulty.value)}</code></td>"
            "</tr>"
        )
    sites_tbody = "\n".join(site_rows) if site_rows else "<tr><td colspan='9'>No sites registered.</td></tr>"

    link_rows: List[str] = []
    for lk in links:
        los_badge = (
            "<span class='badge badge-active'>LOS CLEAR</span>"
            if lk.has_line_of_sight
            else "<span class='badge badge-warn'>OBSTRUCTED</span>"
        )
        link_rows.append(
            "<tr>"
            f"<td><code>{html.escape(lk.source_id)}</code></td>"
            f"<td><code>{html.escape(lk.target_id)}</code></td>"
            f"<td>{lk.distance_km:.2f} km</td>"
            f"<td>{lk.total_path_loss_db:.1f} dB</td>"
            f"<td>{lk.rx_power_dbm:.1f} dBm</td>"
            f"<td>{lk.link_margin_db:.1f} dB</td>"
            f"<td>{los_badge}</td>"
            f"<td>{lk.fresnel_clearance_ratio:.2f}</td>"
            "</tr>"
        )
    links_tbody = "\n".join(link_rows) if link_rows else "<tr><td colspan='8'>No point-to-point RF links evaluated.</td></tr>"

    home_block = ""
    if home_summary:
        items = "".join(
            f"<div><strong>{html.escape(str(k))}:</strong> {html.escape(str(v))}</div>"
            for k, v in home_summary.items()
        )
        home_block = f"""
  <section class="panel">
    <h2>Home QTH / Operator Summary</h2>
    <div class="summary-grid">{items}</div>
  </section>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MeshScout Portable Workbench — {safe_region}</title>
<style>
  :root {{
    --bg: #0b1120;
    --panel: #1e293b;
    --border: #334155;
    --text: #f1f5f9;
    --muted: #94a3b8;
    --accent: #38bdf8;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    margin: 0;
    padding: 24px;
    line-height: 1.5;
  }}
  .container {{
    max-width: 1100px;
    margin: 0 auto;
  }}
  header {{
    border-bottom: 1px solid var(--border);
    padding-bottom: 14px;
    margin-bottom: 20px;
  }}
  h1 {{
    margin: 0 0 6px 0;
    font-size: 1.5rem;
    color: var(--text);
  }}
  .subtitle {{
    margin: 0;
    color: var(--muted);
    font-size: 0.9rem;
  }}
  .panel {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px 20px;
    margin-bottom: 20px;
  }}
  h2 {{
    margin: 0 0 12px 0;
    font-size: 1.05rem;
    color: var(--accent);
  }}
  .summary-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 10px;
    font-size: 0.88rem;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.85rem;
  }}
  th, td {{
    border-bottom: 1px solid var(--border);
    padding: 8px 10px;
    text-align: left;
  }}
  th {{
    color: var(--muted);
    font-weight: 600;
    background: #0f172a;
  }}
  .badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.04em;
  }}
  .badge-active {{
    background: rgba(34, 197, 94, 0.2);
    color: #4ade80;
    border: 1px solid rgba(34, 197, 94, 0.4);
  }}
  .badge-candidate {{
    background: rgba(56, 189, 248, 0.18);
    color: #38bdf8;
    border: 1px solid rgba(56, 189, 248, 0.4);
  }}
  .badge-warn {{
    background: rgba(245, 158, 11, 0.2);
    color: #fbbf24;
    border: 1px solid rgba(245, 158, 11, 0.4);
  }}
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>MeshScout Portable Workbench — {safe_region}</h1>
    <p class="subtitle">
      Self-Contained Offline Regional RF Dossier | Sites: {len(sites)} | Point-to-Point Links: {len(links)}
    </p>
  </header>
{home_block}
  <section class="panel">
    <h2>SVG Elevation Overview (Ground ASL + Mast AGL)</h2>
    {svg_chart}
  </section>

  <section class="panel">
    <h2>Regional High-Site &amp; Node Schedule</h2>
    <table>
      <thead>
        <tr>
          <th>Site ID</th>
          <th>Name</th>
          <th>Status</th>
          <th>Type</th>
          <th>Coordinates</th>
          <th>Elev (ASL)</th>
          <th>Mast (AGL)</th>
          <th>Power</th>
          <th>Access</th>
        </tr>
      </thead>
      <tbody>
        {sites_tbody}
      </tbody>
    </table>
  </section>

  <section class="panel">
    <h2>Point-to-Point RF Link Budget Table</h2>
    <table>
      <thead>
        <tr>
          <th>Source</th>
          <th>Target</th>
          <th>Distance</th>
          <th>Path Loss</th>
          <th>RX Power</th>
          <th>Link Margin</th>
          <th>Line of Sight</th>
          <th>Fresnel Ratio</th>
        </tr>
      </thead>
      <tbody>
        {links_tbody}
      </tbody>
    </table>
  </section>
</div>
</body>
</html>"""


def export_gpx_waypoints(
    sites: Sequence[SiteCandidate],
    include_home: Optional[Coordinate] = None,
    home_name: str = "Home Node",
) -> str:
    """Generate standard GPX 1.1 XML string for handheld GPS and ATAK."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="MeshScout // Vermont Community Mesh Planner" '
        'xmlns="http://www.topografix.com/GPX/1/1" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:schemaLocation="http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd">',
        '  <metadata>',
        '    <name>MeshScout Planned Topology Waypoints</name>',
        '    <desc>Tactical LoRa repeater and node candidate waypoints generated by MeshScout.</desc>',
        '  </metadata>',
    ]

    if include_home is not None:
        lines.append(f'  <wpt lat="{include_home.lat:.6f}" lon="{include_home.lon:.6f}">')
        lines.append(f'    <ele>{include_home.elevation_m:.1f}</ele>')
        lines.append(f'    <name>{html.escape(home_name)}</name>')
        lines.append('    <desc>Designated mesh home base station</desc>')
        lines.append('    <sym>Residence</sym>')
        lines.append('    <type>Home Base</type>')
        lines.append('  </wpt>')

    for site in sites:
        total_elev = site.location.elevation_m + site.mast_height_m
        sym = "Tower" if "tower" in site.site_type.value else "Summit" if "mountain" in site.site_type.value else "Building"
        lines.append(f'  <wpt lat="{site.location.lat:.6f}" lon="{site.location.lon:.6f}">')
        lines.append(f'    <ele>{total_elev:.1f}</ele>')
        lines.append(f'    <name>{html.escape(site.name)} [{site.site_id}]</name>')
        lines.append(f'    <desc>Type: {site.site_type.value} | Mast: {site.mast_height_m:.0f}m AGL | ASL: {site.location.elevation_m:.0f}m</desc>')
        lines.append(f'    <sym>{sym}</sym>')
        lines.append(f'    <type>{site.site_type.value}</type>')
        lines.append('  </wpt>')

    lines.append('</gpx>')
    return '\n'.join(lines)


def export_kml_document(
    sites: Sequence[SiteCandidate],
    active_links: Sequence[Tuple[SiteCandidate, SiteCandidate, float]] = (),
    include_home: Optional[Coordinate] = None,
    home_name: str = "Home Node",
) -> str:
    """Generate standard OGC KML 2.2 XML string for Google Earth and GIS."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        '  <Document>',
        '    <name>MeshScout Mesh Network Topology</name>',
        '    <description>Community LoRa mesh candidates and point-to-point links</description>',
        '    <Style id="towerStyle">',
        '      <IconStyle>',
        '        <color>ff85d025</color>',
        '        <scale>1.1</scale>',
        '      </IconStyle>',
        '    </Style>',
        '    <Style id="linkLineStyle">',
        '      <LineStyle>',
        '        <color>ff85d025</color>',
        '        <width>2.5</width>',
        '      </LineStyle>',
        '    </Style>',
        '    <Folder>',
        '      <name>Repeater &amp; Node Sites</name>',
    ]

    if include_home is not None:
        lines.append('      <Placemark>')
        lines.append(f'        <name>{html.escape(home_name)}</name>')
        lines.append('        <description>Designated home node base station</description>')
        lines.append('        <Point>')
        lines.append(f'          <coordinates>{include_home.lon:.6f},{include_home.lat:.6f},{include_home.elevation_m:.1f}</coordinates>')
        lines.append('        </Point>')
        lines.append('      </Placemark>')

    for site in sites:
        total_alt = site.location.elevation_m + site.mast_height_m
        lines.append('      <Placemark>')
        lines.append(f'        <name>{html.escape(site.name)} [{site.site_id}]</name>')
        lines.append(f'        <description><![CDATA[Type: {site.site_type.value}<br/>Mast: {site.mast_height_m:.0f}m AGL<br/>ASL: {site.location.elevation_m:.0f}m]]></description>')
        lines.append('        <styleUrl>#towerStyle</styleUrl>')
        lines.append('        <Point>')
        lines.append(f'          <coordinates>{site.location.lon:.6f},{site.location.lat:.6f},{total_alt:.1f}</coordinates>')
        lines.append('        </Point>')
        lines.append('      </Placemark>')

    lines.append('    </Folder>')

    if active_links:
        lines.append('    <Folder>')
        lines.append('      <name>Point-to-Point RF Links</name>')
        for src, dst, margin_db in active_links:
            lines.append('      <Placemark>')
            lines.append(f'        <name>{html.escape(src.name)} &lt;-&gt; {html.escape(dst.name)}</name>')
            lines.append(f'        <description>Estimated Link Margin: {margin_db:+.1f} dB</description>')
            lines.append('        <styleUrl>#linkLineStyle</styleUrl>')
            lines.append('        <LineString>')
            lines.append(f'          <coordinates>{src.location.lon:.6f},{src.location.lat:.6f},{src.location.elevation_m + src.mast_height_m:.1f} {dst.location.lon:.6f},{dst.location.lat:.6f},{dst.location.elevation_m + dst.mast_height_m:.1f}</coordinates>')
            lines.append('        </LineString>')
            lines.append('      </Placemark>')
        lines.append('    </Folder>')

    lines.append('  </Document>')
    lines.append('</kml>')
    return '\n'.join(lines)

