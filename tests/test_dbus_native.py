"""
Testes das tools D-Bus com mocks para rodar em containers headless.
"""

from unittest.mock import MagicMock, patch

from src.tools.dbus_native import NativeSystemTool, NativeToolResult


class TestNativeSystemTool:
    def test_action_classification(self):
        tool = NativeSystemTool()
        assert tool.is_read_only("service_status") is True
        assert tool.is_read_only("restart_service") is False
        assert tool.is_known_action("network_status") is True
        assert tool.is_known_action("unknown") is False

    def test_service_status_uses_systemd_dbus(self):
        tool = NativeSystemTool()
        bus = MagicMock()
        manager = MagicMock()
        unit = MagicMock()
        unit.ActiveState = "active"
        unit.SubState = "running"
        unit.LoadState = "loaded"
        manager.LoadUnit.return_value = "/org/freedesktop/systemd1/unit/docker_2eservice"
        bus.get.side_effect = [manager, unit]

        with patch.object(tool, "_system_bus", return_value=bus):
            result = tool.service_status("docker")

        assert result.success is True
        assert result.read_only is True
        assert result.data["service"] == "docker.service"
        assert result.data["active_state"] == "active"
        manager.LoadUnit.assert_called_once_with("docker.service")

    def test_service_action_returns_job_path(self):
        tool = NativeSystemTool()
        bus = MagicMock()
        manager = MagicMock()
        manager.RestartUnit.return_value = "/job/42"
        bus.get.return_value = manager

        with patch.object(tool, "_system_bus", return_value=bus):
            result = tool.service_action("ssh.service", "restart_service")

        assert result.success is True
        assert result.read_only is False
        assert result.data["job_path"] == "/job/42"
        manager.RestartUnit.assert_called_once_with("ssh.service", "replace")

    def test_network_status_degrades_gracefully(self):
        tool = NativeSystemTool()
        with patch.object(tool, "_system_bus", side_effect=RuntimeError("no bus")):
            result = tool.run("network_status")

        assert result.success is False
        assert result.degraded is True
        assert "no bus" in result.error_message

    def test_network_status_reads_network_manager(self):
        tool = NativeSystemTool()
        bus = MagicMock()
        nm = MagicMock()
        nm.NetworkingEnabled = True
        nm.WirelessEnabled = False
        nm.WirelessHardwareEnabled = True
        nm.Connectivity = 4
        nm.State = 70
        nm.PrimaryConnection = "/connection/1"
        bus.get.return_value = nm

        with patch.object(tool, "_system_bus", return_value=bus):
            result = tool.network_status()

        assert result.success is True
        assert result.data["networking_enabled"] is True
        assert result.data["connectivity"] == 4

    def test_unknown_action_returns_structured_error(self):
        result = NativeSystemTool().run("not_real")
        assert result.success is False
        assert result.degraded is True
        assert result.read_only is True

    def test_run_dispatches_service_status(self):
        tool = NativeSystemTool()
        with patch.object(tool, "service_status") as service_status:
            service_status.return_value = NativeToolResult(True, "dbus_native", "service_status")
            result = tool.run("service_status", {"service": "docker"})

        assert result.success is True
        service_status.assert_called_once_with("docker")

    def test_run_dispatches_mutating_service_action(self):
        tool = NativeSystemTool()
        with patch.object(tool, "service_action") as service_action:
            service_action.return_value = NativeToolResult(True, "dbus_native", "restart_service", read_only=False)
            result = tool.run("restart_service", {"service": "docker"})

        assert result.read_only is False
        service_action.assert_called_once_with("docker", "restart_service")

    def test_set_networking_enabled_writes_network_manager_property(self):
        tool = NativeSystemTool()
        bus = MagicMock()
        nm = MagicMock()
        bus.get.return_value = nm

        with patch.object(tool, "_system_bus", return_value=bus):
            result = tool.set_networking_enabled(False)

        assert result.success is True
        assert result.read_only is False
        assert nm.NetworkingEnabled is False

    def test_set_wireless_enabled_writes_network_manager_property(self):
        tool = NativeSystemTool()
        bus = MagicMock()
        nm = MagicMock()
        bus.get.return_value = nm

        with patch.object(tool, "_system_bus", return_value=bus):
            result = tool.set_wireless_enabled(True)

        assert result.success is True
        assert result.read_only is False
        assert nm.WirelessEnabled is True

    def test_gnome_presence_reads_session_bus(self):
        tool = NativeSystemTool()
        bus = MagicMock()
        presence = MagicMock()
        presence.status = 2
        bus.get.return_value = presence

        with patch.object(tool, "_session_bus", return_value=bus):
            result = tool.gnome_presence()

        assert result.success is True
        assert result.data["status"] == 2

    def test_set_gnome_presence_calls_set_status(self):
        tool = NativeSystemTool()
        bus = MagicMock()
        presence = MagicMock()
        bus.get.return_value = presence

        with patch.object(tool, "_session_bus", return_value=bus):
            result = tool.set_gnome_presence(3)

        assert result.success is True
        assert result.read_only is False
        presence.SetStatus.assert_called_once_with(3)

    def test_package_status_uses_dpkg_status_fallback(self, tmp_path):
        status_file = tmp_path / "status"
        status_file.write_text(
            "Package: docker.io\n"
            "Status: install ok installed\n"
            "Version: 24.0\n"
            "\n"
            "Package: vim\n"
            "Status: deinstall ok config-files\n"
            "Version: 9.0\n",
            encoding="utf-8",
        )
        tool = NativeSystemTool()

        with (
            patch.object(tool, "_packagekit_available", return_value=True),
            patch("src.tools.dbus_native.Path", return_value=status_file),
        ):
            result = tool.package_status("docker.io")

        assert result.success is True
        assert result.data["installed"] is True
        assert result.data["version"] == "24.0"
        assert result.data["packagekit_available"] is True

    def test_package_status_empty_package_degrades_through_run(self):
        result = NativeSystemTool().run("package_status", {"package": ""})
        assert result.success is False
        assert result.degraded is True

    def test_normalize_service_requires_name(self):
        tool = NativeSystemTool()
        with patch.object(tool, "_system_bus"):
            result = tool.run("service_status", {"service": ""})

        assert result.success is False
        assert "Nome do serviço" in result.error_message

    def test_result_json_is_stable(self):
        result = NativeToolResult(True, "dbus_native", "service_status", data={"service": "docker"})
        assert '"service": "docker"' in result.to_json()
