"""Unit tests for Living Mesh multi-workspace registry isolation and discovery."""

from __future__ import annotations

from pathlib import Path
import pytest

from meshscout.core.contracts import Coordinate, SiteType
from meshscout.core.registry import (
    DeploymentStatus,
    LivingMeshRegistry,
    RegisteredNode,
    list_available_workspaces,
)


def test_workspace_id_validation_accepts_valid(tmp_path: Path) -> None:
    """Verify that valid workspace identifiers are accepted without error."""
    valid_ids = ["default", "club_alpha", "champlain-valley", "ny_adirondack"]
    for wid in valid_ids:
        db_file = tmp_path / f"{wid}.db"
        reg = LivingMeshRegistry(db_path=db_file, workspace_id=wid)
        assert reg.workspace_id == wid
        assert reg.db_path == db_file


def test_workspace_id_validation_rejects_invalid(tmp_path: Path) -> None:
    """Verify that invalid workspace identifiers or path traversal attempts raise ValueError."""
    invalid_ids = ["../evil", ";DROP TABLE", "has space", "", "nested/path", "toolong" * 10, "back\\slash"]
    for wid in invalid_ids:
        with pytest.raises(ValueError, match="Invalid workspace_id"):
            LivingMeshRegistry(db_path=tmp_path / "test.db", workspace_id=wid)

        with pytest.raises(ValueError, match="Invalid workspace_id"):
            LivingMeshRegistry(workspace_id=wid)


def test_database_isolation_between_workspaces(tmp_path: Path) -> None:
    """Verify complete database isolation between two distinct workspace registries."""
    db_a = tmp_path / "workspaces" / "club_a" / "mesh_state.db"
    db_b = tmp_path / "workspaces" / "club_b" / "mesh_state.db"

    reg_a = LivingMeshRegistry(db_path=db_a, workspace_id="club_a")
    reg_b = LivingMeshRegistry(db_path=db_b, workspace_id="club_b")

    node_a = RegisteredNode(
        site_id="NODE-CLUB-A-01",
        name="Club Alpha Repeater",
        coordinate=Coordinate(lat=44.4906, lon=-73.1112, elevation_m=110.0),
        height_agl_m=15.0,
        site_type=SiteType.MOUNTAIN_PEAK,
        status=DeploymentStatus.ACTIVE_ON_AIR,
        hardware_preset="RAK4631_SOLAR",
        owner="W1AAA",
        is_public_land=True,
        notes="Club Alpha primary repeater",
        source_url="https://example.com/club_a",
        updated_at="2026-10-29T12:00:00Z",
    )

    insert_res = reg_a.insert_node(node_a)
    assert insert_res.ok

    nodes_a = reg_a.list_nodes()
    assert len(nodes_a) == 1
    assert nodes_a[0].site_id == "NODE-CLUB-A-01"

    nodes_b = reg_b.list_nodes()
    assert len(nodes_b) == 0


def test_list_available_workspaces(tmp_path: Path) -> None:
    """Verify scanning and discovery of available workspaces on disk."""
    # 1. Initially empty directory
    assert list_available_workspaces(base_dir=tmp_path) == []

    # 2. Add root mesh_state.db for default workspace
    default_db = tmp_path / "mesh_state.db"
    LivingMeshRegistry(db_path=default_db, workspace_id="default")
    assert list_available_workspaces(base_dir=tmp_path) == ["default"]

    # 3. Add valid workspace directories with mesh_state.db
    ws_adirondack = tmp_path / "workspaces" / "ny_adirondack" / "mesh_state.db"
    ws_alpha = tmp_path / "workspaces" / "club_alpha" / "mesh_state.db"
    LivingMeshRegistry(db_path=ws_adirondack, workspace_id="ny_adirondack")
    LivingMeshRegistry(db_path=ws_alpha, workspace_id="club_alpha")

    # 4. Add invalid or empty workspace directory (should be ignored)
    (tmp_path / "workspaces" / "empty_ws").mkdir(parents=True, exist_ok=True)
    invalid_dir = tmp_path / "workspaces" / "invalid space"
    invalid_dir.mkdir(parents=True, exist_ok=True)
    (invalid_dir / "mesh_state.db").touch()

    discovered = list_available_workspaces(base_dir=tmp_path)
    assert discovered == ["club_alpha", "default", "ny_adirondack"]


def test_default_home_path_resolution(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify that omitting db_path properly constructs paths under Path.home() / .meshscout."""
    fake_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

    reg_default = LivingMeshRegistry(workspace_id="default")
    assert reg_default.db_path == fake_home / ".meshscout" / "mesh_state.db"
    assert reg_default.db_path.is_file()

    reg_custom = LivingMeshRegistry(workspace_id="champlain-valley")
    assert reg_custom.db_path == fake_home / ".meshscout" / "workspaces" / "champlain-valley" / "mesh_state.db"
    assert reg_custom.db_path.is_file()

    workspaces = list_available_workspaces()
    assert workspaces == ["champlain-valley", "default"]
