"""
Testes da tool read-only de recursos.
"""

from types import SimpleNamespace
from unittest.mock import patch

from src.tools.resources import ResourceMonitorTool


class TestResourceMonitorTool:
    @patch("src.tools.resources.psutil")
    def test_run_returns_structured_snapshot(self, mock_psutil):
        mock_psutil.cpu_percent.return_value = 23.5
        mock_psutil.cpu_count.side_effect = [8, 4]
        mock_psutil.virtual_memory.return_value = SimpleNamespace(
            total=16_000,
            available=8_000,
            used=8_000,
            percent=50.0,
        )
        mock_psutil.disk_io_counters.return_value = SimpleNamespace(
            read_count=10,
            write_count=20,
            read_bytes=1024,
            write_bytes=2048,
            read_time=1,
            write_time=2,
            busy_time=3,
        )
        mock_psutil.net_io_counters.return_value = SimpleNamespace(
            bytes_sent=3000,
            bytes_recv=4000,
            packets_sent=30,
            packets_recv=40,
            errin=0,
            errout=0,
            dropin=0,
            dropout=0,
        )

        snapshot = ResourceMonitorTool().run()

        assert snapshot["read_only"] is True
        assert snapshot["cpu"]["percent"] == 23.5
        assert snapshot["memory"]["percent"] == 50.0
        assert snapshot["disk_io"]["read_bytes"] == 1024
        assert snapshot["network"]["bytes_recv"] == 4000

    @patch("src.tools.resources.psutil")
    def test_run_handles_missing_io_counters(self, mock_psutil):
        mock_psutil.cpu_percent.return_value = 0
        mock_psutil.cpu_count.return_value = 1
        mock_psutil.virtual_memory.return_value = SimpleNamespace(
            total=1,
            available=1,
            used=0,
            percent=0.0,
        )
        mock_psutil.disk_io_counters.return_value = None
        mock_psutil.net_io_counters.return_value = None

        snapshot = ResourceMonitorTool().run()

        assert snapshot["disk_io"]["read_bytes"] is None
        assert snapshot["network"]["bytes_recv"] is None
