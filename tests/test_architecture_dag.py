"""Architectural DAG, regulatory parity, scorecard parity, and trap ratchet tests."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from meshscout import mcp_tool_helpers
from meshscout.web import regulatory_routes

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src" / "meshscout"

L0_MODULES: frozenset[str] = frozenset({
    "meshscout.__init__",
    "meshscout.core.contracts",
})

L1_CORE_NAMES: Tuple[str, ...] = (
    "fresnel",
    "itm",
    "viewshed",
    "optimizer",
    "scorer",
    "presets",
    "regulatory",
    "solar",
    "telemetry",
    "archetypes",
    "corridor",
    "provisioning",
    "traffic",
    "resilience",
)
L1_MODULES: frozenset[str] = frozenset(f"meshscout.core.{name}" for name in L1_CORE_NAMES)

L2_MODULES: frozenset[str] = frozenset({
    "meshscout.core.__init__",
    "meshscout.core.registry",
    "meshscout.core.tower_registry",
    "meshscout.core.packs",
    "meshscout.core.staging",
    "meshscout.core.composite_viewshed",
})

L3_MODULES: frozenset[str] = frozenset({
    "meshscout.commands",
    "meshscout.reporting",
    "meshscout.mcp_tool_helpers",
    "meshscout.cli_tower_helpers",
})

L4_CLI_ALLOWED_MCP_IMPORTS: frozenset[str] = frozenset({
    "MeshScoutMCPServer",
    "create_fastmcp_app",
})

PRUNED_SCAN_DIRS: frozenset[str] = frozenset({
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "build",
    "dist",
    "out",
    "target",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".stigmerig",
    ".worktrees",
    "node_modules",
    "vendor",
    "coverage",
    ".tox",
})

SCAN_EXTENSIONS: frozenset[str] = frozenset({
    ".py",
    ".pyi",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".svelte",
    ".vue",
    ".html",
    ".css",
    ".yml",
    ".yaml",
    ".json",
    ".md",
    ".toml",
    ".sh",
    ".ps1",
})

EXCLUDED_TRAP_FILES: frozenset[str] = frozenset({
    "traps.json",
    "stigmerig.traps.json",
    "stigmerig.traps.baseline.json",
    "Trap_Invariants.json",
})

MAX_TRAP_SCAN_BYTES: int = 2 * 1024 * 1024


def _discover_source_modules() -> Dict[str, Path]:
    """Map canonical module names under SRC_ROOT to filesystem paths."""
    modules: Dict[str, Path] = {}
    for py_path in sorted(SRC_ROOT.rglob("*.py")):
        rel_parts = py_path.relative_to(SRC_ROOT).with_suffix("").parts
        mod_name = "meshscout." + ".".join(rel_parts)
        modules[mod_name] = py_path
    return modules


def _classify_module_layer(mod_name: str) -> Optional[int]:
    """Return architectural layer index (0..4) for a canonical module name."""
    if mod_name in L0_MODULES:
        return 0
    if mod_name in L1_MODULES:
        return 1
    if mod_name in L2_MODULES or mod_name == "meshscout.adapters.__init__" or mod_name.startswith("meshscout.adapters."):
        return 2
    if mod_name in L3_MODULES:
        return 3
    if (
        mod_name in {"meshscout.cli", "meshscout.mcp_server", "meshscout.web.__init__"}
        or mod_name.startswith("meshscout.web.")
    ):
        return 4
    return None


def _canonicalize_target(dotted: str, known_modules: Set[str]) -> Optional[str]:
    """Resolve a dotted import path to a canonical module name in known_modules."""
    if not dotted:
        return None
    if dotted in known_modules:
        return dotted
    init_candidate = f"{dotted}.__init__"
    if init_candidate in known_modules:
        return init_candidate
    cur = dotted
    while "." in cur:
        cur = cur.rsplit(".", 1)[0]
        if cur in known_modules:
            return cur
        cur_init = f"{cur}.__init__"
        if cur_init in known_modules:
            return cur_init
    return None


def _extract_meshscout_imports(
    mod_name: str,
    py_path: Path,
    known_modules: Set[str],
) -> List[Tuple[int, str, Optional[str]]]:
    """Extract (lineno, target_module, imported_symbol_or_None) for all meshscout imports."""
    tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
    parts = mod_name.split(".")
    is_pkg = parts[-1] == "__init__"
    pkg_parts = parts[:-1] if is_pkg else parts[:-1]

    imports: List[Tuple[int, str, Optional[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "meshscout" or alias.name.startswith("meshscout."):
                    target = _canonicalize_target(alias.name, known_modules)
                    if target is not None:
                        imports.append((node.lineno, target, None))
        elif isinstance(node, ast.ImportFrom):
            base_mod = node.module or ""
            if node.level > 0:
                anchor_len = len(pkg_parts) - (node.level - 1)
                if anchor_len <= 0:
                    continue
                anchor = ".".join(pkg_parts[:anchor_len])
                base_mod = f"{anchor}.{base_mod}" if base_mod else anchor

            if not (base_mod == "meshscout" or base_mod.startswith("meshscout.")):
                continue

            for alias in node.names:
                if alias.name == "*":
                    target = _canonicalize_target(base_mod, known_modules)
                    if target is not None:
                        imports.append((node.lineno, target, "*"))
                    continue
                sub_candidate = f"{base_mod}.{alias.name}"
                sub_target = _canonicalize_target(sub_candidate, known_modules)
                if sub_target is not None and (
                    sub_candidate in known_modules or f"{sub_candidate}.__init__" in known_modules
                ):
                    imports.append((node.lineno, sub_target, None))
                else:
                    target = _canonicalize_target(base_mod, known_modules)
                    if target is not None:
                        imports.append((node.lineno, target, alias.name))
    return imports


def test_acyclic_l0_to_l4_import_dag() -> None:
    """Enforce strict L0-L4 layered import DAG and L4 boundary isolation via AST."""
    assert len(L1_MODULES) == 14
    modules = _discover_source_modules()
    known_modules = set(modules.keys())

    unclassified = [m for m in sorted(known_modules) if _classify_module_layer(m) is None]
    assert not unclassified, f"Unclassified source modules found: {unclassified}"

    violations: List[str] = []
    acyclic_graph: Dict[str, Set[str]] = {}

    for mod_name, py_path in sorted(modules.items()):
        src_layer = _classify_module_layer(mod_name)
        assert src_layer is not None
        imports = _extract_meshscout_imports(mod_name, py_path, known_modules)
        deps: Set[str] = set()

        for lineno, target_mod, symbol in imports:
            if target_mod == mod_name:
                continue
            tgt_layer = _classify_module_layer(target_mod)
            assert tgt_layer is not None
            deps.add(target_mod)

            if src_layer == 0:
                violations.append(
                    f"{mod_name}:{lineno} (L0) must not import internal module {target_mod}"
                )
            elif src_layer in (1, 2, 3) and tgt_layer > src_layer:
                violations.append(
                    f"{mod_name}:{lineno} (L{src_layer}) imports upward into {target_mod} (L{tgt_layer})"
                )
            elif src_layer == 4:
                if mod_name == "meshscout.web.__init__" or mod_name.startswith("meshscout.web."):
                    if target_mod == "meshscout.cli" or target_mod == "meshscout.mcp_server":
                        violations.append(
                            f"{mod_name}:{lineno} (L4 web) must not import {target_mod}"
                        )
                elif mod_name == "meshscout.mcp_server":
                    if target_mod == "meshscout.cli" or target_mod == "meshscout.web.__init__" or target_mod.startswith("meshscout.web."):
                        violations.append(
                            f"{mod_name}:{lineno} (L4 mcp_server) must not import {target_mod}"
                        )
                elif mod_name == "meshscout.cli" and target_mod == "meshscout.mcp_server":
                    if symbol is None or symbol not in L4_CLI_ALLOWED_MCP_IMPORTS:
                        violations.append(
                            f"{mod_name}:{lineno} (L4 cli) imports disallowed symbol '{symbol or '*module*'}' from meshscout.mcp_server"
                        )

        if src_layer != 2:
            acyclic_graph[mod_name] = deps
        else:
            # Cross-layer edges out of L2 must still be acyclic; intra-L2 edges are allowed.
            acyclic_graph[mod_name] = {
                dep for dep in deps if _classify_module_layer(dep) != 2
            }

    assert not violations, "Architecture DAG layer violations:\n" + "\n".join(violations)

    visit_state: Dict[str, int] = {}

    def _find_cycle(node: str, trail: List[str]) -> Optional[List[str]]:
        visit_state[node] = 1
        for nxt in sorted(acyclic_graph.get(node, ())):
            state = visit_state.get(nxt, 0)
            if state == 1:
                idx = trail.index(nxt)
                return trail[idx:] + [nxt]
            if state == 0:
                found = _find_cycle(nxt, trail + [nxt])
                if found is not None:
                    return found
        visit_state[node] = 2
        return None

    for mod_name in sorted(acyclic_graph):
        if visit_state.get(mod_name, 0) == 0:
            cycle = _find_cycle(mod_name, [mod_name])
            assert cycle is None, f"Import cycle detected: {' -> '.join(cycle)}"


def test_regulatory_domain_fallback_parity() -> None:
    """Verify MCP and Web regulatory EIRP helpers resolve unknown domain + CA_QC identically."""
    mcp_res = mcp_tool_helpers.advise_eirp(
        tx_power_dbm=20.0,
        antenna_gain_dbi=3.0,
        domain="UNKNOWN_DOMAIN",
        region="CA_QC",
    )
    web_res = regulatory_routes.evaluate_regulatory_eirp_payload(
        domain="UNKNOWN_DOMAIN",
        region="CA_QC",
    )
    assert mcp_res["ok"] is True
    assert web_res["ok"] is True
    assert mcp_res["domain"] == "CA_ISED_RSS247"
    assert web_res["domain"] == "CA_ISED_RSS247"


def test_scorecard_parity() -> None:
    """Verify README scorecard metrics match live MCP manifests and North American regions."""
    script_path = REPO_ROOT / "scripts" / "check_scorecard_parity.py"
    spec = importlib.util.spec_from_file_location("check_scorecard_parity", script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    ok, errors = mod.verify_scorecard_parity(REPO_ROOT)
    assert ok and not errors, f"Scorecard parity check failed: {errors}"


def _compile_glob_regex(glob_pat: str) -> re.Pattern[str]:
    """Compile a POSIX glob pattern into an anchored segment-aware regular expression."""
    pat = glob_pat.strip().replace("\\", "/")
    while pat.startswith("./"):
        pat = pat[2:]
    if pat == "**":
        return re.compile(r"\A.*\Z")

    parts: List[str] = [r"\A"]
    i = 0
    n = len(pat)
    while i < n:
        if pat.startswith("**/", i):
            parts.append(r"(?:.+/)?")
            i += 3
        elif pat.startswith("/**", i) and i + 3 == n:
            parts.append(r"(?:/.*)?")
            i += 3
        elif pat.startswith("/**", i) and i + 3 < n and pat[i + 3] == "/":
            parts.append(r"/(?:.+/)?")
            i += 4
        elif pat.startswith("**", i):
            parts.append(r".*")
            i += 2
        elif pat[i] == "*":
            parts.append(r"[^/]*")
            i += 1
        elif pat[i] == "?":
            parts.append(r"[^/]")
            i += 1
        elif pat[i] == "[":
            j = i + 1
            if j < n and pat[j] in ("!", "^"):
                j += 1
            if j < n and pat[j] == "]":
                j += 1
            while j < n and pat[j] != "]":
                j += 1
            if j < n:
                inner = pat[i + 1 : j]
                if inner.startswith("!"):
                    inner = "^" + inner[1:]
                parts.append(f"[{inner.replace(chr(92), chr(92) * 2)}]")
                i = j + 1
            else:
                parts.append(re.escape("["))
                i += 1
        else:
            parts.append(re.escape(pat[i]))
            i += 1

    parts.append(r"\Z")
    return re.compile("".join(parts))


def _matches_target_globs(rel_posix: PurePosixPath, target_globs: Sequence[str]) -> bool:
    """Evaluate positive and negated target_globs against a repo-relative POSIX path."""
    if not target_globs:
        return True
    rel_str = rel_posix.as_posix()
    neg_globs = [g[1:] for g in target_globs if g.startswith("!")]
    pos_globs = [g for g in target_globs if not g.startswith("!")]

    if any(_compile_glob_regex(ng).match(rel_str) is not None for ng in neg_globs):
        return False
    if not pos_globs:
        return True
    return any(_compile_glob_regex(pg).match(rel_str) is not None for pg in pos_globs)


def _iter_repo_scan_files(repo_root: Path) -> Iterable[Tuple[Path, PurePosixPath]]:
    """Yield scannable repository files while pruning build, cache, vcs, and vendor trees."""
    stack: List[Path] = [repo_root]
    while stack:
        cur_dir = stack.pop()
        for child in sorted(cur_dir.iterdir(), reverse=True):
            if child.is_symlink():
                continue
            if child.is_dir():
                if child.name.lower() not in PRUNED_SCAN_DIRS:
                    stack.append(child)
                continue
            if not child.is_file():
                continue
            if child.name in EXCLUDED_TRAP_FILES:
                continue
            if child.suffix.lower() not in SCAN_EXTENSIONS:
                continue
            try:
                if child.stat().st_size > MAX_TRAP_SCAN_BYTES:
                    continue
            except OSError:
                continue
            rel = PurePosixPath(child.relative_to(repo_root).as_posix())
            yield child, rel


def test_polyglot_trap_ratchet_zero_regression() -> None:
    """Enforce zero unbaselined or banned polyglot trap violations using pure stdlib."""
    registry_path = REPO_ROOT / "stigmerig.traps.json"
    baseline_path = REPO_ROOT / "stigmerig.traps.baseline.json"
    assert registry_path.is_file(), f"Missing trap registry: {registry_path}"
    assert baseline_path.is_file(), f"Missing trap baseline: {baseline_path}"

    registry_data = json.loads(registry_path.read_text(encoding="utf-8"))
    promoted_traps = [
        t for t in registry_data.get("traps", [])
        if isinstance(t, dict) and t.get("status") == "promoted"
    ]
    promoted_ids = {str(t.get("trap_id")) for t in promoted_traps}
    expected_ids = {
        "TRAP-GEN-001",
        "TRAP-PY-001",
        "TRAP-PY-002",
        "TRAP-TS-001",
        "TRAP-TS-002",
        "TRAP-VER-001",
        "TRAP-VER-002",
        "TRAP-VER-003",
    }
    assert promoted_ids == expected_ids, f"Unexpected promoted trap set: {sorted(promoted_ids)}"

    baseline_data = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline_counts: Dict[Tuple[str, str, str], int] = {}
    for entry in baseline_data.get("entries", []):
        fp = (
            str(entry["file"]),
            str(entry["trap_id"]),
            str(entry["snippet_sha256"]),
        )
        baseline_counts[fp] = baseline_counts.get(fp, 0) + int(entry["count"])

    found_counts: Dict[Tuple[str, str, str], int] = {}
    zero_tolerance_hits: List[str] = []

    for file_path, rel_posix in _iter_repo_scan_files(REPO_ROOT):
        rel_str = rel_posix.as_posix()
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        lines = content.splitlines()

        for trap in promoted_traps:
            target_globs = trap.get("target_globs") or []
            if not _matches_target_globs(rel_posix, target_globs):
                continue

            trap_id = str(trap["trap_id"])
            pattern = str(trap["trigger_pattern"])
            match_mode = str(trap.get("match_mode") or "line")

            snippets: List[str] = []
            if match_mode == "multiline":
                for match in re.finditer(pattern, content, re.MULTILINE):
                    snippets.append(re.sub(r"\s+", " ", content[match.start() : match.end()]).strip()[:100])
            else:
                compiled = re.compile(pattern)
                for line in lines:
                    if compiled.search(line):
                        snippets.append(line.strip()[:100])

            for snippet in snippets:
                if trap_id == "TRAP-PY-002" or trap_id.startswith("TRAP-TS-") or trap_id == "TRAP-GEN-001":
                    zero_tolerance_hits.append(f"{trap_id} in {rel_str}: {snippet}")
                digest = hashlib.sha256(snippet.encode("utf-8")).hexdigest()
                fp = (rel_str, trap_id, digest)
                found_counts[fp] = found_counts.get(fp, 0) + 1

    assert not zero_tolerance_hits, (
        "Zero-tolerance trap violations detected:\n" + "\n".join(zero_tolerance_hits)
    )

    regressions: List[str] = []
    for fp, found in sorted(found_counts.items()):
        allowed = baseline_counts.get(fp, 0)
        if found > allowed:
            rel_str, trap_id, digest = fp
            regressions.append(
                f"{trap_id} in {rel_str} (sha256={digest[:12]}): found {found} > baseline {allowed}"
            )

    assert not regressions, "Trap ratchet regressions above baseline:\n" + "\n".join(regressions)
