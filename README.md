# Stickwash

**Stickwash** is a terminal-only CLI utility for inspecting, relabeling, and rebuilding removable USB drives on Linux.

It resolves common partitions and partition tables left behind by bootable ISO writers (e.g. Arch, Ubuntu, Ventoy) and restores USB sticks to clean single-partition volumes (ext4, exFAT, or FAT32).

---

## Key Features

- **Automated USB Discovery:** Detects removable USB block devices with model, size, serial number, and partition layouts.
- **Root & Mount Safeguards:** Refuses to format drives backing system mounts (`/`, `/boot`, `/home`, `/var`, `/usr`, `/etc`, or swap).
- **Subcommands & Interactive TUI:** Run interactively without arguments, or use non-interactive CLI commands (`list`, `inspect`, `wipe`, `relabel`).
- **Dry-Run Mode:** Simulate wiping or relabeling operations using `--dry-run` to inspect exact terminal commands before execution.
- **JSON Output:** Export device and partition structures with `--json` for scripting and automation.
- **Filesystem Support & Tool Detection:** Supports `ext4`, `exFAT`, and `FAT32` with automatic tool verification (`mkfs.ext4`, `mkfs.exfat`, `mkfs.fat`, `e2label`, `exfatlabel`, `fatlabel`) and package install hints.
- **User Permission Handover:** Automatically mounts formatted volumes for the invoking `$SUDO_USER` under `/run/media/$SUDO_USER/<label>` or `/mnt/<label>`.

---

## Requirements

### Core System Tools
- `python3` (>= 3.10)
- `util-linux` (`lsblk`, `findmnt`, `wipefs`, `umount`, `mount`)
- `parted`
- `systemd` / `udev` (`partprobe`, `udevadm`)

### Filesystem Formatter Packages
- **ext4:** `e2fsprogs` (`mkfs.ext4`, `e2label`)
- **exFAT:** `exfatprogs` (`mkfs.exfat`, `exfatlabel`)
- **FAT32:** `dosfstools` (`mkfs.fat` / `mkfs.vfat`, `fatlabel`)

On Arch Linux:
```bash
sudo pacman -S util-linux parted e2fsprogs exfatprogs dosfstools
```

On Ubuntu / Debian:
```bash
sudo apt update && sudo apt install util-linux parted e2fsprogs exfatprogs dosfstools
```

---

## Command Usage

### 1. Interactive TUI Mode
Run `stickwash` as root to open the interactive wizard:
```bash
sudo ./stickwash
```

### 2. List Drives
List all removable USB drives:
```bash
stickwash list
```

Export layout in JSON format:
```bash
stickwash list --json
```

Include internal non-removable disks:
```bash
stickwash list --all
```

### 3. Inspect Device
Display detailed partition table and mountpoints for a specific block device:
```bash
stickwash inspect /dev/sdc
```

### 4. Wipe and Rebuild Drive
Wipe signatures, write a fresh GPT table, and format a primary partition:
```bash
sudo stickwash wipe /dev/sdc --fs exfat --label SHAREDATA -y
```

Simulate wiping with `--dry-run`:
```bash
stickwash wipe /dev/sdc --fs ext4 --label DATA --dry-run
```

Wipe and automatically mount after formatting:
```bash
sudo stickwash wipe /dev/sdc --fs ext4 --label LINUXUSB --mount -y
```

### 5. Relabel Partition
Relabel an existing partition without reformatting:
```bash
sudo stickwash relabel /dev/sdc1 --label BACKUP
```

---

## Safety Guarantees

- **Destruction Protection:** Never touches devices backing `/`, `/boot`, `/home`, or active swap partitions.
- **Device Path Typing:** Interactive wiping requires explicitly re-typing the full target device path (e.g. `/dev/sdc`).
- **Removable Drive Filtering:** Rejects non-removable internal drives unless explicitly overridden with `--force`.

---

## Project Structure

```text
stickwash/
├── README.md                  # Documentation and usage guide
├── pyproject.toml             # Package metadata and test runner config
├── stickwash                  # Executable entry point launcher
├── stickwash_lib/             # Modern Python library
│   ├── __init__.py            # Package version
│   ├── cli.py                 # Argument parsing and interactive TUI controller
│   ├── disk.py                # lsblk/findmnt JSON parsing & system mount safeguards
│   ├── formatters.py          # Parted/wipefs/mkfs execution & tool detection
│   └── ui.py                  # ANSI TrueColor styling, tables, & live spinners
└── tests/                     # Unit test suite
    ├── test_cli.py
    ├── test_disk.py
    └── test_formatters.py
```

---

## Running Tests

Run the unit test suite:
```bash
python3 -m unittest discover -s tests
```
