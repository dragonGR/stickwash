from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Partition:
    path: str
    fstype: str = ""
    label: str = ""
    size: str = "?"
    mountpoints: list[str] = field(default_factory=list)


@dataclass
class BlockDevice:
    path: str
    size: str = "?"
    model: str = ""
    serial: str = ""
    rm: bool = False
    tran: str = ""
    dev_type: str = "disk"
    partitions: list[Partition] = field(default_factory=list)

    @property
    def short_serial(self) -> str:
        if not self.serial:
            return ""
        if len(self.serial) > 20:
            return f"{self.serial[:8]}...{self.serial[-8:]}"
        return self.serial

    @property
    def display_title(self) -> str:
        parts = [self.path, f"({self.size})"]
        if self.model:
            parts.append(self.model)
        if self.short_serial:
            parts.append(f"[{self.short_serial}]")
        return "  ".join(parts)


SYSTEM_MOUNTS = {"/", "/boot", "/home", "/var", "/usr", "/etc", "[SWAP]"}


def exec_command(args: list[str], timeout: float = 30.0) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return 127, "", f"Command not found: {args[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"Command timed out after {timeout}s: {' '.join(args)}"


def _parse_partitions(children: list[dict[str, Any]]) -> list[Partition]:
    partitions: list[Partition] = []
    for item in children:
        item_type = str(item.get("type", ""))
        path = str(item.get("path", ""))

        if item_type == "part":
            mounts = item.get("mountpoints") or []
            clean_mounts = [m for m in mounts if m]
            partitions.append(
                Partition(
                    path=path,
                    fstype=str(item.get("fstype") or ""),
                    label=str(item.get("label") or ""),
                    size=str(item.get("size") or "?"),
                    mountpoints=clean_mounts,
                )
            )

        sub_children = item.get("children")
        if isinstance(sub_children, list):
            partitions.extend(_parse_partitions(sub_children))

    return partitions


def discover_drives(removable_only: bool = True, target_device: str | None = None) -> list[BlockDevice]:
    cmd = [
        "lsblk",
        "--json",
        "-o",
        "PATH,RM,TRAN,SIZE,MODEL,SERIAL,TYPE,FSTYPE,LABEL,MOUNTPOINTS",
    ]
    if target_device:
        cmd.append(target_device)

    rc, stdout, _ = exec_command(cmd)
    if rc != 0 or not stdout.strip():
        return []

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return []

    devices: list[BlockDevice] = []
    raw_devices = data.get("blockdevices", [])

    disk_items = [d for d in raw_devices if str(d.get("type", "")) == "disk"]
    flat_parts: list[Partition] = []

    for dev in raw_devices:
        if str(dev.get("type", "")) == "part":
            path = str(dev.get("path", ""))
            mounts = dev.get("mountpoints") or []
            clean_mounts = [m for m in mounts if m]
            flat_parts.append(
                Partition(
                    path=path,
                    fstype=str(dev.get("fstype") or ""),
                    label=str(dev.get("label") or ""),
                    size=str(dev.get("size") or "?"),
                    mountpoints=clean_mounts,
                )
            )

    for dev in disk_items:
        path = str(dev.get("path", ""))
        if not path:
            continue

        rm = bool(dev.get("rm", False))
        tran = str(dev.get("tran") or "")

        if removable_only and not (rm or tran.lower() == "usb"):
            continue

        children = dev.get("children") or []
        partitions = _parse_partitions(children)

        norm_disk_path = os.path.realpath(path)
        for fp in flat_parts:
            norm_part_path = os.path.realpath(fp.path)
            if norm_part_path.startswith(norm_disk_path) and not any(p.path == fp.path for p in partitions):
                partitions.append(fp)

        devices.append(
            BlockDevice(
                path=path,
                size=str(dev.get("size") or "?"),
                model=str(dev.get("model") or "").strip(),
                serial=str(dev.get("serial") or "").strip(),
                rm=rm,
                tran=tran,
                dev_type="disk",
                partitions=partitions,
            )
        )

    return devices


def get_device_by_path(device_path: str) -> BlockDevice | None:
    norm_path = os.path.realpath(device_path)
    all_drives = discover_drives(removable_only=False, target_device=device_path)
    for dev in all_drives:
        if os.path.realpath(dev.path) == norm_path:
            return dev

    fallback_drives = discover_drives(removable_only=False)
    for dev in fallback_drives:
        if os.path.realpath(dev.path) == norm_path:
            return dev

    return None


def get_active_mounts() -> dict[str, str]:
    cmd = ["findmnt", "--json", "-o", "TARGET,SOURCE"]
    rc, stdout, _ = exec_command(cmd)
    if rc != 0 or not stdout.strip():
        return {}

    mount_map: dict[str, str] = {}

    def _recurse_mounts(fs_list: list[dict[str, Any]]) -> None:
        for fs in fs_list:
            target = str(fs.get("target") or "")
            source = str(fs.get("source") or "")
            if target and source:
                mount_map[target] = source
            children = fs.get("children")
            if isinstance(children, list):
                _recurse_mounts(children)

    try:
        data = json.loads(stdout)
        filesystems = data.get("filesystems", [])
        _recurse_mounts(filesystems)
    except json.JSONDecodeError:
        pass

    return mount_map


def is_system_device(device_path: str) -> tuple[bool, str]:
    norm_target = os.path.realpath(device_path)
    mount_map = get_active_mounts()

    for mountpoint, source in mount_map.items():
        norm_source = os.path.realpath(source)
        if norm_source.startswith(norm_target):
            if mountpoint in SYSTEM_MOUNTS or mountpoint == "/":
                return True, f"Device backs critical mount point: {mountpoint}"

    device = get_device_by_path(device_path)
    if device:
        for part in device.partitions:
            for mp in part.mountpoints:
                if mp in SYSTEM_MOUNTS or mp == "/":
                    return True, f"Partition {part.path} is mounted at {mp}"

    return False, ""
