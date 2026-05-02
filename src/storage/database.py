"""
Ubuntu Agent - Módulo de persistência (SQLite).

Gerencia o banco de dados de histórico de comandos executados,
fornecendo contexto conversacional para o LLM.
"""

import json
import os
import re
import sqlite3
from datetime import datetime
from typing import Any


class Database:
    """Gerenciador do banco SQLite para histórico de comandos."""

    def __init__(self, db_path: str = "data/history.db") -> None:
        """
        Inicializa a conexão com o banco de dados.

        Args:
            db_path: Caminho relativo ou absoluto para o arquivo SQLite.
                     Use ":memory:" para banco em memória (útil para testes).
        """
        self.db_path = db_path
        self._persistent_conn: sqlite3.Connection | None = None

        # Para bancos em arquivo, garantir que o diretório existe
        if db_path != ":memory:":
            os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else "data", exist_ok=True)
        else:
            # Para :memory:, manter uma conexão persistente (cada connect() cria um DB novo)
            self._persistent_conn = sqlite3.connect(":memory:")
            self._persistent_conn.row_factory = sqlite3.Row

        self._init_db()

    def _init_db(self) -> None:
        """Cria as tabelas de histórico e memória caso não existam."""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS commands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    user_input TEXT NOT NULL,
                    llm_response TEXT,
                    extracted_command TEXT,
                    stdout TEXT,
                    stderr TEXT,
                    exit_code INTEGER,
                    confirmed INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT,
                    importance INTEGER DEFAULT 1
                )
            """)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        """Retorna uma conexão com o banco."""
        if self._persistent_conn is not None:
            return self._persistent_conn
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def save_command(
        self,
        user_input: str,
        llm_response: str | None = None,
        extracted_command: str | None = None,
        stdout: str | None = None,
        stderr: str | None = None,
        exit_code: int | None = None,
        confirmed: bool = False,
    ) -> int:
        """
        Salva um registro de comando no histórico.

        Args:
            user_input: Texto original digitado pelo usuário.
            llm_response: Resposta bruta do LLM.
            extracted_command: Comando Bash extraído da resposta.
            stdout: Saída padrão da execução.
            stderr: Saída de erro da execução.
            exit_code: Código de saída do processo.
            confirmed: Se o usuário confirmou a execução.

        Returns:
            ID do registro inserido.
        """
        timestamp = datetime.now().isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO commands
                    (timestamp, user_input, llm_response, extracted_command,
                     stdout, stderr, exit_code, confirmed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp,
                    user_input,
                    llm_response,
                    extracted_command,
                    stdout,
                    stderr,
                    exit_code,
                    int(confirmed),
                ),
            )
            conn.commit()
            return cursor.lastrowid  # type: ignore[return-value]

    def get_last_n(self, n: int = 5) -> list[dict]:
        """
        Recupera os últimos N comandos do histórico.

        Args:
            n: Número de registros a retornar.

        Returns:
            Lista de dicionários com os dados de cada comando.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT user_input, extracted_command, stdout, stderr, exit_code
                FROM commands
                ORDER BY id DESC
                LIMIT ?
                """,
                (n,),
            ).fetchall()

        # Retorna em ordem cronológica (mais antigo primeiro)
        return [dict(row) for row in reversed(rows)]

    def clear_history(self) -> int:
        """
        Limpa todo o histórico de comandos.

        Returns:
            Número de registros removidos.
        """
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM commands")
            conn.commit()
            return cursor.rowcount

    def save_memory(
        self,
        kind: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        importance: int = 1,
    ) -> int:
        """
        Salva um item de memória operacional de curto/médio prazo.

        Args:
            kind: Tipo semântico da memória (ex: package, service, interaction).
            content: Texto conciso que será reinjetado no prompt.
            metadata: Dados auxiliares serializados em JSON.
            importance: Peso simples para priorizar lembranças.

        Returns:
            ID do item inserido.
        """
        timestamp = datetime.now().isoformat()
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO memory_items (timestamp, kind, content, metadata, importance)
                VALUES (?, ?, ?, ?, ?)
                """,
                (timestamp, kind, content, metadata_json, importance),
            )
            conn.commit()
            return cursor.lastrowid  # type: ignore[return-value]

    def get_recent_memories(self, limit: int = 8) -> list[dict]:
        """
        Recupera memórias recentes priorizando importância e recência.

        Args:
            limit: Número máximo de itens.

        Returns:
            Lista em ordem cronológica para leitura natural no prompt.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT timestamp, kind, content, metadata, importance
                FROM memory_items
                ORDER BY importance DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        memories = []
        for row in reversed(rows):
            item = dict(row)
            try:
                item["metadata"] = json.loads(item.get("metadata") or "{}")
            except json.JSONDecodeError:
                item["metadata"] = {}
            memories.append(item)
        return memories

    def clear_memory(self) -> int:
        """
        Limpa a memória operacional.

        Returns:
            Número de registros removidos.
        """
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM memory_items")
            conn.commit()
            return cursor.rowcount

    def remember_interaction(
        self,
        user_input: str,
        extracted_command: str | None = None,
        stdout: str | None = None,
        stderr: str | None = None,
        exit_code: int | None = None,
        confirmed: bool = False,
    ) -> int | None:
        """
        Gera uma lembrança curta a partir de uma interação bem-sucedida.

        A heurística é propositalmente conservadora e local: registra fatos úteis
        como instalações, ações em serviços e comandos confirmados recentes.
        """
        if exit_code not in (0, None):
            return None

        command = extracted_command or ""
        combined = f"{user_input}\n{command}".strip()
        if not combined:
            return None

        package = self._extract_installed_package(command)
        if package:
            return self.save_memory(
                "package",
                f"O usuário instalou ou solicitou instalação de {package}.",
                {
                    "package": package,
                    "command": command,
                    "stdout": (stdout or "")[:300],
                },
                importance=4,
            )

        service = self._extract_service_name(command)
        if service:
            return self.save_memory(
                "service",
                f"Interação recente envolveu o serviço {service}.",
                {"service": service, "command": command, "stderr": (stderr or "")[:300]},
                importance=3,
            )

        if confirmed or command.startswith("native:"):
            summary = combined.replace("\n", " -> ")
            return self.save_memory(
                "interaction",
                f"Interação recente: {summary[:220]}",
                {"command": command, "confirmed": confirmed},
                importance=1,
            )

        return None

    @staticmethod
    def _extract_installed_package(command: str) -> str:
        patterns = [
            r"\bapt(?:-get)?\s+install\s+-?y?\s*([a-zA-Z0-9_.:+-]+)",
            r"\bsnap\s+install\s+([a-zA-Z0-9_.:+-]+)",
            r"\bflatpak\s+install\s+(?:-y\s+)?(?:\S+\s+)?([a-zA-Z0-9_.:+-]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, command)
            if match:
                return match.group(1)
        return ""

    @staticmethod
    def _extract_service_name(command: str) -> str:
        match = re.search(r"\bsystemctl\s+(?:status|start|stop|restart|reload)\s+([a-zA-Z0-9_.@+-]+)", command)
        if match:
            return match.group(1)
        if command.startswith("native:dbus_native."):
            service_match = re.search(r'"service":\s*"([^"]+)"', command)
            if service_match:
                return service_match.group(1)
        return ""
