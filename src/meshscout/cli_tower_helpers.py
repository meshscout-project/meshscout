"""CLI helper functions for the `meshscout towers` subcommand.

Separates pure human-readable summary formatting (Functional Core) from
argument validation, source resolution, database lifecycle, and stdio I/O
(Imperative Shell).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


def format_tower_ingest_summary(ingest_res: dict[str, Any], source_key: str) -> str:
    """Format a human-readable summary table for tower dataset ingestion results."""
    lines = [
        "============================================================",
        f" Ingested {ingest_res['ingested_count']} towers from {source_key}",
        "============================================================",
        " Breakdown by Region:",
    ]
    for reg, cnt in sorted(ingest_res.get("by_region", {}).items()):
        lines.append(f"   - {reg:<12}: {cnt:,} towers")
    tier_stats = ingest_res.get("by_friction_tier", {})
    lines.extend(
        [
            " Breakdown by Friction Tier:",
            f"   - Tier 1 Civic:        {tier_stats.get('tier_1_civic', 0):,} towers",
            f"   - Tier 2 Agricultural: {tier_stats.get('tier_2_agricultural', 0):,} towers",
            f"   - Tier 3 Commercial:   {tier_stats.get('tier_3_commercial', 0):,} towers",
            "============================================================",
        ]
    )
    return "\n".join(lines) + "\n"


def run_towers_subcommand(args: argparse.Namespace) -> int:
    """Execute the `towers` CLI subcommand and return a POSIX exit code."""
    from meshscout.adapters.source_fetch import fetch_source
    from meshscout.adapters.tower_ingest import ingest_tower_source
    from meshscout.core.tower_registry import UnifiedTowerRegistry

    if args.towers_action == "ingest":
        source_key = args.source or getattr(args, "pos_source", None)
        if not source_key:
            sys.stderr.write("Error: Must specify source ('fcc_asr', 'ised_sms', or 'civic').\n")
            return 2

        source_path: Path | None = None
        if args.path:
            source_path = Path(args.path)
        elif args.from_source:
            try:
                source_path = fetch_source(source_key)
            except Exception as exc:
                sys.stderr.write(f"Error fetching source '{source_key}': {exc}\n")
                return 1
        else:
            sys.stderr.write("Error: Must specify either --path/--input <PATH> or --from-source.\n")
            return 2

        if not source_path.exists():
            sys.stderr.write(f"Error: Source file not found: {source_path}\n")
            return 1

        registry = UnifiedTowerRegistry(db_path=args.db_path)
        try:
            ingest_res = ingest_tower_source(
                registry=registry,
                source=source_key,
                path=source_path,
                region_code=args.region,
            )
            if getattr(args, "output_json", False):
                sys.stdout.write(json.dumps(ingest_res, indent=2) + "\n")
            else:
                sys.stdout.write(format_tower_ingest_summary(ingest_res, source_key))
            return 0
        except Exception as exc:
            sys.stderr.write(f"Error during tower ingestion: {exc}\n")
            return 1
        finally:
            registry.close()

    return 1
