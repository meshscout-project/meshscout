#!/usr/bin/env python3
"""Offline stdlib PEP 669 statement coverage gate for MeshScout."""

from __future__ import annotations

import argparse
import dis
import os
from pathlib import Path
import sys
from typing import Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = str(REPO_ROOT / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)


def _collect_lines(code: object) -> set[int]:
    """Return executable line numbers excluding Python 3.14 synthetic __annotate__ consts."""
    lines = {line for _, line in dis.findlinestarts(code) if line}
    for const in getattr(code, "co_consts", ()):
        if isinstance(const, type(code)) and not const.co_name.startswith("__annotate"):
            lines |= _collect_lines(const)
    return lines


def _find_free_tool_id() -> Optional[int]:
    """Return the first available sys.monitoring tool ID in (3, 4, 5), or None."""
    for tid in (3, 4, 5):
        if sys.monitoring.get_tool(tid) is None:
            return tid
    return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run pytest with PEP 669 line coverage and enforce --min-pct floor."""
    parser = argparse.ArgumentParser(description="Enforce MeshScout statement coverage floor.")
    parser.add_argument("--min-pct", type=float, default=85.0, help="Minimum required coverage percentage.")
    parser.add_argument("--src-dir", type=Path, default=REPO_ROOT / "src" / "meshscout", help="Package root to measure.")
    parser.add_argument("--pytest-args", nargs=argparse.REMAINDER, default=None, help="Arguments passed to pytest.")
    args = parser.parse_args(argv)

    pytest_args = list(args.pytest_args) if args.pytest_args else ["-q", str(REPO_ROOT / "tests")]
    if pytest_args and pytest_args[0] == "--":
        pytest_args = pytest_args[1:] or ["-q", str(REPO_ROOT / "tests")]

    import pytest

    if sys.version_info < (3, 12) or not hasattr(sys, "monitoring"):
        rc = int(pytest.main(pytest_args))
        print("[SKIP] PEP 669 sys.monitoring requires Python >= 3.12; returning pytest exit code.")
        return rc

    tid = _find_free_tool_id()
    if tid is None:
        return int(pytest.main(pytest_args))

    src_dir = args.src_dir.resolve()
    all_py = sorted(os.path.normcase(str(p.resolve())) for p in src_dir.rglob("*.py"))
    py_set = set(all_py)
    fn_map: dict[str, str] = {}
    executed: dict[str, set[int]] = {p: set() for p in all_py}
    events = sys.monitoring.events

    def on_line(code: object, line: int) -> object:
        raw = code.co_filename  # type: ignore[attr-defined]
        norm = fn_map.get(raw)
        if norm is None:
            cand = os.path.normcase(os.path.abspath(raw))
            norm = cand if cand in py_set else ""
            fn_map[raw] = norm
        if norm and line and not code.co_name.startswith("__annotate"):  # type: ignore[attr-defined]
            executed[norm].add(line)
        return sys.monitoring.DISABLE

    sys.monitoring.use_tool_id(tid, "meshscout_cov")
    try:
        sys.monitoring.register_callback(tid, events.LINE, on_line)
        sys.monitoring.set_events(tid, events.LINE)
        rc = int(pytest.main(pytest_args))
    finally:
        sys.monitoring.set_events(tid, 0)
        sys.monitoring.register_callback(tid, events.LINE, None)
        sys.monitoring.free_tool_id(tid)

    if rc != 0:
        return rc

    tot_hit = 0
    tot_all = 0
    for mod_path in all_py:
        src_text = Path(mod_path).read_text(encoding="utf-8")
        all_lines = _collect_lines(compile(src_text, mod_path, "exec"))
        tot_hit += len(executed[mod_path] & all_lines)
        tot_all += len(all_lines)

    pct = 100.0 * tot_hit / max(1, tot_all)
    if pct >= args.min_pct:
        print(
            f"[PASS] Statement coverage verified: {tot_hit}/{tot_all} "
            f"({pct:.2f}% >= {args.min_pct:.2f}%) across {len(all_py)} modules."
        )
        return 0
    print(f"[FAIL] Statement coverage {pct:.2f}% below floor {args.min_pct:.2f}% ({tot_hit}/{tot_all}).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
