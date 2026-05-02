"""
Ferramenta read-only de observabilidade de recursos.

Usa psutil apenas para leitura do estado atual da máquina. Nenhuma função deste
módulo altera configuração, processo, arquivo ou serviço do sistema.
"""

from __future__ import annotations

import contextlib
import json
import os
from datetime import UTC, datetime
from typing import Any

import psutil


class ResourceMonitorTool:
    """Tool LangGraph read-only para snapshot de CPU, RAM, disco e rede."""

    name = "resource_snapshot"
    description = "Lê uso atual de CPU, RAM, IOPS de disco e rede em JSON estruturado."
    read_only = True

    def run(self) -> dict[str, Any]:
        """Retorna um snapshot estruturado do uso de recursos."""
        disk_io = psutil.disk_io_counters()
        net_io = psutil.net_io_counters()
        memory = psutil.virtual_memory()

        load_avg: list[float] = []
        with contextlib.suppress(OSError, AttributeError):
            load_avg = [float(value) for value in os.getloadavg()]

        return {
            "tool": self.name,
            "read_only": True,
            "timestamp": datetime.now(UTC).isoformat(),
            "cpu": {
                "percent": float(psutil.cpu_percent(interval=0.0)),
                "count_logical": psutil.cpu_count(logical=True),
                "count_physical": psutil.cpu_count(logical=False),
                "load_average": load_avg,
            },
            "memory": {
                "total_bytes": int(memory.total),
                "available_bytes": int(memory.available),
                "used_bytes": int(memory.used),
                "percent": float(memory.percent),
            },
            "disk_io": self._counter_payload(
                disk_io,
                [
                    "read_count",
                    "write_count",
                    "read_bytes",
                    "write_bytes",
                    "read_time",
                    "write_time",
                    "busy_time",
                ],
            ),
            "network": self._counter_payload(
                net_io,
                [
                    "bytes_sent",
                    "bytes_recv",
                    "packets_sent",
                    "packets_recv",
                    "errin",
                    "errout",
                    "dropin",
                    "dropout",
                ],
            ),
        }

    def run_json(self) -> str:
        """Retorna o snapshot em JSON estável para prompt/logs."""
        return json.dumps(self.run(), ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _counter_payload(counter: Any, fields: list[str]) -> dict[str, int | None]:
        if counter is None:
            return {field: None for field in fields}
        return {field: int(getattr(counter, field, 0)) for field in fields}
