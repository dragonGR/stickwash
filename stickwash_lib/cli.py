from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Sequence

from stickwash_lib import __version__
from stickwash_lib.disk import (
    BlockDevice,
    Partition,
    discover_drives,
    get_device_by_path,
    is_system_device,
)
from stickwash_lib.formatters import (
    FilesystemProfile,
    create_partition_table,
    format_partition,
    get_filesystem_profiles,
    get_package_installer,
    get_profile_by_name,
    mount_partition_for_user,
    relabel_partition,
    resolve_created_partition,
    settle_udev,
    unmount_device_partitions,
    wipe_signatures,
)
from stickwash_lib.ui import (
    Spinner,
    render_card,
    render_menu,
    render_table,
    say,
    say_err,
    say_ok,
    say_warn,
    set_color_enabled,
    theme,
)


def ensure_root(action_name: str = "This operation") -> None:
    if os.geteuid() != 0:
        say_err(f"{action_name} requires root privileges. Run with sudo.")
        sys.exit(1)


def build_layout_table_data(device: BlockDevice) -> tuple[list[str], list[list[str]]]:
    headers = ["PATH", "SIZE", "FSTYPE", "LABEL", "MOUNTPOINTS"]
    rows: list[list[str]] = [
        [device.path, device.size, "", "", ""]
    ]
    for part in device.partitions:
        mounts_str = ", ".join(part.mountpoints) if part.mountpoints else ""
        rows.append([part.path, part.size, part.fstype or "unknown", part.label or "-", mounts_str])
    return headers, rows


def cmd_list(args: argparse.Namespace) -> None:
    drives = discover_drives(removable_only=not args.all)

    if args.json:
        out_data = []
        for d in drives:
            out_data.append(
                {
                    "path": d.path,
                    "size": d.size,
                    "model": d.model,
                    "serial": d.serial,
                    "removable": d.rm,
                    "transport": d.tran,
                    "partitions": [
                        {
                            "path": p.path,
                            "size": p.size,
                            "fstype": p.fstype,
                            "label": p.label,
                            "mountpoints": p.mountpoints,
                        }
                        for p in d.partitions
                    ],
                }
            )
        print(json.dumps(out_data, indent=2))
        return

    if not drives:
        say_warn("No removable USB drives found.")
        return

    headers = ["#", "DEVICE", "SIZE", "MODEL", "SERIAL", "PARTS"]
    rows = []
    for idx, d in enumerate(drives, 1):
        parts_summary = f"{len(d.partitions)} partition(s)" if d.partitions else "Empty"
        rows.append([str(idx), d.path, d.size, d.model or "-", d.short_serial or "-", parts_summary])

    render_table(headers, rows, title="Removable USB Drives")


def cmd_inspect(args: argparse.Namespace) -> None:
    device = get_device_by_path(args.device)
    if not device:
        say_err(f"Device not found or invalid block device: {args.device}")
        sys.exit(1)

    if args.json:
        out_data = {
            "path": device.path,
            "size": device.size,
            "model": device.model,
            "serial": device.serial,
            "removable": device.rm,
            "transport": device.tran,
            "partitions": [
                {
                    "path": p.path,
                    "size": p.size,
                    "fstype": p.fstype,
                    "label": p.label,
                    "mountpoints": p.mountpoints,
                }
                for p in device.partitions
            ],
        }
        print(json.dumps(out_data, indent=2))
        return

    headers, rows = build_layout_table_data(device)
    render_table(headers, rows, title=f"Partition Layout: {device.display_title}")


def execute_wipe(
    device_path: str,
    fs_name: str,
    label: str,
    dry_run: bool = False,
    mount: bool = False,
) -> str:
    prof = get_profile_by_name(fs_name)
    if not prof:
        raise ValueError(f"Unknown filesystem: {fs_name}")
    if not prof.available and not dry_run:
        pkg_cmd = get_package_installer(prof.package)
        raise RuntimeError(f"Formatter '{prof.mkfs_cmd}' is missing. Install with: {pkg_cmd}")

    if label and len(label) > prof.label_limit:
        raise ValueError(f"Label exceeds limit of {prof.label_limit} chars for {prof.name}")

    if not dry_run:
        with Spinner(f"Unmounting active partitions on {device_path}"):
            unmount_device_partitions(device_path, dry_run=False)

        with Spinner(f"Wiping signatures on {device_path}"):
            wipe_signatures(device_path, dry_run=False)

        with Spinner(f"Creating GPT partition table on {device_path}"):
            create_partition_table(device_path, dry_run=False)

        with Spinner(f"Settling udev and discovering new partition on {device_path}"):
            part_path = resolve_created_partition(device_path, dry_run=False)

        with Spinner(f"Formatting {part_path} as {prof.name} (label: '{label or 'none'}')"):
            format_partition(prof, part_path, label=label, dry_run=False)
            settle_udev(device_path, dry_run=False)
    else:
        unmount_device_partitions(device_path, dry_run=True)
        wipe_signatures(device_path, dry_run=True)
        create_partition_table(device_path, dry_run=True)
        part_path = resolve_created_partition(device_path, dry_run=True)
        format_partition(prof, part_path, label=label, dry_run=True)

    if mount and not dry_run:
        with Spinner(f"Mounting fresh partition {part_path}"):
            mnt = mount_partition_for_user(part_path, prof.name, label=label, dry_run=False)
        say_ok(f"Mounted {part_path} at {mnt}")

    return part_path


