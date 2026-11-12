#!/usr/bin/env python3
"""
scripts/build_branding.py

Role:
  Deterministic brand asset compiler for MeshScout.
  Complies with the Code-Rendered Infographics Mandate (AGENTS.md Item 6 & Rule 10).
  Produces lossless vector SVG, 1024x1024 PNG avatar, and manifest.json sidecar.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

SVG_SOURCE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="100%" height="100%">
  <!-- Background: Deep Conifer Forest -->
  <rect width="512" height="512" rx="112" fill="#14261F" />
  
  <!-- Outer Survey Compass / Benchmark Border -->
  <circle cx="256" cy="256" r="216" fill="none" stroke="#A89F84" stroke-width="2" stroke-dasharray="3 6" opacity="0.6"/>
  <circle cx="256" cy="256" r="204" fill="none" stroke="#EDE6D6" stroke-width="1.5" opacity="0.3"/>

  <!-- Topographic Elevation Contours (Matte Sand/Buff) -->
  <g fill="none" stroke="#A89F84" opacity="0.45" stroke-width="1.5">
    <ellipse cx="256" cy="300" rx="180" ry="100" />
    <ellipse cx="256" cy="290" rx="140" ry="75" />
    <ellipse cx="256" cy="280" rx="100" ry="50" />
    <ellipse cx="256" cy="270" rx="60" ry="30" />
  </g>

  <!-- Mountain Massif (Solid Terracotta & Raw Umber) -->
  <!-- Back Ridge -->
  <polygon points="60,410 180,260 280,360 400,240 460,410" fill="#20382E" />
  <!-- Primary Ridge -->
  <polygon points="100,410 256,200 412,410" fill="#B35434" />
  <!-- Mountain Shadow Facet -->
  <polygon points="256,200 256,410 412,410" fill="#7E3720" />

  <!-- Geodetic Survey Benchmark Reticle Lines -->
  <line x1="256" y1="56" x2="256" y2="116" stroke="#EDE6D6" stroke-width="2" stroke-linecap="round" opacity="0.7"/>
  <line x1="56" y1="256" x2="116" y2="256" stroke="#EDE6D6" stroke-width="2" stroke-linecap="round" opacity="0.7"/>
  <line x1="396" y1="256" x2="456" y2="256" stroke="#EDE6D6" stroke-width="2" stroke-linecap="round" opacity="0.7"/>

  <!-- Communication Mast (Bone Ivory) -->
  <line x1="256" y1="126" x2="256" y2="200" stroke="#EDE6D6" stroke-width="4" stroke-linecap="round"/>
  <line x1="244" y1="200" x2="256" y2="126" stroke="#EDE6D6" stroke-width="2"/>
  <line x1="268" y1="200" x2="256" y2="126" stroke="#EDE6D6" stroke-width="2"/>
  <line x1="247" y1="172" x2="265" y2="172" stroke="#EDE6D6" stroke-width="2"/>
  <line x1="250" y1="150" x2="262" y2="150" stroke="#EDE6D6" stroke-width="2"/>

  <!-- RF Radial Signals (Warm Buff / Non-Neon) -->
  <path d="M 230,112 A 30,30 0 0,1 282,112" fill="none" stroke="#EDE6D6" stroke-width="3.5" stroke-linecap="round"/>
  <path d="M 212,96 A 52,52 0 0,1 300,96" fill="none" stroke="#EDE6D6" stroke-width="3" stroke-linecap="round" opacity="0.85"/>
  <path d="M 194,80 A 74,74 0 0,1 318,80" fill="none" stroke="#EDE6D6" stroke-width="2.5" stroke-linecap="round" opacity="0.65"/>

  <!-- High-Site Beacon (Rescue Orange / Terracotta) -->
  <circle cx="256" cy="126" r="8" fill="#D4421E" stroke="#EDE6D6" stroke-width="2.5" />

  <!-- Outlying Mesh Nodes & Connecting Sightlines -->
  <g stroke="#EDE6D6" stroke-width="1.5" stroke-dasharray="3 4" opacity="0.5">
    <line x1="256" y1="126" x2="120" y2="230"/>
    <line x1="256" y1="126" x2="390" y2="220"/>
    <line x1="120" y1="230" x2="170" y2="340"/>
    <line x1="390" y1="220" x2="340" y2="340"/>
  </g>

  <!-- Nodes -->
  <circle cx="120" cy="230" r="6" fill="#EDE6D6" stroke="#14261F" stroke-width="2"/>
  <circle cx="390" cy="220" r="6" fill="#EDE6D6" stroke="#14261F" stroke-width="2"/>
  <circle cx="170" cy="340" r="5" fill="#D4421E" stroke="#EDE6D6" stroke-width="1.5"/>
  <circle cx="340" cy="340" r="5" fill="#D4421E" stroke="#EDE6D6" stroke-width="1.5"/>

  <!-- Clean Brand Name Typography: MESHSCOUT -->
  <text x="256" y="458" font-family="'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif" font-size="20" fill="#EDE6D6" letter-spacing="6" text-anchor="middle" font-weight="700">MESHSCOUT</text>
</svg>
"""


def sha256_file(filepath: Path) -> str:
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def main():
    root = Path(__file__).resolve().parent.parent
    assets_dir = root / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    svg_file = assets_dir / "meshscout-logo.svg"
    svg_file.write_text(SVG_SOURCE, encoding="utf-8", newline="\n")

    html_file = assets_dir / "render_avatar.html"
    html_content = f"""<!DOCTYPE html><html><body style="margin:0;display:flex;align-items:center;justify-content:center;width:1024px;height:1024px;background:transparent;">{SVG_SOURCE}</body></html>"""
    html_file.write_text(html_content, encoding="utf-8")

    png_file = assets_dir / "meshscout-avatar.png"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1024, "height": 1024})
        page.goto(html_file.as_uri())
        page.screenshot(path=str(png_file), omit_background=True)
        browser.close()

    manifest = {
        "slug": "meshscout-brand-avatar",
        "concept": "MeshScout official organization avatar - USGS Field Cartography with clean wordmark",
        "archetype": "instrumentation",
        "engine": "html",
        "provenance": {
            "generator": "html-playwright",
            "source_script": "scripts/build_branding.py",
            "viewport": [1024, 1024],
            "renderer": "chromium-playwright"
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "files": {
            "meshscout-logo.svg": sha256_file(svg_file),
            "meshscout-avatar.png": sha256_file(png_file),
            "render_avatar.html": sha256_file(html_file)
        }
    }

    manifest_file = assets_dir / "manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Brand assets compiled successfully:")
    print(f"  - SVG: {svg_file}")
    print(f"  - PNG: {png_file}")
    print(f"  - Manifest: {manifest_file}")


if __name__ == "__main__":
    main()
