import os
import shutil
import struct
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
    fat32_tool = "mkfs.fat" if have_tool("mkfs.fat") else ("mkfs.vfat" if have_tool("mkfs.vfat") else "native")
    exfat_tool = "mkfs.exfat" if have_tool("mkfs.exfat") else "native"

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
            mkfs_cmd=exfat_tool,
            label_cmd="exfatlabel" if have_tool("exfatlabel") else "native",
            label_limit=15,
            package="exfatprogs",
            available=True,
        ),
        FilesystemProfile(
            name="fat32",
            note="Universal compatibility, maximum 4 GB per file",
            mkfs_cmd=fat32_tool,
            label_cmd="fatlabel" if have_tool("fatlabel") else "native",
            label_limit=11,
            package="dosfstools",
            available=True,
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


def get_device_size_bytes(device_path: str) -> int:
    try:
        import fcntl

        BLKGETSIZE64 = 0x80081272
        with open(device_path, "rb") as f:
            buf = fcntl.ioctl(f.fileno(), BLKGETSIZE64, b"\x00" * 8)
            size = struct.unpack("<Q", buf)[0]
            if size > 0:
                return size
    except Exception:
        pass

    try:
        with open(device_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            if size > 0:
                return size
    except Exception:
        pass

    return os.path.getsize(device_path)


def format_fat32_native(device_path: str, label: str = "") -> None:
    file_size = get_device_size_bytes(device_path)
    total_sectors = file_size // 512
    if total_sectors < 65536:
        sectors_per_cluster = 1
    elif total_sectors < 16777216:
        sectors_per_cluster = 8
    else:
        sectors_per_cluster = 32

    reserved_sectors = 32
    num_fats = 2
    root_cluster = 2

    tmp_clusters = (total_sectors - reserved_sectors) // sectors_per_cluster
    fat_size_sectors = ((tmp_clusters * 4) + 511) // 512
    total_clusters = (total_sectors - reserved_sectors - (num_fats * fat_size_sectors)) // sectors_per_cluster
    fat_size_sectors = (((total_clusters + 2) * 4) + 511) // 512

    if total_clusters <= 0:
        raise RuntimeError(f"Device {device_path} size ({file_size} B) is too small for FAT32.")

    clean_label = (label.strip().upper() or "NO NAME").ljust(11)[:11]
    vol_id = int(time.time()) & 0xFFFFFFFF

    boot = bytearray(512)
    boot[0:3] = b"\xeb\x58\x90"
    boot[3:11] = b"MSWIN4.1"
    struct.pack_into("<H", boot, 0x0B, 512)
    boot[0x0D] = sectors_per_cluster
    struct.pack_into("<H", boot, 0x0E, reserved_sectors)
    boot[0x10] = num_fats
    boot[0x15] = 0xF8
    struct.pack_into("<H", boot, 0x18, 63)
    struct.pack_into("<H", boot, 0x1A, 255)
    struct.pack_into("<I", boot, 0x1C, 2048)
    struct.pack_into("<I", boot, 0x20, total_sectors)
    struct.pack_into("<I", boot, 0x24, fat_size_sectors)
    struct.pack_into("<I", boot, 0x2C, root_cluster)
    struct.pack_into("<H", boot, 0x30, 1)
    struct.pack_into("<H", boot, 0x32, 6)
    boot[0x40] = 0x80
    boot[0x42] = 0x29
    struct.pack_into("<I", boot, 0x43, vol_id)
    boot[0x47:0x52] = clean_label.encode("ascii")
    boot[0x52:0x5A] = b"FAT32   "
    boot[0x1FE:0x200] = b"\x55\xaa"

    fsinfo = bytearray(512)
    fsinfo[0:4] = b"\x52\x52\x61\x41"
    fsinfo[0x1E4:0x1E8] = b"\x72\x72\x41\x61"
    struct.pack_into("<I", fsinfo, 0x1E8, total_clusters - 1)
    struct.pack_into("<I", fsinfo, 0x1EC, 3)
    fsinfo[0x1FC:0x200] = b"\x00\x00\x55\xaa"

    fat_sec0 = bytearray(512)
    struct.pack_into("<I", fat_sec0, 0, 0x0FFFFFF8)
    struct.pack_into("<I", fat_sec0, 4, 0xFFFFFFFF)
    struct.pack_into("<I", fat_sec0, 8, 0x0FFFFFFF)

    root_dir = bytearray(512 * sectors_per_cluster)
    if clean_label != "NO NAME    ":
        root_dir[0:11] = clean_label.encode("ascii")
        root_dir[0x0B] = 0x08

    with open(device_path, "r+b") as f:
        f.seek(0)
        f.write(boot)
        f.seek(1 * 512)
        f.write(fsinfo)
        f.seek(6 * 512)
        f.write(boot)

        fat1_offset = reserved_sectors * 512
        f.seek(fat1_offset)
        f.write(fat_sec0)

        fat2_offset = (reserved_sectors + fat_size_sectors) * 512
        f.seek(fat2_offset)
        f.write(fat_sec0)

        cluster_heap_offset = (reserved_sectors + (num_fats * fat_size_sectors)) * 512
        f.seek(cluster_heap_offset)
        f.write(root_dir)
        f.flush()


def format_exfat_native(device_path: str, label: str = "") -> None:
    file_size = get_device_size_bytes(device_path)
    total_sectors = file_size // 512

    sector_bits = 9
    spc_bits = 6
    spc = 1 << spc_bits
    fat_offset = 24
    num_fats = 1

    total_clusters = (total_sectors - fat_offset) // spc
    fat_size_sectors = (((total_clusters + 2) * 4) + 511) // 512

    heap_offset = fat_offset + fat_size_sectors
    if heap_offset % spc != 0:
        heap_offset += (spc - (heap_offset % spc))

    total_clusters = (total_sectors - heap_offset) // spc
    if total_clusters <= 0:
        raise RuntimeError(f"Device {device_path} size ({file_size} B) is too small for exFAT.")

    vol_id = int(time.time()) & 0xFFFFFFFF
    clean_label = label.strip() or "EXFATUSB"
    label_u16 = clean_label.encode("utf-16le")[:22]

    boot = bytearray(512)
    boot[0:3] = b"\xeb\x76\x90"
    boot[3:11] = b"EXFAT   "
    struct.pack_into("<Q", boot, 64, 0)
    struct.pack_into("<Q", boot, 72, total_sectors)
    struct.pack_into("<I", boot, 80, fat_offset)
    struct.pack_into("<I", boot, 84, fat_size_sectors)
    struct.pack_into("<I", boot, 88, heap_offset)
    struct.pack_into("<I", boot, 92, total_clusters)
    struct.pack_into("<I", boot, 96, 4)
    struct.pack_into("<I", boot, 100, vol_id)
    struct.pack_into("<H", boot, 104, 0x0100)
    struct.pack_into("<H", boot, 106, 0x0000)
    boot[108] = sector_bits
    boot[109] = spc_bits
    boot[110] = num_fats
    boot[111] = 0x80
    boot[112] = 0
    boot[510:512] = b"\x55\xaa"

    boot_region = bytearray(11 * 512)
    boot_region[0:512] = boot
    for i in range(1, 11):
        boot_region[i * 512 + 510:i * 512 + 512] = b"\x55\xaa"

    chk = 0
    for i, b in enumerate(boot_region):
        if i in (106, 107, 112):
            continue
        chk = (((chk & 1) << 31) | (chk >> 1)) + b
        chk &= 0xFFFFFFFF

    checksum_sector = bytearray(512)
    for i in range(0, 512, 4):
        struct.pack_into("<I", checksum_sector, i, chk)

    fat_sec0 = bytearray(512)
    struct.pack_into("<I", fat_sec0, 0, 0xFFFFFFF8)
    struct.pack_into("<I", fat_sec0, 4, 0xFFFFFFFF)
    struct.pack_into("<I", fat_sec0, 8, 0xFFFFFFFF)
    struct.pack_into("<I", fat_sec0, 12, 0xFFFFFFFF)
    struct.pack_into("<I", fat_sec0, 16, 0xFFFFFFFF)

    bitmap_size = (total_clusters + 7) // 8
    bitmap_data = bytearray(spc * 512)
    bitmap_data[0] = 0x07

    upcase_data = bytearray(spc * 512)
    for i in range(128):
        struct.pack_into("<H", upcase_data, i * 2, ord(chr(i).upper()))
    upcase_chk = 0
    for b in upcase_data[:256]:
        upcase_chk = (((upcase_chk & 1) << 31) | (upcase_chk >> 1)) + b
        upcase_chk &= 0xFFFFFFFF

    root_data = bytearray(spc * 512)
    root_data[0] = 0x83
    root_data[1] = len(label_u16) // 2
    root_data[2:2 + len(label_u16)] = label_u16

    root_data[32] = 0x81
    root_data[33] = 0x00
    struct.pack_into("<I", root_data, 32 + 20, 2)
    struct.pack_into("<Q", root_data, 32 + 24, bitmap_size)

    root_data[64] = 0x82
    struct.pack_into("<I", root_data, 64 + 4, upcase_chk)
    struct.pack_into("<I", root_data, 64 + 20, 3)
    struct.pack_into("<Q", root_data, 64 + 24, 256)

    with open(device_path, "r+b") as f:
        f.seek(0)
        f.write(boot_region)
        f.write(checksum_sector)
        f.seek(12 * 512)
        f.write(boot_region)
        f.write(checksum_sector)

        f.seek(fat_offset * 512)
        f.write(fat_sec0)

        f.seek(heap_offset * 512)
        f.write(bitmap_data)

        f.seek((heap_offset + spc) * 512)
        f.write(upcase_data)

        f.seek((heap_offset + (2 * spc)) * 512)
        f.write(root_data)
        f.flush()


def relabel_fat32_native(partition_path: str, new_label: str) -> None:
    clean_label = (new_label.strip().upper() or "NO NAME").ljust(11)[:11]
    with open(partition_path, "r+b") as f:
        f.seek(0x47)
        f.write(clean_label.encode("ascii"))
        f.seek(6 * 512 + 0x47)
        f.write(clean_label.encode("ascii"))
        f.flush()


def relabel_exfat_native(partition_path: str, new_label: str) -> None:
    clean_label = new_label.strip() or "EXFATUSB"
    label_u16 = clean_label.encode("utf-16le")[:22]

    with open(partition_path, "r+b") as f:
        f.seek(88)
        heap_offset = struct.unpack("<I", f.read(4))[0]
        f.seek(96)
        root_cluster = struct.unpack("<I", f.read(4))[0]
        f.seek(109)
        spc_bits = f.read(1)[0]
        spc = 1 << spc_bits

        root_offset = (heap_offset + ((root_cluster - 2) * spc)) * 512
        f.seek(root_offset)
        root_data = bytearray(f.read(512))

        if root_data[0] == 0x83:
            root_data[1] = len(label_u16) // 2
            root_data[2:2 + len(label_u16)] = label_u16.ljust(22, b"\x00")
            f.seek(root_offset)
            f.write(root_data[:32])
            f.flush()


def format_partition(
    fs_profile: FilesystemProfile,
    partition_path: str,
    label: str = "",
    dry_run: bool = False,
) -> None:
    if fs_profile.name == "ext4":
        cmd = ["mkfs.ext4", "-F", "-q"]
        if label:
            cmd.extend(["-L", label])
        cmd.append(partition_path)

        if dry_run:
            say(theme.muted(f"[DRY-RUN] Would run: {' '.join(cmd)}"))
            say(theme.muted(f"[DRY-RUN] Would run: sync {partition_path}"))
            return

        rc, _, err = exec_command(cmd, timeout=300.0)
        if rc != 0:
            raise RuntimeError(f"Formatting failed (mkfs.ext4): {err}")
    elif fs_profile.name == "exfat":
        if have_tool("mkfs.exfat"):
            cmd = ["mkfs.exfat", "-q"]
            if label:
                cmd.extend(["-L", label])
            cmd.append(partition_path)

            if dry_run:
                say(theme.muted(f"[DRY-RUN] Would run: {' '.join(cmd)}"))
                say(theme.muted(f"[DRY-RUN] Would run: sync {partition_path}"))
                return

            rc, _, err = exec_command(cmd, timeout=300.0)
            if rc != 0:
                raise RuntimeError(f"Formatting failed (mkfs.exfat): {err}")
        else:
            if dry_run:
                say(theme.muted(f"[DRY-RUN] Would run native Python exFAT formatter on {partition_path} (label: '{label}')"))
                return
            format_exfat_native(partition_path, label=label)
    elif fs_profile.name in ("fat32", "vfat"):
        mkfs_bin = "mkfs.fat" if have_tool("mkfs.fat") else ("mkfs.vfat" if have_tool("mkfs.vfat") else "")
        if mkfs_bin:
            cmd = [mkfs_bin, "-F", "32"]
            if label:
                cmd.extend(["-n", label])
            cmd.append(partition_path)

            if dry_run:
                say(theme.muted(f"[DRY-RUN] Would run: {' '.join(cmd)}"))
                say(theme.muted(f"[DRY-RUN] Would run: sync {partition_path}"))
                return

            rc, _, err = exec_command(cmd, timeout=300.0)
            if rc != 0:
                raise RuntimeError(f"Formatting failed ({mkfs_bin}): {err}")
        else:
            if dry_run:
                say(theme.muted(f"[DRY-RUN] Would run native Python FAT32 formatter on {partition_path} (label: '{label}')"))
                return
            format_fat32_native(partition_path, label=label)
    else:
        raise ValueError(f"Unsupported filesystem: {fs_profile.name}")

    if not dry_run:
        exec_command(["sync", partition_path])


def relabel_partition(
    fstype: str,
    partition_path: str,
    new_label: str,
    dry_run: bool = False,
) -> None:
    norm_fs = fstype.lower()
    if norm_fs in ("ext2", "ext3", "ext4"):
        if not have_tool("e2label"):
            raise RuntimeError(f"Relabel tool 'e2label' is missing. Install with: {get_package_installer('e2fsprogs')}")
        cmd = ["e2label", partition_path, new_label]
        if dry_run:
            say(theme.muted(f"[DRY-RUN] Would run: {' '.join(cmd)}"))
            return
        unmount_partition(partition_path, dry_run=dry_run)
        rc, _, err = exec_command(cmd)
        if rc != 0:
            raise RuntimeError(f"Relabeling failed (e2label): {err}")
    elif norm_fs == "exfat":
        if dry_run:
            say(theme.muted(f"[DRY-RUN] Would relabel exFAT partition {partition_path} to '{new_label}'"))
            return
        unmount_partition(partition_path, dry_run=dry_run)
        if have_tool("exfatlabel"):
            exec_command(["exfatlabel", partition_path, new_label])
        else:
            relabel_exfat_native(partition_path, new_label)
    elif norm_fs in ("fat", "fat16", "fat32", "vfat", "msdos"):
        if dry_run:
            say(theme.muted(f"[DRY-RUN] Would relabel FAT32 partition {partition_path} to '{new_label}'"))
            return
        unmount_partition(partition_path, dry_run=dry_run)
        if have_tool("fatlabel"):
            exec_command(["fatlabel", partition_path, new_label])
        else:
            relabel_fat32_native(partition_path, new_label)
    else:
        raise ValueError(f"Relabeling is not supported for filesystem type: {fstype}")

    if not dry_run:
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
