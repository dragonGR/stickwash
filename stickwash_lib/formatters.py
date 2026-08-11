from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Sequence

from stickwash_lib.disk import BlockDevice, Partition, exec_command, get_device_by_path
from stickwash_lib.ui import Spinner, say, say_err, say_ok, say_warn, theme


@dataclass
class FilesystemProfile:
    name: str
    note: str
    mkfs_cmd: str
    label_cmd: str
    label_limit: int
    package: str
    available: bool


def have_tool(tool_name: str) -> bool:
    return shutil.which(tool_name) is not None


def get_package_installer(package_name: str) -> str:
    if have_tool("pacman"):
        return f"sudo pacman -S {package_name}"
    if have_tool("apt-get") or have_tool("apt"):
        return f"sudo apt install {package_name}"
    if have_tool("dnf"):
        return f"sudo dnf install {package_name}"
    if have_tool("zypper"):
        return f"sudo zypper install {package_name}"
    return f"Install package: {package_name}"


def get_filesystem_profiles() -> list[FilesystemProfile]:
    ext4_avail = have_tool("mkfs.ext4")
    exfat_avail = have_tool("mkfs.exfat")
    fat32_tool = "mkfs.fat" if have_tool("mkfs.fat") else ("mkfs.vfat" if have_tool("mkfs.vfat") else "")
    fat32_avail = bool(fat32_tool)

    return [
        FilesystemProfile(
            name="ext4",
            note="Linux default filesystem",
            mkfs_cmd="mkfs.ext4",
            label_cmd="e2label",
            label_limit=16,
            package="e2fsprogs",
            available=ext4_avail,
        ),
        FilesystemProfile(
            name="exfat",
            note="Optimal for cross-platform Linux and Windows compatibility",
            mkfs_cmd="mkfs.exfat",
            label_cmd="exfatlabel",
            label_limit=15,
            package="exfatprogs",
            available=exfat_avail,
        ),
        FilesystemProfile(
            name="fat32",
            note="Universal compatibility, maximum 4 GB per file",
            mkfs_cmd=fat32_tool or "mkfs.fat",
            label_cmd="fatlabel",
            label_limit=11,
            package="dosfstools",
            available=fat32_avail,
        ),
    ]


def get_profile_by_name(fs_name: str) -> FilesystemProfile | None:
    norm = fs_name.lower()
    for prof in get_filesystem_profiles():
        if prof.name.lower() == norm:
            return prof
    return None


def unmount_partition(part_path: str, dry_run: bool = False) -> None:
    if dry_run:
        say(theme.muted(f"[DRY-RUN] Would unmount and swapoff {part_path}"))
        return

    exec_command(["swapoff", part_path])

    rc, stdout, _ = exec_command(["findmnt", "-rn", "-S", part_path])
    if rc != 0 or not stdout.strip():
        return

    rc, _, stderr = exec_command(["umount", part_path])
    if rc != 0:
        say_warn(f"{part_path} is busy. Attempting lazy unmount...")
        rc2, _, err2 = exec_command(["umount", "-l", part_path])
        if rc2 != 0:
            raise RuntimeError(f"Failed to unmount {part_path}: {err2}")


def unmount_device_partitions(device_path: str, dry_run: bool = False) -> None:
    if not dry_run:
        exec_command(["swapoff", device_path])
        rc, stdout, _ = exec_command(["lsblk", "-ln", "-o", "PATH", device_path])
        if rc == 0 and stdout.strip():
            for node in stdout.strip().splitlines():
                node = node.strip()
                if node and node != device_path:
                    unmount_partition(node, dry_run=dry_run)
    else:
        device = get_device_by_path(device_path)
        if device:
            for part in device.partitions:
                unmount_partition(part.path, dry_run=dry_run)


def wipe_signatures(device_path: str, dry_run: bool = False) -> None:
    device = get_device_by_path(device_path)
    if device:
        for part in device.partitions:
            if dry_run:
                say(theme.muted(f"[DRY-RUN] Would run: wipefs -af {part.path}"))
            else:
                exec_command(["wipefs", "-af", part.path])

    if dry_run:
        say(theme.muted(f"[DRY-RUN] Would run: wipefs -af {device_path}"))
        say(theme.muted(f"[DRY-RUN] Would zero out initial MBR/GPT header on {device_path}"))
    else:
        exec_command(["wipefs", "-af", device_path])
        exec_command(["dd", "if=/dev/zero", f"of={device_path}", "bs=1M", "count=1", "status=none", "conv=fsync"])
        exec_command(["partprobe", device_path])
        exec_command(["udevadm", "settle"])
        time.sleep(0.5)


def create_partition_table(device_path: str, dry_run: bool = False) -> None:
    if dry_run:
        say(theme.muted(f"[DRY-RUN] Would run: sfdisk --wipe always --wipe-partitions always --lock=yes {device_path}"))
        return

    unmount_device_partitions(device_path, dry_run=False)
    exec_command(["partprobe", device_path])
    exec_command(["udevadm", "settle"])
    time.sleep(0.5)

    if have_tool("sfdisk"):
        sfdisk_input = "label: gpt\n,\n"
        for _ in range(3):
            try:
                proc = subprocess.run(
                    ["sfdisk", "--wipe", "always", "--wipe-partitions", "always", "--lock=yes", device_path],
                    input=sfdisk_input,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=30.0,
                    check=False,
                )
                if proc.returncode == 0:
                    exec_command(["partprobe", device_path])
                    exec_command(["udevadm", "settle"])
                    return
            except Exception:
                pass
            time.sleep(0.5)

    flock_cmd = ["flock", "-x", "-w", "10", device_path, "parted", "-s", device_path, "mklabel", "gpt", "mkpart", "primary", "1MiB", "100%"]
    rc1, _, err1 = exec_command(flock_cmd)
    if rc1 != 0:
        rc1, _, err1 = exec_command(["parted", "-s", "-a", "optimal", device_path, "mklabel", "gpt", "mkpart", "primary", "1MiB", "100%"])

    if rc1 != 0:
        raise RuntimeError(f"Failed to create GPT label on {device_path}: {err1}")

    exec_command(["partprobe", device_path])
    exec_command(["udevadm", "settle"])


