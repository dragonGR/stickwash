import unittest
from unittest.mock import patch

from stickwash_lib.disk import (
    BlockDevice,
    Partition,
    _parse_partitions,
    discover_drives,
    is_system_device,
)


class TestDiskDiscovery(unittest.TestCase):
    def test_block_device_display_title(self) -> None:
        dev = BlockDevice(
            path="/dev/sdc",
            size="14.4G",
            model="DataTraveler 3.0",
            serial="80C5F29E",
        )
        self.assertIn("/dev/sdc", dev.display_title)
        self.assertIn("14.4G", dev.display_title)
        self.assertIn("DataTraveler 3.0", dev.display_title)
        self.assertIn("[80C5F29E]", dev.display_title)

    def test_parse_partitions(self) -> None:
        children = [
            {
                "path": "/dev/sdc1",
                "type": "part",
                "fstype": "ext4",
                "label": "DATA",
                "size": "14G",
                "mountpoints": ["/run/media/user/DATA"],
            }
        ]
        parts = _parse_partitions(children)
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0].path, "/dev/sdc1")
        self.assertEqual(parts[0].fstype, "ext4")
        self.assertEqual(parts[0].label, "DATA")

    @patch("stickwash_lib.disk.exec_command")
    def test_discover_drives_removable_filter(self, mock_exec) -> None:
        mock_lsblk_json = """{
            "blockdevices": [
                {
                    "path": "/dev/sda",
                    "rm": false,
                    "tran": "sata",
                    "size": "500G",
                    "type": "disk",
                    "children": []
                },
                {
                    "path": "/dev/sdb",
                    "rm": true,
                    "tran": "usb",
                    "size": "16G",
                    "model": "USB Flash",
                    "type": "disk",
                    "children": []
                }
            ]
        }"""
        mock_exec.return_value = (0, mock_lsblk_json, "")

        removable_drives = discover_drives(removable_only=True)
        self.assertEqual(len(removable_drives), 1)
        self.assertEqual(removable_drives[0].path, "/dev/sdb")

        all_drives = discover_drives(removable_only=False)
        self.assertEqual(len(all_drives), 2)

    @patch("stickwash_lib.disk.get_active_mounts")
    def test_is_system_device(self, mock_mounts) -> None:
        mock_mounts.return_value = {
            "/": "/dev/nvme0n1p2",
            "/boot": "/dev/nvme0n1p1",
        }
        is_sys, reason = is_system_device("/dev/nvme0n1")
        self.assertTrue(is_sys)
        self.assertIn("critical mount point: /", reason)

        is_sys_usb, _ = is_system_device("/dev/sdc")
        self.assertFalse(is_sys_usb)


if __name__ == "__main__":
    unittest.main()