def cmd_wipe(args: argparse.Namespace) -> None:
    if not args.dry_run:
        ensure_root("Drive wiping")

    device_path = args.device
    device = get_device_by_path(device_path)
    if not device:
        say_err(f"Device not found: {device_path}")
        sys.exit(1)

    is_sys, sys_reason = is_system_device(device_path)
    if is_sys:
        say_err(f"Refusing to touch system device: {sys_reason}")
        sys.exit(1)

    if not device.rm and device.tran != "usb" and not args.force:
        say_err(f"{device_path} does not report as a removable USB drive. Use --force to override.")
        sys.exit(1)

    if not args.yes and not args.dry_run:
        headers, rows = build_layout_table_data(device)
        render_table(headers, rows, title=f"TARGET DISK LAYOUT: {device_path}")
        say_warn(f"WARNING: Wiping {device_path} will permanently erase all existing partitions!")
        confirm = input(f"Type the full device path ({device_path}) to confirm: ").strip()
        if confirm != device_path:
            say("Wipe cancelled.")
            return

    before_dev = get_device_by_path(device_path)
    part_path = execute_wipe(
        device_path,
        fs_name=args.fs,
        label=args.label or "",
        dry_run=args.dry_run,
        mount=args.mount,
    )

    if not args.dry_run:
        say_ok(f"Successfully formatted {device_path} as {args.fs.upper()}.")
        settle_udev(device_path, dry_run=False)
        time.sleep(0.5)
        after_dev = get_device_by_path(device_path)

        if before_dev and after_dev:
            say("")
            b_headers, b_rows = build_layout_table_data(before_dev)
            render_table(b_headers, b_rows, title="BEFORE")
            say("")
            a_headers, a_rows = build_layout_table_data(after_dev)
            render_table(a_headers, a_rows, title="AFTER")


def cmd_relabel(args: argparse.Namespace) -> None:
    if not args.dry_run:
        ensure_root("Partition relabeling")

    part_path = args.partition
    dev = get_device_by_path(part_path)
    if dev:
        say_err(f"{part_path} is a disk device, not a partition path.")
        sys.exit(1)

    all_drives = discover_drives(removable_only=False)
    target_part: Partition | None = None
    target_dev: BlockDevice | None = None

    for d in all_drives:
        for p in d.partitions:
            if p.path == part_path or os.path.realpath(p.path) == os.path.realpath(part_path):
                target_part = p
                target_dev = d
                break
        if target_part:
            break

    if not target_part or not target_dev:
        say_err(f"Partition not found: {part_path}")
        sys.exit(1)

    is_sys, sys_reason = is_system_device(target_dev.path)
    if is_sys:
        say_err(f"Refusing to touch system device partition: {sys_reason}")
        sys.exit(1)

    if not target_dev.rm and target_dev.tran != "usb" and not args.force:
        say_err(f"{target_dev.path} is not a removable USB device. Use --force to override.")
        sys.exit(1)

    if not target_part.fstype:
        say_err(f"Cannot relabel {part_path}: unknown filesystem type.")
        sys.exit(1)

    if not args.dry_run:
        with Spinner(f"Relabeling {part_path} ({target_part.fstype}) to '{args.label}'"):
            relabel_partition(target_part.fstype, part_path, args.label, dry_run=False)
        say_ok(f"Partition {part_path} relabeled to '{args.label}'.")
    else:
        relabel_partition(target_part.fstype, part_path, args.label, dry_run=True)