def settle_udev(device_path: str, dry_run: bool = False) -> None:
    if dry_run:
        say(theme.muted(f"[DRY-RUN] Would run: partprobe {device_path} && udevadm settle"))
        return

    exec_command(["partprobe", device_path])
    exec_command(["udevadm", "settle"])


def resolve_created_partition(device_path: str, dry_run: bool = False) -> str:
    expected_part = f"{device_path}p1" if ("nvme" in device_path or "mmcblk" in device_path) else f"{device_path}1"

    if dry_run:
        return expected_part

    for _ in range(12):
        settle_udev(device_path)
        time.sleep(0.5)

        if os.path.exists(expected_part):
            return expected_part

        dev = get_device_by_path(device_path)
        if dev and dev.partitions:
            return dev.partitions[0].path

    raise RuntimeError(f"New partition ({expected_part}) did not appear on {device_path} after formatting partition table.")


def format_partition(
    fs_profile: FilesystemProfile,
    partition_path: str,
    label: str = "",
    dry_run: bool = False,
) -> None:
    cmd = [fs_profile.mkfs_cmd]

    if fs_profile.name == "ext4":
        cmd.extend(["-F", "-q"])
        if label:
            cmd.extend(["-L", label])
        cmd.append(partition_path)
    elif fs_profile.name == "exfat":
        cmd.extend(["-q"])
        if label:
            cmd.extend(["-L", label])
        cmd.append(partition_path)
    elif fs_profile.name in ("fat32", "vfat"):
        cmd.extend(["-F", "32"])
        if label:
            cmd.extend(["-n", label])
        cmd.append(partition_path)
    else:
        raise ValueError(f"Unsupported filesystem: {fs_profile.name}")

    if dry_run:
        say(theme.muted(f"[DRY-RUN] Would run: {' '.join(cmd)}"))
        say(theme.muted(f"[DRY-RUN] Would run: sync {partition_path}"))
        return

    rc, _, err = exec_command(cmd, timeout=300.0)
    if rc != 0:
        raise RuntimeError(f"Formatting failed ({fs_profile.mkfs_cmd}): {err}")

    exec_command(["sync", partition_path])


def relabel_partition(
    fstype: str,
    partition_path: str,
    new_label: str,
    dry_run: bool = False,
) -> None:
    norm_fs = fstype.lower()
    tool = ""
    if norm_fs in ("ext2", "ext3", "ext4"):
        tool = "e2label"
    elif norm_fs == "exfat":
        tool = "exfatlabel"
    elif norm_fs in ("fat", "fat16", "fat32", "vfat", "msdos"):
        tool = "fatlabel"
    else:
        raise ValueError(f"Relabeling is not supported for filesystem type: {fstype}")

    if not have_tool(tool):
        pkg = "e2fsprogs" if tool == "e2label" else ("exfatprogs" if tool == "exfatlabel" else "dosfstools")
        raise RuntimeError(f"Relabel tool '{tool}' is missing. Install with: {get_package_installer(pkg)}")

    cmd = [tool, partition_path, new_label]
    if dry_run:
        say(theme.muted(f"[DRY-RUN] Would run: {' '.join(cmd)}"))
        return

    unmount_partition(partition_path, dry_run=dry_run)
    rc, _, err = exec_command(cmd)
    if rc != 0:
        raise RuntimeError(f"Relabeling failed ({tool}): {err}")
    exec_command(["udevadm", "settle"])


def mount_partition_for_user(
    partition_path: str,
    fs_name: str,
    label: str = "",
    dry_run: bool = False,
) -> str:
    sudo_user = os.environ.get("SUDO_USER", "")
    if sudo_user and sudo_user != "root":
        base_dir = f"/run/media/{sudo_user}"
    else:
        base_dir = "/mnt"

    leaf = label.strip() or os.path.basename(partition_path)
    clean_leaf = "".join(c if c.isalnum() or c in "-_" else "_" for c in leaf)
    mountpoint = os.path.join(base_dir, clean_leaf)

    if dry_run:
        say(theme.muted(f"[DRY-RUN] Would create directory {mountpoint} and mount {partition_path}"))
        return mountpoint

    os.makedirs(mountpoint, exist_ok=True)

    uid_gid_opts = []
    if sudo_user and sudo_user != "root":
        import pwd
        try:
            user_info = pwd.getpwnam(sudo_user)
            uid, gid = user_info.pw_uid, user_info.pw_gid
            uid_gid_opts = ["-o", f"uid={uid},gid={gid},umask=022"]
        except KeyError:
            pass

    cmd = ["mount"]
    if fs_name.lower() in ("exfat", "fat32") and uid_gid_opts:
        cmd.extend(uid_gid_opts)
    cmd.extend([partition_path, mountpoint])

    rc, _, err = exec_command(cmd)
    if rc != 0:
        raise RuntimeError(f"Failed to mount {partition_path} at {mountpoint}: {err}")

    if fs_name.lower() == "ext4" and sudo_user and sudo_user != "root":
        try:
            import pwd
            user_info = pwd.getpwnam(sudo_user)
            os.chown(mountpoint, user_info.pw_uid, user_info.pw_gid)
        except Exception as e:
            say_warn(f"Could not change ownership of {mountpoint}: {e}")

    return mountpoint
