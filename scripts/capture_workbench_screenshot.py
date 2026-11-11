#!/usr/bin/env python3
"""
scripts/capture_workbench_screenshot.py

Captures a high-resolution retina screenshot of the MeshScout interactive web workbench
for inclusion in README.md and documentation.
"""

import hashlib
import json
import time
import threading
import uvicorn
from pathlib import Path
from playwright.sync_api import sync_playwright

def run_server():
    from meshscout.web.app import app
    uvicorn.run(app, host="127.0.0.1", port=8089, log_level="warning")

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
    out_png = assets_dir / "meshscout-workbench.png"

    # Start server in daemon thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(2)  # Wait for server startup

    with sync_playwright() as p:
        browser = p.chromium.launch()
        # 1600x960 retina viewport
        page = browser.new_page(viewport={"width": 1600, "height": 960}, device_scale_factor=1)
        page.goto("http://127.0.0.1:8089")
        
        # Wait for map and UI elements to load
        page.wait_for_selector("#map-container", timeout=10000)
        page.wait_for_selector("#vector-map-svg", timeout=10000)
        page.wait_for_timeout(3000)  # Wait for map layers, markers, and sidebar to populate
        
        page.screenshot(path=str(out_png))
        browser.close()

    print(f"Captured workbench screenshot: {out_png} ({out_png.stat().st_size} bytes)")

    # Update manifest.json with the new asset
    manifest_file = assets_dir / "manifest.json"
    if manifest_file.exists():
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        files = {}
        for f in assets_dir.rglob("*"):
            if f.is_file() and f.name != "manifest.json" and not f.name.startswith("."):
                rel = f.relative_to(assets_dir).as_posix()
                files[rel] = sha256_file(f)
        manifest["files"] = files
        manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"Updated manifest: {manifest_file}")

if __name__ == "__main__":
    main()
