"""
Ubuntu Agent - Módulo de persistência (SQLite).

Gerencia o banco de dados de histórico de comandos executados,
fornecendo contexto conversacional para o LLM.
"""

import os
import sqlite3
from datetime import datetime


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
        """Cria a tabela de comandos caso não exista."""
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
