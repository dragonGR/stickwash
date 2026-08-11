import unittest
from unittest.mock import patch

from stickwash_lib.cli import main


class TestCLI(unittest.TestCase):
    def test_version_flag(self) -> None:
        with self.assertRaises(SystemExit) as cm:
            main(["--version"])
        self.assertEqual(cm.exception.code, 0)

    @patch("stickwash_lib.cli.discover_drives")
    def test_list_command_json(self, mock_discover) -> None:
        mock_discover.return_value = []
        with patch("sys.stdout"):
            main(["list", "--json"])

    @patch("stickwash_lib.cli.get_device_by_path")
    @patch("stickwash_lib.cli.is_system_device")
    @patch("stickwash_lib.cli.execute_wipe")
    def test_wipe_dry_run(self, mock_execute, mock_is_sys, mock_get_dev) -> None:
        mock_is_sys.return_value = (False, "")
        mock_dev = unittest.mock.MagicMock()
        mock_dev.rm = True
        mock_dev.tran = "usb"
        mock_get_dev.return_value = mock_dev

        main(["wipe", "/dev/sdc", "--fs", "ext4", "--label", "TEST", "--dry-run"])
        mock_execute.assert_called_once_with(
            "/dev/sdc",
            fs_name="ext4",
            label="TEST",
            dry_run=True,
            mount=False,
        )


if __name__ == "__main__":
    unittest.main()