def interactive_wizard() -> None:
    ensure_root("Stickwash wizard")

    say("")
    say(theme.bold(theme.cyan("Stickwash - USB Drive Maintenance Utility")))
    say(theme.muted("Only removable USB drives are shown below."))

    while True:
        drives = discover_drives(removable_only=True)
        if not drives:
            say("")
            say_warn("No removable USB drives detected.")
            ans = input("Press Enter to rescan, or 'q' to quit: ").strip().lower()
            if ans == "q":
                sys.exit(0)
            continue

        say("")
        headers = ["#", "DEVICE", "SIZE", "MODEL", "SERIAL"]
        rows = []
        for idx, d in enumerate(drives, 1):
            rows.append([str(idx), d.path, d.size, d.model or "-", d.short_serial or "-"])

        render_table(headers, rows, title="Detected USB Drives")
        say("")
        say("  r. Rescan drives")
        say("  q. Quit")

        choice = input("\nPick a drive number: ").strip().lower()
        if choice in ("q", "quit"):
            sys.exit(0)
        if choice in ("r", "rescan", ""):
            continue

        if not choice.isdigit() or not (1 <= int(choice) <= len(drives)):
            say_err("Invalid selection. Pick a listed number, 'r', or 'q'.")
            continue

        selected_dev = drives[int(choice) - 1]
        interactive_drive_menu(selected_dev)


