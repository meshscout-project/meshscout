#!/usr/bin/env python3
"""Verify README scorecard parity against live MeshScout MCP and region catalogs.

Runs standalone using only the Python 3.10+ standard library and resolves the
repository root from ``__file__`` so it operates from any working directory or
clean-room release export.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = str(REPO_ROOT / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

EXPECTED_TOOL_COUNT = 14
EXPECTED_RESOURCE_COUNT = 8
EXPECTED_PROMPT_COUNT = 3
EXPECTED_REGION_COUNT = 65


def _token_present(text: str, token: str) -> bool:
    """Return True when an exact tool, resource URI, or prompt token appears in text."""
    pattern = rf"(?<![A-Za-z0-9_:/-]){re.escape(token)}(?![A-Za-z0-9_:/-])"
    return re.search(pattern, text) is not None


def verify_scorecard_parity(repo_root: Path = REPO_ROOT) -> tuple[bool, list[str]]:
    """Verify README scorecard counts and manifest entries match live source definitions."""
    src_path = str(repo_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

    from meshscout.adapters.regions import NorthAmericaRegionCode
    from meshscout.mcp_server import (
        MCP_PROMPTS_MANIFEST,
        MCP_RESOURCES_MANIFEST,
        MCP_TOOLS_MANIFEST,
    )

    errors: list[str] = []
    readme_path = repo_root / "README.md"
    if not readme_path.is_file():
        return False, [f"Missing README.md at {readme_path}"]

    try:
        readme_text = readme_path.read_text(encoding="utf-8")
    except OSError as exc:
        return False, [f"Failed reading {readme_path}: {exc}"]

    tool_count = len(MCP_TOOLS_MANIFEST)
    resource_count = len(MCP_RESOURCES_MANIFEST)
    prompt_count = len(MCP_PROMPTS_MANIFEST)
    region_count = len(NorthAmericaRegionCode)

    expected_counts = (
        ("MCP tools", tool_count, EXPECTED_TOOL_COUNT),
        ("MCP resources", resource_count, EXPECTED_RESOURCE_COUNT),
        ("MCP prompts", prompt_count, EXPECTED_PROMPT_COUNT),
        ("North American jurisdictions", region_count, EXPECTED_REGION_COUNT),
    )
    for label, actual, expected in expected_counts:
        if actual != expected:
            errors.append(
                f"Live {label} count mismatch: expected {expected}, found {actual}."
            )

    scorecard_markers = (
        f"**{tool_count} Tools**:",
        f"**{resource_count} Resources**:",
        f"**{prompt_count} Prompts**:",
        f"{region_count} North American jurisdictions",
    )
    for marker in scorecard_markers:
        if marker not in readme_text:
            errors.append(
                f"README.md missing expected scorecard marker: {marker}"
            )

    for tool in MCP_TOOLS_MANIFEST:
        tool_name = str(tool.get("name", "")).strip()
        if not tool_name or not _token_present(readme_text, tool_name):
            errors.append(
                f"README.md missing MCP tool from manifest: {tool_name}"
            )

    for resource in MCP_RESOURCES_MANIFEST:
        resource_uri = str(resource.get("uri", "")).strip()
        if not resource_uri or not _token_present(readme_text, resource_uri):
            errors.append(
                f"README.md missing MCP resource from manifest: {resource_uri}"
            )

    for prompt in MCP_PROMPTS_MANIFEST:
        prompt_name = str(prompt.get("name", "")).strip()
        if not prompt_name or not _token_present(readme_text, prompt_name):
            errors.append(
                f"README.md missing MCP prompt from manifest: {prompt_name}"
            )

    return len(errors) == 0, errors


def main() -> int:
    """Run scorecard parity check and print verification summary."""
    ok, errors = verify_scorecard_parity(REPO_ROOT)
    if ok:
        print(
            "[PASS] Scorecard parity verified: "
            f"{EXPECTED_TOOL_COUNT} tools, "
            f"{EXPECTED_RESOURCE_COUNT} resources, "
            f"{EXPECTED_PROMPT_COUNT} prompts, "
            f"{EXPECTED_REGION_COUNT} jurisdictions."
        )
        return 0

    for error in errors:
        print(f"[FAIL] {error}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
