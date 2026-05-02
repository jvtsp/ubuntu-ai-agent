"""
Ferramentas nativas via D-Bus para administração do Ubuntu.

As chamadas usam pydbus quando disponível e degradam com erro estruturado em
ambientes headless, containers ou sessões sem os serviços alvo. A classe separa
ações read-only de ações mutáveis para que o grafo solicite confirmação antes
de qualquer mudança.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.logger import get_logger

log = get_logger("tools.dbus_native")


READ_ONLY_ACTIONS = {
    "service_status",
    "network_status",
    "gnome_presence",
    "package_status",
}

MUTATING_ACTIONS = {
    "start_service",
    "stop_service",
    "restart_service",
    "set_networking_enabled",
    "set_wireless_enabled",
    "set_gnome_presence",
}


@dataclass(frozen=True)
class NativeToolResult:
    """Resultado estruturado de uma ferramenta nativa."""

    success: bool
    tool: str
    action: str
    data: dict[str, Any] = field(default_factory=dict)
    error_message: str = ""
    degraded: bool = False
    read_only: bool = True

    def to_json(self) -> str:
        return json.dumps(
            {
                "success": self.success,
                "tool": self.tool,
                "action": self.action,
                "data": self.data,
                "error_message": self.error_message,
                "degraded": self.degraded,
                "read_only": self.read_only,
            },
            ensure_ascii=False,
            sort_keys=True,
        )


class NativeSystemTool:
    """Executa ações nativas de sysadmin via D-Bus ou fallback read-only."""

    name = "dbus_native"

    def is_known_action(self, action: str) -> bool:
        return action in READ_ONLY_ACTIONS or action in MUTATING_ACTIONS

    def is_read_only(self, action: str) -> bool:
        return action in READ_ONLY_ACTIONS

    def run(self, action: str, args: dict[str, Any] | None = None) -> NativeToolResult:
        """Despacha uma ação nativa com tratamento rigoroso de exceções."""
        args = args or {}
        if not self.is_known_action(action):
            return NativeToolResult(
                success=False,
                tool=self.name,
                action=action,
                error_message=f"Ação D-Bus desconhecida: {action}",
                degraded=True,
                read_only=True,
            )

        try:
            if action == "service_status":
                return self.service_status(str(args.get("service", "")))
            if action in {"start_service", "stop_service", "restart_service"}:
                return self.service_action(str(args.get("service", "")), action)
            if action == "network_status":
                return self.network_status()
            if action == "set_networking_enabled":
                return self.set_networking_enabled(bool(args.get("enabled", True)))
            if action == "set_wireless_enabled":
                return self.set_wireless_enabled(bool(args.get("enabled", True)))
            if action == "gnome_presence":
                return self.gnome_presence()
            if action == "set_gnome_presence":
                return self.set_gnome_presence(int(args.get("status", 0)))
            if action == "package_status":
                return self.package_status(str(args.get("package", "")))
        except Exception as exc:
            log.warning("Falha em ação D-Bus %s: %s", action, str(exc)[:200])
            return NativeToolResult(
                success=False,
                tool=self.name,
                action=action,
                error_message=str(exc)[:300],
                degraded=True,
                read_only=self.is_read_only(action),
            )

        return NativeToolResult(
            success=False,
            tool=self.name,
            action=action,
            error_message="Ação não implementada.",
            degraded=True,
            read_only=self.is_read_only(action),
        )

    def service_status(self, service: str) -> NativeToolResult:
        """Consulta estado de um serviço systemd pelo D-Bus do sistema."""
        service = self._normalize_service_name(service)
        manager, bus = self._systemd_manager()
        unit_path = manager.LoadUnit(service)
        unit = bus.get("org.freedesktop.systemd1", unit_path)
        data = {
            "service": service,
            "active_state": getattr(unit, "ActiveState", "unknown"),
            "sub_state": getattr(unit, "SubState", "unknown"),
            "load_state": getattr(unit, "LoadState", "unknown"),
            "unit_path": str(unit_path),
        }
        return NativeToolResult(True, self.name, "service_status", data=data, read_only=True)

    def service_action(self, service: str, action: str) -> NativeToolResult:
        """Inicia, para ou reinicia um serviço via systemd D-Bus."""
        service = self._normalize_service_name(service)
        manager, _bus = self._systemd_manager()
        method_name = {
            "start_service": "StartUnit",
            "stop_service": "StopUnit",
            "restart_service": "RestartUnit",
        }[action]
        job_path = getattr(manager, method_name)(service, "replace")
        return NativeToolResult(
            True,
            self.name,
            action,
            data={"service": service, "job_path": str(job_path)},
            read_only=False,
        )

    def network_status(self) -> NativeToolResult:
        """Consulta NetworkManager pelo D-Bus do sistema."""
        nm = self._system_bus().get("org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager")
        data = {
            "networking_enabled": bool(getattr(nm, "NetworkingEnabled", False)),
            "wireless_enabled": bool(getattr(nm, "WirelessEnabled", False)),
            "wireless_hardware_enabled": bool(getattr(nm, "WirelessHardwareEnabled", False)),
            "connectivity": int(getattr(nm, "Connectivity", -1)),
            "state": int(getattr(nm, "State", -1)),
            "primary_connection": str(getattr(nm, "PrimaryConnection", "")),
        }
        return NativeToolResult(True, self.name, "network_status", data=data, read_only=True)

    def set_networking_enabled(self, enabled: bool) -> NativeToolResult:
        """Ajusta networking global do NetworkManager respeitando permissões da sessão."""
        nm = self._system_bus().get("org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager")
        nm.NetworkingEnabled = enabled
        return NativeToolResult(
            True,
            self.name,
            "set_networking_enabled",
            data={"networking_enabled": enabled},
            read_only=False,
        )

    def set_wireless_enabled(self, enabled: bool) -> NativeToolResult:
        """Ajusta Wi-Fi do NetworkManager respeitando permissões da sessão."""
        nm = self._system_bus().get("org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager")
        nm.WirelessEnabled = enabled
        return NativeToolResult(
            True,
            self.name,
            "set_wireless_enabled",
            data={"wireless_enabled": enabled},
            read_only=False,
        )

    def gnome_presence(self) -> NativeToolResult:
        """Consulta presença da sessão GNOME se o serviço existir."""
        presence = self._session_bus().get("org.gnome.SessionManager", "/org/gnome/SessionManager/Presence")
        data = {"status": int(getattr(presence, "status", getattr(presence, "Status", -1)))}
        return NativeToolResult(True, self.name, "gnome_presence", data=data, read_only=True)

    def set_gnome_presence(self, status: int) -> NativeToolResult:
        """Ajusta presença GNOME via sessão do usuário."""
        presence = self._session_bus().get("org.gnome.SessionManager", "/org/gnome/SessionManager/Presence")
        presence.SetStatus(status)
        return NativeToolResult(True, self.name, "set_gnome_presence", data={"status": status}, read_only=False)

    def package_status(self, package: str) -> NativeToolResult:
        """Verifica status de pacote sem terminal; tenta PackageKit e usa dpkg status como fallback."""
        package = package.strip()
        if not package:
            raise ValueError("Nome do pacote não informado.")

        packagekit_available = self._packagekit_available()
        dpkg_data = self._read_dpkg_status(package)
        data = {
            "package": package,
            "packagekit_available": packagekit_available,
            "installed": dpkg_data.get("installed", False),
            "version": dpkg_data.get("version", ""),
            "source": "packagekit+dpkg_status_file" if packagekit_available else "dpkg_status_file",
        }
        return NativeToolResult(True, self.name, "package_status", data=data, read_only=True)

    def _system_bus(self):
        from pydbus import SystemBus

        return SystemBus()

    def _session_bus(self):
        from pydbus import SessionBus

        return SessionBus()

    def _systemd_manager(self):
        bus = self._system_bus()
        manager = bus.get("org.freedesktop.systemd1", "/org/freedesktop/systemd1")
        return manager, bus

    def _packagekit_available(self) -> bool:
        try:
            self._system_bus().get("org.freedesktop.PackageKit", "/org/freedesktop/PackageKit")
        except Exception:
            return False
        return True

    @staticmethod
    def _normalize_service_name(service: str) -> str:
        service = service.strip()
        if not service:
            raise ValueError("Nome do serviço não informado.")
        if "." not in service:
            service = f"{service}.service"
        return service

    @staticmethod
    def _read_dpkg_status(package: str) -> dict[str, Any]:
        status_path = Path("/var/lib/dpkg/status")
        if not status_path.exists():
            return {"installed": False, "version": ""}

        current: dict[str, str] = {}
        with status_path.open(encoding="utf-8", errors="replace") as handle:
            for raw_line in handle:
                line = raw_line.rstrip("\n")
                if not line:
                    if current.get("Package") == package:
                        status = current.get("Status", "")
                        return {
                            "installed": "install ok installed" in status,
                            "version": current.get("Version", ""),
                        }
                    current = {}
                    continue
                if ":" in line and not line.startswith(" "):
                    key, value = line.split(":", 1)
                    current[key] = value.strip()

        if current.get("Package") == package:
            status = current.get("Status", "")
            return {"installed": "install ok installed" in status, "version": current.get("Version", "")}
        return {"installed": False, "version": ""}
