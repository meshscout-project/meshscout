#!/usr/bin/env python3
"""MeshScout End-User Download and Installation Validation Suite.

Validates the public release instructions from an end-user perspective.
Automates cloning the repository into a clean temporary directory,
initializing an isolated Python virtual environment, executing pip install,
and verifying CLI subcommands, web workbench startup, and MCP server registration.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

DEFAULT_REPO_URL = "https://github.com/meshscout-project/meshscout.git"


def run_cmd(
    cmd: list[str],
    cwd: Optional[Path] = None,
    env: Optional[dict] = None,
    check: bool = True,
    timeout: Optional[float] = 300.0,
) -> subprocess.CompletedProcess:
    """Execute a subprocess command with captured output."""
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=merged_env,
        capture_output=True,
        text=True,
        check=check,
        timeout=timeout,
    )


def test_user_install(
    source_url: str = DEFAULT_REPO_URL,
    local_source: Optional[Path] = None,
    branch: str = "main",
    use_venv: bool = True,
    minimal: bool = False,
    run_tests: bool = False,
    keep_temp: bool = False,
) -> bool:
    """Execute end-to-end installation validation in an isolated sandbox."""
    t0_total = time.perf_counter()
    temp_dir = tempfile.mkdtemp(prefix="meshscout_install_test_")
    work_dir = Path(temp_dir).resolve()
    repo_dir = work_dir / "meshscout"

    print("================================================================")
    print(" MeshScout End-User Download & Installation Validation")
    print("================================================================")
    print(f"Isolated Sandbox: {work_dir}")
    print(f"Python Host:      {sys.executable} ({sys.version.split()[0]})")
    print(f"Target Source:    {local_source if local_source else source_url}")
    print("----------------------------------------------------------------")

    try:
        # Phase 1: Download / Clone
        print("[Phase 1] Downloading repository...")
        t_phase = time.perf_counter()
        if local_source and local_source.is_dir():
            print(f"  Copying local source tree from: {local_source}")
            shutil.copytree(
                local_source,
                repo_dir,
                ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".venv", "venv"),
            )
        else:
            print(f"  Cloning {source_url} (branch: {branch})...")
            proc = run_cmd(["git", "clone", "--depth", "1", "--branch", branch, source_url, str(repo_dir)])
            if proc.returncode != 0:
                print(f"  [FAIL] Git clone failed:\n{proc.stderr}", file=sys.stderr)
                return False
        elapsed = time.perf_counter() - t_phase
        print(f"  [PASS] Repository acquired ({elapsed:.2f}s).")

        # Verify key distribution files
        required_files = ["pyproject.toml", "README.md", "LICENSE", "src/meshscout/__init__.py"]
        for rel_path in required_files:
            file_path = repo_dir / rel_path
            assert file_path.is_file(), f"Missing required file: {rel_path}"
        print("  [PASS] Key repository files verified.")

        # Phase 2: Virtual Environment Setup
        if use_venv:
            venv_dir = work_dir / ".venv"
            print(f"[Phase 2] Creating clean virtual environment at {venv_dir}...")
            t_phase = time.perf_counter()
            proc = run_cmd([sys.executable, "-m", "venv", str(venv_dir)])
            if proc.returncode != 0:
                print(f"  [FAIL] Venv creation failed:\n{proc.stderr}", file=sys.stderr)
                return False

            if os.name == "nt":
                python_bin = venv_dir / "Scripts" / "python.exe"
                pip_bin = venv_dir / "Scripts" / "pip.exe"
                cli_bin = venv_dir / "Scripts" / "meshscout.exe"
                pytest_bin = venv_dir / "Scripts" / "pytest.exe"
            else:
                python_bin = venv_dir / "bin" / "python"
                pip_bin = venv_dir / "bin" / "pip"
                cli_bin = venv_dir / "bin" / "meshscout"
                pytest_bin = venv_dir / "bin" / "pytest"

            assert python_bin.is_file(), f"Python binary not found at {python_bin}"
            elapsed = time.perf_counter() - t_phase
            print(f"  [PASS] Virtual environment created ({elapsed:.2f}s).")
        else:
            python_bin = Path(sys.executable)
            pip_bin = Path("pip")
            cli_bin = Path("meshscout")
            pytest_bin = Path("pytest")

        # Phase 3: Package Installation
        install_target = str(repo_dir) if minimal else f"{repo_dir}[web,dev]"
        print(f"[Phase 3] Installing MeshScout ('pip install -e \"{install_target}\"')...")
        t_phase = time.perf_counter()
        proc = run_cmd([str(pip_bin), "install", "-e", install_target])
        if proc.returncode != 0:
            print(f"  [FAIL] Pip install failed:\n{proc.stderr}\n{proc.stdout}", file=sys.stderr)
            return False
        elapsed = time.perf_counter() - t_phase
        print(f"  [PASS] Package installed successfully ({elapsed:.2f}s).")

        # Phase 4: Import and Version Check
        print("[Phase 4] Validating module import and version metadata...")
        proc = run_cmd([str(python_bin), "-c", "import meshscout; print(meshscout.__version__)"])
        assert proc.returncode == 0, f"Module import failed: {proc.stderr}"
        version_str = proc.stdout.strip()
        print(f"  [PASS] Module imported cleanly. Detected version: {version_str}")

        # Phase 5: CLI Entrypoint Verification
        print("[Phase 5] Validating CLI executable ('meshscout --help')...")
        proc = run_cmd([str(cli_bin), "--help"])
        assert proc.returncode == 0, f"CLI help failed: {proc.stderr}"
        stdout_help = proc.stdout
        assert "meshscout" in stdout_help.lower(), "CLI help missing binary name"
        for subcmd in ["serve", "regions", "packs", "scout", "link", "mcp"]:
            assert subcmd in stdout_help, f"CLI help missing expected subcommand '{subcmd}'"
        print("  [PASS] CLI entrypoint functional with all documented subcommands.")

        # Phase 6: Subcommand Instruction Execution
        print("[Phase 6] Validating README subcommands...")

        # 6a: regions list
        proc = run_cmd([str(cli_bin), "regions", "list", "--country", "US"])
        assert proc.returncode == 0, f"regions list failed: {proc.stderr}"
        assert "VT - Vermont" in proc.stdout or "Vermont" in proc.stdout, "Vermont missing from US regions"
        print("  [PASS] 'meshscout regions list --country US' executed successfully.")

        # 6b: packs list
        proc = run_cmd([str(cli_bin), "packs", "list"])
        assert proc.returncode == 0, f"packs list failed: {proc.stderr}"
        print("  [PASS] 'meshscout packs list' executed successfully.")

        # 6c: presets verification
        code_presets = (
            "from meshscout.core.presets import PROTOCOL_PROFILES, HARDWARE_PRESETS, build_radio_config; "
            "prof = PROTOCOL_PROFILES.get('MESHCORE_NARROW'); "
            "assert prof is not None and prof.network_family == 'MeshCore'; "
            "assert 'RAK4631_SOLAR' in HARDWARE_PRESETS; "
            "cfg = build_radio_config('RAK4631_SOLAR', 'MESHCORE_NARROW', 'WINTER_LEAF_OFF'); "
            "assert cfg.ok is True and cfg.value is not None; "
            "print('Presets verified successfully')"
        )
        proc = run_cmd([str(python_bin), "-c", code_presets])
        assert proc.returncode == 0, f"Presets check failed: {proc.stderr}"
        print("  [PASS] Radio presets and MeshCore Narrow protocol profile verified.")

        # Phase 7: Web Workbench Initialization
        print("[Phase 7] Validating Web Workbench FastAPI application...")
        code_web = (
            "from meshscout.web.app import create_web_app; "
            "app = create_web_app(); "
            "assert app is not None; "
            "print('FastAPI app initialized successfully')"
        )
        proc = run_cmd([str(python_bin), "-c", code_web])
        assert proc.returncode == 0, f"Web app initialization failed: {proc.stderr}"
        print("  [PASS] Web workbench FastAPI application initialized cleanly.")

        # Phase 8: MCP Server Registration
        print("[Phase 8] Validating Model Context Protocol (MCP) server...")
        code_mcp = (
            "from meshscout.mcp_server import MeshScoutMCPServer; "
            "srv = MeshScoutMCPServer(); "
            "res = srv.handle_request({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}}); "
            "tools = res.get('result', {}).get('tools', []); "
            "assert len(tools) == 14, f'Expected 14 tools, got {len(tools)}'; "
            "assert 'scout_repeater_sites' in [t['name'] for t in tools]; "
            "print(f'MCP Server initialized with {len(tools)} tools')"
        )
        proc = run_cmd([str(python_bin), "-c", code_mcp])
        assert proc.returncode == 0, f"MCP server check failed: {proc.stderr}"
        print("  [PASS] MCP Day-0 server initialized with 14 tools.")

        # Phase 9: Test Suite Execution (Optional / Smoke Test)
        if run_tests:
            print("[Phase 9] Running pytest verification suite in isolated environment...")
            t_phase = time.perf_counter()
            smoke_targets = [
                str(repo_dir / "tests" / "test_contracts.py"),
                str(repo_dir / "tests" / "test_presets_and_geocoder.py"),
            ]
            proc = run_cmd([str(pytest_bin), *smoke_targets, "-v"])
            assert proc.returncode == 0, f"Pytest failed:\n{proc.stderr}\n{proc.stdout}"
            elapsed = time.perf_counter() - t_phase
            print(f"  [PASS] Core test suite passed in isolated environment ({elapsed:.2f}s).")

        total_elapsed = time.perf_counter() - t0_total
        print("----------------------------------------------------------------")
        print(f"RESULT: ALL CHECKS PASSED in {total_elapsed:.2f}s")
        print("The repository download and installation instructions are verified.")
        print("================================================================")
        return True

    except Exception as exc:
        print(f"\n[FAIL] Validation encountered an error:\n{exc}", file=sys.stderr)
        return False

    finally:
        if keep_temp:
            print(f"[NOTE] Sandbox preserved at: {work_dir}")
        else:
            shutil.rmtree(work_dir, ignore_errors=True)


def main() -> int:
    """CLI argument parser and entrypoint."""
    parser = argparse.ArgumentParser(
        description="Test download, venv creation, and installation of MeshScout from an end-user perspective."
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_REPO_URL,
        help=f"Target Git repository URL to clone (default: {DEFAULT_REPO_URL})",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Test against local working directory rather than cloning from remote Git",
    )
    parser.add_argument(
        "--local-path",
        default=None,
        help="Explicit local repository directory to test",
    )
    parser.add_argument(
        "--branch",
        default="main",
        help="Git branch to clone (default: main)",
    )
    parser.add_argument(
        "--no-venv",
        action="store_true",
        help="Skip creating a virtual environment (use host Python)",
    )
    parser.add_argument(
        "--minimal",
        action="store_true",
        help="Test minimal install without web and dev extras",
    )
    parser.add_argument(
        "--run-tests",
        action="store_true",
        help="Run pytest smoke tests inside the newly installed environment",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep the temporary sandbox directory after completion for inspection",
    )

    args = parser.parse_args()

    local_src: Optional[Path] = None
    if args.local:
        # Default to the parent of the scripts folder
        local_src = Path(__file__).resolve().parent.parent
    elif args.local_path:
        local_src = Path(args.local_path).resolve()

    success = test_user_install(
        source_url=args.url,
        local_source=local_src,
        branch=args.branch,
        use_venv=not args.no_venv,
        minimal=args.minimal,
        run_tests=args.run_tests,
        keep_temp=args.keep,
    )
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
