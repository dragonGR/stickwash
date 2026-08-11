import unittest
from unittest.mock import patch

from stickwash_lib.formatters import (
    format_partition,
    get_filesystem_profiles,
    get_profile_by_name,
    relabel_partition,
)


class TestFormatters(unittest.TestCase):
    def test_get_filesystem_profiles(self) -> None:
        profiles = get_filesystem_profiles()
        self.assertEqual(len(profiles), 3)
        names = [p.name for p in profiles]
        self.assertIn("ext4", names)
        self.assertIn("exfat", names)
        self.assertIn("fat32", names)

    def test_get_profile_by_name(self) -> None:
        prof = get_profile_by_name("exFAT")
        self.assertIsNotNone(prof)
        self.assertEqual(prof.name, "exfat")
        self.assertEqual(prof.label_limit, 15)

    @patch("stickwash_lib.formatters.exec_command")
    def test_format_partition_dry_run(self, mock_exec) -> None:
        prof = get_profile_by_name("ext4")
        self.assertIsNotNone(prof)
        format_partition(prof, "/dev/sdc1", label="MYSTICK", dry_run=True)
        mock_exec.assert_not_called()

    @patch("stickwash_lib.formatters.have_tool")
    @patch("stickwash_lib.formatters.unmount_partition")
    @patch("stickwash_lib.formatters.exec_command")
    def test_relabel_partition_dry_run(self, mock_exec, mock_unmount, mock_have_tool) -> None:
        mock_have_tool.return_value = True
        relabel_partition("ext4", "/dev/sdc1", "NEWLABEL", dry_run=True)
        mock_exec.assert_not_called()
        mock_unmount.assert_not_called()

    def test_relabel_unsupported_fs(self) -> None:
        with self.assertRaises(ValueError):
            relabel_partition("ntfs", "/dev/sdc1", "TESTLABEL")

    def test_format_fat32_and_exfat_native(self) -> None:
        import os
        import tempfile
        from stickwash_lib.formatters import format_exfat_native, format_fat32_native, get_device_size_bytes

        with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as tf:
            tf.seek(64 * 1024 * 1024 - 1)
            tf.write(b"\0")
            img_path = tf.name

        try:
            self.assertEqual(get_device_size_bytes(img_path), 64 * 1024 * 1024)

            format_fat32_native(img_path, label="TESTFAT")
            with open(img_path, "rb") as f:
                header = f.read(512)
                self.assertIn(b"FAT32", header)
                self.assertIn(b"TESTFAT", header)

            format_exfat_native(img_path, label="TESTEXFAT")
            with open(img_path, "rb") as f:
                header = f.read(512)
                self.assertIn(b"EXFAT", header)
        finally:
            if os.path.exists(img_path):
                os.remove(img_path)


if __name__ == "__main__":
    unittest.main()
