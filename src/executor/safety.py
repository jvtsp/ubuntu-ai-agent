"""
Ubuntu Agent - Validação de segurança de comandos.

Implementa a blocklist de padrões perigosos e a categorização de comandos
em read-only, requer-confirmação ou bloqueado.
"""

import re
from dataclasses import dataclass
from enum import Enum


class CommandCategory(Enum):
    """Categorias de segurança para comandos."""

    READ_ONLY = "read_only"
    NEEDS_CONFIRMATION = "needs_confirmation"
    BLOCKED = "blocked"


@dataclass
class SafetyResult:
    """Resultado da validação de segurança."""

    category: CommandCategory
    is_safe: bool
    reason: str = ""
    matched_pattern: str = ""


# Comandos considerados seguros (read-only)
READ_ONLY_COMMANDS = {
    "ls",
    "cat",
    "grep",
    "find",
    "df",
    "free",
    "top",
    "htop",
    "ps",
    "whoami",
    "hostname",
    "uname",
    "date",
    "cal",
    "uptime",
    "head",
    "tail",
    "wc",
    "sort",
    "uniq",
    "diff",
    "file",
    "which",
    "whereis",
    "type",
    "echo",
    "pwd",
    "id",
    "groups",
    "env",
    "printenv",
    "locale",
    "lsb_release",
    "lscpu",
    "lsmem",
    "lsblk",
    "lsusb",
    "lspci",
    "ip",
    "ifconfig",
    "ping",
    "dig",
    "nslookup",
    "traceroute",
    "ss",
    "netstat",
    "du",
    "stat",
    "tree",
    "man",
    "help",
    "info",
    "apt list",
    "apt show",
    "apt search",
    "dpkg -l",
    "snap list",
    "flatpak list",
    "systemctl status",
    "journalctl",
    "dmesg",
    "sensors",
    "inxi",
    "gnome-terminal",
    "x-terminal-emulator",
    "konsole",
    "xfce4-terminal",
    "terminator",
    "alacritty",
    "kitty",
    "xterm",
}


class SecurityValidator:
    """Validador de segurança para comandos Bash."""

    def __init__(self, config: dict) -> None:
        """
        Inicializa o validador com as configurações de segurança.

        Args:
            config: Dicionário com chaves 'blocked_patterns' e 'require_confirmation_for'.
        """
        raw_patterns = config.get("blocked_patterns", [])
        self.blocked_patterns: list[re.Pattern] = []
        import contextlib

        for pattern in raw_patterns:
            with contextlib.suppress(re.error):
                self.blocked_patterns.append(re.compile(pattern, re.IGNORECASE))

        self.confirmation_keywords: list[str] = config.get("require_confirmation_for", [])

    def validate(self, command: str) -> SafetyResult:
        """
        Valida um comando contra a blocklist e regras de confirmação.

        Args:
            command: Comando Bash a ser validado.

        Returns:
            SafetyResult com a categoria, se é seguro, e o motivo.
        """
        # 1. Verificar contra padrões bloqueados
        for pattern in self.blocked_patterns:
            if pattern.search(command):
                return SafetyResult(
                    category=CommandCategory.BLOCKED,
                    is_safe=False,
                    reason=f"Comando corresponde a padrão perigoso: {pattern.pattern}",
                    matched_pattern=pattern.pattern,
                )

        # 1.5 Verificar evasões com subshells ou backticks
        if "`" in command or "$(" in command:
            return SafetyResult(
                category=CommandCategory.BLOCKED,
                is_safe=False,
                reason="Uso de subshells ou backticks bloqueado para evitar evasões de segurança.",
                matched_pattern="subshell_or_backtick",
            )

        # 2. Verificar se é read-only
        if self._is_read_only(command):
            return SafetyResult(
                category=CommandCategory.READ_ONLY,
                is_safe=True,
                reason="Comando classificado como somente leitura.",
            )

        # 3. Verificar se requer confirmação
        for keyword in self.confirmation_keywords:
            # Usar regex com limitadores de palavra para evitar falsos positivos
            # ex: 'rm' não deve dar match em 'gnome-terminal'
            kw_pattern = rf"\b{re.escape(keyword)}\b"
            if re.search(kw_pattern, command, re.IGNORECASE):
                return SafetyResult(
                    category=CommandCategory.NEEDS_CONFIRMATION,
                    is_safe=True,
                    reason=f"Comando contém '{keyword}' e requer confirmação do usuário.",
                )

        # 4. Comandos não reconhecidos requerem confirmação por precaução
        return SafetyResult(
            category=CommandCategory.NEEDS_CONFIRMATION,
            is_safe=True,
            reason="Comando não classificado como somente leitura. Confirmação requerida.",
        )

    def _is_read_only(self, command: str) -> bool:
        """
        Verifica se o comando é somente leitura.

        Analisa o primeiro token (o comando base) e verifica
        se ele está na lista de comandos seguros.

        Args:
            command: Comando Bash completo.

        Returns:
            True se o comando for considerado somente leitura.
        """
        # Remove pipes e analisa o primeiro comando
        # Para comandos encadeados com &&, verifica cada um
        parts = re.split(r"\s*&&\s*|\s*\|\|\s*", command)

        for part in parts:
            part = part.strip()
            if not part:
                continue

            # Ignora redirecionamentos de output no início
            # Pega o primeiro "token real"
            tokens = part.split()
            if not tokens:
                continue

            # O primeiro token pode ser um path completo
            base_cmd = tokens[0].split("/")[-1]

            # Verifica se está na lista de read-only
            # Também verifica combinações com o segundo token (ex: "apt list")
            if base_cmd in READ_ONLY_COMMANDS:
                continue
            if len(tokens) >= 2:
                combined = f"{base_cmd} {tokens[1]}"
                if combined in READ_ONLY_COMMANDS:
                    continue

            # Se qualquer parte não for read-only, o comando todo não é
            return False

        return True