def interactive_drive_menu(device: BlockDevice) -> None:
    while True:
        say("")
        render_card("TARGET DRIVE", device.display_title)
        say("")
        render_menu([
            ("1", "Show partition layout", "Inspect partitions, filesystems, and mountpoints"),
            ("2", "Relabel a partition", "Change partition volume label without reformatting"),
            ("3", "Wipe and rebuild drive", "Format drive with ext4, exFAT, or FAT32"),
            ("4", "Back to drive list", "Return to removable USB drive selection"),
        ])

        choice = input("\nWhat now: ").strip()

        if choice == "1":
            headers, rows = build_layout_table_data(device)
            render_table(headers, rows, title=f"Layout for {device.path}")
            if not device.partitions:
                say_warn(f"{device.path} currently contains no partitions.")
        elif choice == "2":
            if not device.partitions:
                say_warn(f"No partitions exist on {device.path}.")
                say(theme.muted("  To create a partition, select option 3 (Wipe and rebuild drive)."))
                continue
            say("\nSelect partition to relabel:")
            for idx, p in enumerate(device.partitions, 1):
                say(f"  [{idx}] {p.path} ({p.size}, {p.fstype or 'unknown'}, label: '{p.label or '-'}')")
            say("  [q] Back")
            p_choice = input("\nPartition: ").strip().lower()
            if p_choice == "q" or not p_choice:
                continue
            if not p_choice.isdigit() or not (1 <= int(p_choice) <= len(device.partitions)):
                say_err("Invalid partition selection.")
                continue

            sel_part = device.partitions[int(p_choice) - 1]
            new_label = input(f"New label for {sel_part.path}: ").strip()
            if not new_label:
                say("Label unchanged.")
                continue

            try:
                relabel_partition(sel_part.fstype, sel_part.path, new_label)
                say_ok(f"Relabeled {sel_part.path} to '{new_label}'.")
            except Exception as e:
                say_err(str(e))
        elif choice == "3":
            say("")
            render_card("SELECT TARGET FILESYSTEM", f"Choose a filesystem format for {device.display_title}")
            say("")

            profiles = get_filesystem_profiles()
            for idx, prof in enumerate(profiles, 1):
                badge = theme.bold(theme.cyan(f"[{idx}]"))
                title = theme.bold(f"{prof.name.upper():<6}")
                status = theme.emerald("✓ AVAILABLE") if prof.available else theme.rose("✗ MISSING TOOL")
                say(f"  {badge}  {title}  {prof.note}  ({status})")
                if not prof.available:
                    say(theme.muted(f"       -> Install tool: {get_package_installer(prof.package)}"))
            say(f"  {theme.bold(theme.cyan('[q]'))}  {theme.bold('Back')}    {theme.muted('Return to drive menu')}")

            fs_choice = input("\nFilesystem choice: ").strip().lower()
            if fs_choice == "q" or not fs_choice:
                continue
            if not fs_choice.isdigit() or not (1 <= int(fs_choice) <= len(profiles)):
                say_err("Invalid filesystem choice.")
                continue

            sel_prof = profiles[int(fs_choice) - 1]
            if not sel_prof.available:
                say_err(f"{sel_prof.name.upper()} tool is missing. Install with: {get_package_installer(sel_prof.package)}")
                continue

            label = input(f"\nVolume label (max {sel_prof.label_limit} chars, press Enter for none): ").strip()
            if len(label) > sel_prof.label_limit:
                say_err(f"Label exceeds limit of {sel_prof.label_limit} characters.")
                continue

            say("")
            render_card("PERMANENT ERASE CONFIRMATION", f"All data on {device.path} will be permanently destroyed")
            say("")
            say(f"  {theme.muted('Target Device')}     : {theme.bold(device.path)} ({device.size})")
            say(f"  {theme.muted('Selected Format')}   : {theme.bold(theme.cyan(sel_prof.name.upper()))}")
            say(f"  {theme.muted('Volume Label')}      : {theme.bold(label or '(none)')}")
            say("")
            say_warn(f"Confirm wipe by typing the exact device path ({device.path}):")
            confirm = input("Confirm path: ").strip()
            if confirm != device.path:
                say("Wipe cancelled.")
                continue

            before_dev = get_device_by_path(device.path)
            part_path = execute_wipe(device.path, fs_name=sel_prof.name, label=label, dry_run=False)
            say_ok(f"Formatting complete: {device.path} is now {sel_prof.name.upper()}.")

            settle_udev(device.path, dry_run=False)
            time.sleep(0.5)
            after_dev = get_device_by_path(device.path)
            if before_dev and after_dev:
                say("")
                b_headers, b_rows = build_layout_table_data(before_dev)
                render_table(b_headers, b_rows, title="BEFORE")
                say("")
                a_headers, a_rows = build_layout_table_data(after_dev)
                render_table(a_headers, a_rows, title="AFTER")

            say("")
            render_card("VOLUME MOUNTING", f"Mount fresh volume {part_path} for current user session?")
            say("")
            mount_ans = input(f"Mount {part_path} now? [y/N]: ").strip().lower()
            if mount_ans in ("y", "yes"):
                try:
                    mnt = mount_partition_for_user(part_path, sel_prof.name, label=label)
                    say_ok(f"Mounted {part_path} at {mnt}")
                    say("")
                except Exception as e:
                    say_err(str(e))
            return
        elif choice == "4":
            return


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="stickwash",
        description="Stickwash: A terminal utility for cleaning up removable USB drives on Linux.",
    )
    parser.add_argument("-v", "--version", action="version", version=f"stickwash {__version__}")
    parser.add_argument("--debug", action="store_true", help="Display full Python traceback on errors")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI color output")

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # list
    p_list = subparsers.add_parser("list", help="List block devices")
    p_list.add_argument("--json", action="store_true", help="Output device list as JSON")
    p_list.add_argument("--all", action="store_true", help="Include non-removable internal disks")

    # inspect
    p_inspect = subparsers.add_parser("inspect", help="Inspect a specific block device")
    p_inspect.add_argument("device", help="Path to block device (e.g. /dev/sdc)")
    p_inspect.add_argument("--json", action="store_true", help="Output layout as JSON")

    # wipe
    p_wipe = subparsers.add_parser("wipe", help="Wipe disk and create a new partition & filesystem")
    p_wipe.add_argument("device", help="Path to block device (e.g. /dev/sdc)")
    p_wipe.add_argument("--fs", required=True, choices=["ext4", "exfat", "fat32"], help="Target filesystem")
    p_wipe.add_argument("--label", default="", help="Volume label")
    p_wipe.add_argument("--mount", action="store_true", help="Mount volume immediately after format")
    p_wipe.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")
    p_wipe.add_argument("--dry-run", action="store_true", help="Print actions without modifying disk")
    p_wipe.add_argument("--force", action="store_true", help="Allow targeting non-USB removable drives")

    # relabel
    p_relabel = subparsers.add_parser("relabel", help="Change partition volume label")
    p_relabel.add_argument("partition", help="Path to partition device (e.g. /dev/sdc1)")
    p_relabel.add_argument("--label", required=True, help="New volume label")
    p_relabel.add_argument("--dry-run", action="store_true", help="Print actions without modifying partition")
    p_relabel.add_argument("--force", action="store_true", help="Allow targeting non-USB partition")

    args = parser.parse_args(argv)

    if args.no_color:
        set_color_enabled(False)

    try:
        if args.command == "list":
            cmd_list(args)
        elif args.command == "inspect":
            cmd_inspect(args)
        elif args.command == "wipe":
            cmd_wipe(args)
        elif args.command == "relabel":
            cmd_relabel(args)
        else:
            interactive_wizard()
    except KeyboardInterrupt:
        say("\nAborted.")
        sys.exit(130)
    except Exception as exc:
        if args.debug:
            raise
        say_err(str(exc))
        sys.exit(1)
