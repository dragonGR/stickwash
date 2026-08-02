# Stickwash

Stickwash is a small Bash tool for one job.

It finds removable USB drives on a Linux box, shows you what is on them, and can wipe one clean into a fresh partition in ext4, exFAT, or FAT32. It is meant for the exact mess you get after writing an installer image to a flash drive and wanting the stick back.

## What it does

- lists removable USB drives
- shows the current partition layout with `lsblk`
- asks you what to do with the selected drive
- wipes old partitions and filesystem signatures
- creates a new GPT partition table
- lets you choose ext4, exFAT, or FAT32
- shows a before and after layout summary once formatting is done
- asks you to type the full device path before it does anything destructive
- sends you back to a clean start prompt if you want to wipe another drive
- refuses to touch the drive that currently backs `/`

## What it does not do

- it does not auto mount the new partition
- it does not try to be clever with internal drives
- it does not run without root
- it does not pretend missing formatter tools are fine

That last point is on purpose. Disk tools should be boring and explicit.

## Files

```text
.
├── README.md
└── stickwash
```

## Requirements

You need a Linux system with these tools installed:

- bash
- lsblk
- findmnt
- umount
- wipefs
- parted
- partprobe
- udevadm

Formatter tools:

- ext4 needs `mkfs.ext4` from `e2fsprogs`
- exFAT needs `mkfs.exfat` from `exfatprogs`
- FAT32 needs `mkfs.fat` or `mkfs.vfat` from `dosfstools`

On Arch Linux, the usual packages are `util-linux`, `parted`, `e2fsprogs`, `exfatprogs`, and `dosfstools`.

## Run it

```bash
sudo ./stickwash
```

You will see a list of removable USB drives. Pick one by number.

Inside the drive menu you can:

1. show the current layout
2. wipe the drive and format it
3. go back to the drive list

If you choose the wipe path, the script will:

1. ask which filesystem you want
2. ask for an optional volume label
3. show the drive layout again
4. ask you to type the full device path, for example `/dev/sdc`
5. unmount any mounted partitions on that drive
6. wipe partition and filesystem signatures
7. create a fresh GPT table
8. create one partition that fills the drive
9. format it as ext4, exFAT, or FAT32
10. show what the drive looked like before and after
11. ask whether you want to start over or quit

## Typical use case

You wrote an Arch ISO to a stick. Now the stick has weird partitions and your desktop only sees part of the space.

Run Stickwash, pick that USB drive, choose the filesystem you want, confirm the device path, and it will give you a normal single partition again.

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
  2. Wipe it and format it
  3. Back to the drive list
What now: 2

Pick a filesystem:
  1. ext4  Linux default
  2. exFAT  Windows and Linux
  3. FAT32  Older but widely supported
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
Before, it looked like this:
PATH       SIZE FSTYPE LABEL   MOUNTPOINTS
/dev/sdc  14.4G
/dev/sdc1  900M iso9660 ARCH_2026
/dev/sdc2   80M vfat   ARCHISO

Now it looks like this:
PATH       SIZE FSTYPE LABEL     MOUNTPOINTS
/dev/sdc  14.4G
/dev/sdc1 14.4G exfat  SHAREUSB

If you want to wipe another drive, start over from the drive list.
Press Enter to start over, or q to quit:
```

## Safety notes

Read this part before you run it.

- The wipe path is destructive.
- The script is written for removable USB drives.
- It still shows device paths because humans should verify disk names themselves.
- If you pick the wrong drive and confirm it, the data is gone.
- If a partition is mounted, the script tries to unmount it first.

## Filesystem choices

- `ext4` is the Linux default
- `exFAT` is the best fit if the stick needs to move between Linux and Windows
- `FAT32` is the widest compatibility option, but it has the old 4 GB file size limit

## How the script works

At a high level it does this:

```text
scan drives
  -> pick one
  -> choose filesystem
  -> confirm device path
  -> unmount child partitions
  -> wipe signatures
  -> write new GPT table
  -> create one partition
  -> run the matching formatter
```

The script uses `lsblk` for discovery and display, `wipefs` to clear old signatures, `parted` to write the new partition table, and the matching formatter for the filesystem you picked.

## Troubleshooting

### It says no removable USB drives found

Unplug the stick, plug it back in, then run the script again. If your enclosure reports itself in an unusual way, check what `lsblk -dnP -o PATH,RM,TRAN,SIZE,MODEL,SERIAL,TYPE` shows.

### It says to run as root

That is expected. Use `sudo ./stickwash`.

### The new partition does not show up right away

The script already calls `partprobe` and waits for udev. If your system is slow to notice new block devices, unplug and replug the stick once.

## Notes for future changes

One sensible next step would be NTFS or user defined partition layouts. I left those out so the current menu stays easy to trust.
