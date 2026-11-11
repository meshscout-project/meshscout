"""Removable drive discovery and storage validation adapter.

Provides cross-platform inspection of attached removable storage devices
and validation of target field-kit export directories.
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import shutil
import sys
from typing import List, Tuple, Union

from pydantic import BaseModel


class RemovableDriveInfo(BaseModel):
    device_id: str
    mount_point: str
    volume_label: str
    total_bytes: int
    free_bytes: int
    filesystem: str
    is_removable: bool


def _list_removable_drives_windows() -> List[RemovableDriveInfo]:
    results: List[RemovableDriveInfo] = []
    drive_removable_code = 2
    try:
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for i in range(26):
            if bitmask & (1 << i):
                letter = chr(ord("A") + i)
                drive_str = f"{letter}:\\"
                try:
                    dtype = ctypes.windll.kernel32.GetDriveTypeW(drive_str)
                    if dtype == drive_removable_code:
                        vol_name_buf = ctypes.create_unicode_buffer(1024)
                        fs_name_buf = ctypes.create_unicode_buffer(1024)
                        ctypes.windll.kernel32.GetVolumeInformationW(
                            ctypes.c_wchar_p(drive_str),
                            vol_name_buf,
                            len(vol_name_buf),
                            None,
                            None,
                            None,
                            fs_name_buf,
                            len(fs_name_buf),
                        )
                        usage = shutil.disk_usage(drive_str)
                        results.append(
                            RemovableDriveInfo(
                                device_id=f"{letter}:",
                                mount_point=drive_str,
                                volume_label=vol_name_buf.value,
                                total_bytes=usage.total,
                                free_bytes=usage.free,
                                filesystem=fs_name_buf.value,
                                is_removable=True,
                            )
                        )
                except Exception:
                    continue
    except Exception:
        pass
    return results


def _list_removable_drives_darwin() -> List[RemovableDriveInfo]:
    results: List[RemovableDriveInfo] = []
    volumes_dir = Path("/Volumes")
    if not volumes_dir.is_dir():
        return results
    try:
        for entry in volumes_dir.iterdir():
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            if entry.name in ("Macintosh HD", "Macintosh HD - Data"):
                continue
            mount_path = str(entry.resolve())
            try:
                usage = shutil.disk_usage(mount_path)
            except Exception:
                continue
            results.append(
                RemovableDriveInfo(
                    device_id=mount_path,
                    mount_point=mount_path,
                    volume_label=entry.name,
                    total_bytes=usage.total,
                    free_bytes=usage.free,
                    filesystem="unknown",
                    is_removable=True,
                )
            )
    except Exception:
        pass
    return results


def _list_removable_drives_linux() -> List[RemovableDriveInfo]:
    results: List[RemovableDriveInfo] = []
    candidate_dirs: List[Path] = []
    user = os.environ.get("USER", "")
    if user:
        candidate_dirs.append(Path(f"/media/{user}"))
        candidate_dirs.append(Path(f"/run/media/{user}"))
    candidate_dirs.append(Path("/media"))
    candidate_dirs.append(Path("/mnt"))

    seen_mounts = set()
    try:
        removable_devs = set()
        sys_block = Path("/sys/block")
        if sys_block.is_dir():
            for block in sys_block.iterdir():
                removable_file = block / "removable"
                if removable_file.is_file():
                    try:
                        if removable_file.read_text(encoding="utf-8").strip() == "1":
                            removable_devs.add(block.name)
                    except Exception:
                        pass

        mounts_file = Path("/proc/mounts")
        if mounts_file.is_file():
            with open(mounts_file, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 3:
                        dev_path, mnt_point, fs_type = parts[0], parts[1], parts[2]
                        is_rem = any(dev_name in dev_path for dev_name in removable_devs)
                        if is_rem and mnt_point not in seen_mounts and mnt_point != "/":
                            try:
                                usage = shutil.disk_usage(mnt_point)
                                results.append(
                                    RemovableDriveInfo(
                                        device_id=dev_path,
                                        mount_point=mnt_point,
                                        volume_label=os.path.basename(mnt_point),
                                        total_bytes=usage.total,
                                        free_bytes=usage.free,
                                        filesystem=fs_type,
                                        is_removable=True,
                                    )
                                )
                                seen_mounts.add(mnt_point)
                            except Exception:
                                pass

        for cdir in candidate_dirs:
            if cdir.is_dir():
                for sub in cdir.iterdir():
                    sub_str = str(sub)
                    if sub.is_dir() and sub_str not in seen_mounts:
                        try:
                            usage = shutil.disk_usage(sub_str)
                            results.append(
                                RemovableDriveInfo(
                                    device_id=sub_str,
                                    mount_point=sub_str,
                                    volume_label=sub.name,
                                    total_bytes=usage.total,
                                    free_bytes=usage.free,
                                    filesystem="unknown",
                                    is_removable=True,
                                )
                            )
                            seen_mounts.add(sub_str)
                        except Exception:
                            pass
    except Exception:
        pass
    return results


def list_removable_drives() -> List[RemovableDriveInfo]:
    """List mounted removable drives across Windows, macOS, and Linux platforms."""
    try:
        if sys.platform.startswith("win"):
            return _list_removable_drives_windows()
        if sys.platform == "darwin":
            return _list_removable_drives_darwin()
        if sys.platform.startswith("linux"):
            return _list_removable_drives_linux()
        return []
    except Exception:
        return []


def validate_field_kit_target_directory(
    target_path: Union[str, Path],
    required_free_bytes: int = 250 * 1024 * 1024,
) -> Tuple[bool, str]:
    """Validate that target directory exists or can be created and has sufficient free space."""
    try:
        p = Path(target_path)
        if p.exists():
            if not p.is_dir():
                return False, f"Target path '{target_path}' is an existing file, not a directory"
        else:
            p.mkdir(parents=True, exist_ok=True)

        usage = shutil.disk_usage(p)
        if usage.free < required_free_bytes:
            return (
                False,
                f"Insufficient disk space: {usage.free} bytes available, {required_free_bytes} bytes required",
            )
        return True, ""
    except Exception as exc:
        return False, f"Directory validation failed: {exc}"
