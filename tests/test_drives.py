"""Tests for removable drive discovery and storage safety validation."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from meshscout.adapters.drives import (
    RemovableDriveInfo,
    list_removable_drives,
    validate_field_kit_target_directory,
)
from meshscout.web.app import create_web_app


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    """Provide a TestClient with an isolated database."""
    app = create_web_app(db_path=tmp_path / "test_mesh_state.db")
    return TestClient(app)


def test_removable_drive_info_creation_and_validation() -> None:
    """Test RemovableDriveInfo schema validation and serialization."""
    drive = RemovableDriveInfo(
        device_id="E:",
        mount_point="E:\\",
        volume_label="USB_KIT",
        total_bytes=32_000_000_000,
        free_bytes=16_000_000_000,
        filesystem="FAT32",
        is_removable=True,
    )
    assert drive.device_id == "E:"
    assert drive.mount_point == "E:\\"
    assert drive.volume_label == "USB_KIT"
    assert drive.total_bytes == 32_000_000_000
    assert drive.free_bytes == 16_000_000_000
    assert drive.filesystem == "FAT32"
    assert drive.is_removable is True

    dumped = drive.model_dump()
    assert dumped["device_id"] == "E:"
    assert dumped["is_removable"] is True

    # Missing required field must raise ValidationError
    with pytest.raises(ValidationError):
        RemovableDriveInfo(
            device_id="E:",
            mount_point="E:\\",
            # missing volume_label, total_bytes, etc.
        )


def test_list_removable_drives_executes_without_error() -> None:
    """Verify list_removable_drives runs on the current OS without error."""
    drives = list_removable_drives()
    assert isinstance(drives, list)
    for drive in drives:
        assert isinstance(drive, RemovableDriveInfo)
        assert isinstance(drive.total_bytes, int)
        assert isinstance(drive.free_bytes, int)
        assert isinstance(drive.is_removable, bool)


def test_list_removable_drives_platform_mocking() -> None:
    """Test simulated platform drive detection."""
    # Test Linux branch
    fake_mount_data = "/dev/sdb1 /mnt/usb vfat rw 0 0\n"
    with patch("sys.platform", "linux"):
        with patch("pathlib.Path.is_dir", return_value=False):
            with patch("pathlib.Path.is_file", return_value=True):
                with patch("builtins.open", pytest.importorskip("unittest.mock").mock_open(read_data=fake_mount_data)):
                    res = list_removable_drives()
                    assert isinstance(res, list)

    # Test Darwin branch
    with patch("sys.platform", "darwin"):
        with patch("pathlib.Path.is_dir", return_value=False):
            res = list_removable_drives()
            assert isinstance(res, list)


def test_validate_field_kit_target_directory_success(tmp_path: Path) -> None:
    """Test validation with a valid existing directory and a newly created nested directory."""
    # Existing directory with default required free space
    ok, err = validate_field_kit_target_directory(tmp_path)
    assert ok is True
    assert err == ""

    # Nested non-existent directory that can be created
    target_subdir = tmp_path / "sub" / "field_kit"
    ok, err = validate_field_kit_target_directory(target_subdir, required_free_bytes=1024)
    assert ok is True
    assert err == ""
    assert target_subdir.is_dir()


def test_validate_field_kit_target_directory_insufficient_space(tmp_path: Path) -> None:
    """Test validation failure when available free space is below the required threshold."""
    # Require an absurdly large free space amount (1 Exabyte)
    ok, err = validate_field_kit_target_directory(tmp_path, required_free_bytes=10**18)
    assert ok is False
    assert "Insufficient disk space" in err

    # Mock shutil.disk_usage returning very low free bytes
    with patch("shutil.disk_usage", return_value=MagicMock(total=1_000_000, used=990_000, free=10_000)):
        ok, err = validate_field_kit_target_directory(tmp_path, required_free_bytes=250 * 1024 * 1024)
        assert ok is False
        assert "Insufficient disk space" in err
        assert "10000 bytes available" in err


def test_validate_field_kit_target_directory_file_conflict(tmp_path: Path) -> None:
    """Test validation failure when the target path is an existing file, not a directory."""
    conflicting_file = tmp_path / "not_a_directory.txt"
    conflicting_file.write_text("meshscout", encoding="utf-8")

    ok, err = validate_field_kit_target_directory(conflicting_file)
    assert ok is False
    assert "not a directory" in err


def test_p0_safety_invariant_no_destructive_commands() -> None:
    """CRITICAL P0 SAFETY INVARIANT: Ensure adapter never contains disk destruction or partitioning commands."""
    banned_tokens = ["format ", "mkfs", "diskpart", "newfs", "wipefs", "dd if="]
    adapter_path = Path(__file__).resolve().parent.parent / "src" / "meshscout" / "adapters" / "drives.py"
    assert adapter_path.is_file(), f"Adapter file not found at {adapter_path}"

    content = adapter_path.read_text(encoding="utf-8")
    for token in banned_tokens:
        assert token not in content, (
            f"VIOLATION OF P0 SAFETY INVARIANT: Banned token '{token}' discovered in {adapter_path}!"
        )


def test_api_get_removable_drives(client: TestClient) -> None:
    """Test GET /api/system/drives endpoint returns 200 and expected payload structure."""
    resp = client.get("/api/system/drives")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "drives" in data
    assert isinstance(data["drives"], list)
    assert data["count"] == len(data["drives"])

    # If any drives are returned, verify expected keys
    for d in data["drives"]:
        assert "device_id" in d
        assert "mount_point" in d
        assert "volume_label" in d
        assert "total_bytes" in d
        assert "free_bytes" in d
        assert "filesystem" in d
        assert "is_removable" in d
