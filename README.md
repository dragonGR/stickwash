# Stickwash

Stickwash is a small Bash tool for cleaning up USB sticks on Linux.

It finds removable USB drives, shows you their current layout, lets you relabel an existing partition, or wipes the drive and rebuilds it as a fresh ext4, exFAT, or FAT32 volume. It is built for the common mess left behind by bootable ISO writers.

## What it does

- lists removable USB drives
- shows the current partition layout with `lsblk`
- lets you inspect a drive before touching it
- lets you change a partition label without reformatting
- wipes old partitions and filesystem signatures when you choose the full rebuild path
- creates a new GPT partition table
- lets you choose ext4, exFAT, or FAT32
- explains which filesystem makes sense for Linux only use, Linux plus Windows use, or maximum compatibility
- shows missing formatter tools and the package command to install them
- shows a before and after summary once the job is done
- can mount the fresh partition right away after formatting
- refuses to touch the drive that currently backs `/`

## What it does not do

- it does not auto pick a filesystem for you
- it does not touch internal drives
- it does not run without root
- it does not hide destructive steps behind cute wording

That last point matters. Disk tools should be plain.

## Files

```text
.
├── README.md
└── stickwash
```

## Requirements

Base tools:

- bash
- lsblk
- findmnt
- umount
- wipefs
- parted
- partprobe
- udevadm
- mount
- mkdir
- chown

Filesystem tools:

- ext4 needs `mkfs.ext4` from `e2fsprogs`
- exFAT needs `mkfs.exfat` from `exfatprogs`
- FAT32 needs `mkfs.fat` or `mkfs.vfat` from `dosfstools`
- relabeling ext filesystems needs `e2label` from `e2fsprogs`
- relabeling exFAT needs `exfatlabel` from `exfatprogs`
- relabeling FAT32 needs `fatlabel` from `dosfstools`

On Arch Linux, the usual packages are:

```bash
sudo pacman -S util-linux parted e2fsprogs exfatprogs dosfstools
```

## Run it

```bash
sudo ./stickwash
```

You will get a list of removable USB drives. Pick one by number.

Inside the drive menu you can:

1. show the current layout
2. change label only
3. wipe it and format it
4. go back to the drive list

## Filesystem guide

- `ext4` is the Linux default. Good if the stick stays in Linux land.
- `exFAT` is the best fit if the stick needs to move between Linux and Windows.
- `FAT32` works almost everywhere, but it still has the old 4 GB file size limit.

## Relabel only flow

The relabel path is for the cases where the filesystem is already fine and you just want a cleaner name.

The script will:

1. list partitions on the selected drive
2. let you pick one
3. detect the filesystem type
4. use the right relabel tool if it is supported
5. show a before and after summary

Supported relabel paths:

- ext2, ext3, ext4 via `e2label`
- exFAT via `exfatlabel`
- FAT32 via `fatlabel`

## Full wipe and format flow

If you choose the full rebuild path, the script will:

1. ask which filesystem you want
2. ask for an optional label
3. show the current layout again
4. ask you to type the exact device path
5. unmount any mounted partitions on that drive
6. wipe partition and filesystem signatures
7. create a fresh GPT table
8. create one partition that fills the drive
9. run the matching formatter
10. show a before and after summary
11. offer to mount the new partition right away
12. let you start over or quit

## Typical use case

You wrote an Arch ISO to a stick. Now the stick has odd partitions and your desktop only sees part of the space.

Run Stickwash, pick that USB drive, choose `exFAT` if you want Windows support too, confirm the device path, and the script will hand you back a normal single partition.

## Example session

```text
$ sudo ./stickwash
Stickwash

This script only lists removable USB drives.

Drives on this machine:
  1. /dev/sdc  14.4G  DataTraveler 3.0  [80C5F29E93F0B2B117DD1B4A]
  r. scan again
  q. quit
Pick a drive: 1

Picked: /dev/sdc  14.4G  DataTraveler 3.0  [80C5F29E93F0B2B117DD1B4A]
  1. Show current layout
  2. Change label only
  3. Wipe it and format it
  4. Back to the drive list
What now: 3

Pick a filesystem:
  1. ext4  Linux default
  2. exFAT  Best for Linux and Windows
  3. FAT32  Widest support, 4 GB file limit
  q. back
Filesystem: 2
exFAT label, blank is fine: SHAREUSB

This will erase every partition and filesystem signature on /dev/sdc.
There is no undo.

PATH       SIZE FSTYPE LABEL   MOUNTPOINTS
/dev/sdc  14.4G
/dev/sdc1  900M iso9660 ARCH_2026
/dev/sdc2   80M vfat   ARCHISO

Type the device path to continue: /dev/sdc

/dev/sdc has been formatted as exFAT.
Filesystem: exFAT
Partition: /dev/sdc1
Label: SHAREUSB

Before:
PATH       SIZE FSTYPE LABEL   MOUNTPOINTS
/dev/sdc  14.4G
/dev/sdc1  900M iso9660 ARCH_2026
/dev/sdc2   80M vfat   ARCHISO

Now:
PATH       SIZE FSTYPE LABEL     MOUNTPOINTS
/dev/sdc  14.4G
/dev/sdc1 14.4G exfat  SHAREUSB

What next:
  1. Mount it now
  2. Start over
  3. Quit
```

## Safety notes

Read this before you trust your fingers.

- The wipe path is destructive.
- The script only lists removable USB drives, but you still need to verify the device path yourself.
- If you confirm the wrong drive, the data is gone.
- If a partition is mounted, the script unmounts it before formatting or relabeling.
- The script refuses to touch the drive backing `/`.

## How the script works

At a high level:

```text
scan drives
  -> pick one
  -> inspect, relabel, or rebuild
  -> confirm target
  -> unmount if needed
  -> relabel or rebuild
  -> show before and after
  -> optionally mount the fresh partition
```

Stickwash uses `lsblk` for discovery and display, `wipefs` to clear old signatures, `parted` to write the new partition table, and the matching formatter or label tool for the filesystem you picked.

## Troubleshooting

### exFAT or FAT32 says unavailable here

That means the formatter tool is missing. On Arch Linux:

```bash
sudo pacman -S exfatprogs dosfstools
```

### Relabel support says unavailable here

The matching label tool is missing. The script prints the package command it expects on your system.

### It says no removable USB drives found

Unplug the stick, plug it back in, then run the script again. If your enclosure reports itself in an unusual way, check what `lsblk -dnP -o PATH,RM,TRAN,SIZE,MODEL,SERIAL,TYPE` shows.

### It says to run as root

That is expected. Use `sudo ./stickwash`.

### The new partition does not show up right away

The script already calls `partprobe` and waits for udev. If your system is slow to notice new block devices, unplug and replug the stick once.

## Notes for future changes

A sensible next step would be NTFS support or custom multi partition layouts. I left those out so the current menu stays easy to trust.
