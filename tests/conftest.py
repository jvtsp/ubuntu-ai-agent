"""
Fixtures compartilhadas para os testes do Ubuntu Agent.
"""

import os
import sys
from unittest.mock import MagicMock

import pytest

# Garantir que o diretório raiz do projeto está no path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)


@pytest.fixture
def security_config():
    """Configuração de segurança padrão para testes."""
    return {
        "blocked_patterns": [
            r"rm\s+-rf\s+/",
            r"rm\s+-rf\s+~",
            r"mkfs\.",
            r"dd\s+if=.+of=/dev/",
            r":\(\)\{\s*:\|:\&\s*\};:",
            r"curl\s+.+\|\s*(ba)?sh",
            r"wget\s+.+\|\s*(ba)?sh",
            r"chmod\s+-R\s+777",
            r"chmod\s+777\s+/",
            r">\s*/dev/sd",
            r"/etc/fstab",
            r"/boot/grub",
        ],
        "require_confirmation_for": [
            "sudo",
            "apt install",
            "apt remove",
            "rm",
            "systemctl",
            "chmod",
            "chown",
        ],
    }


@pytest.fixture
def default_config(security_config):
    """Configuração completa padrão para testes."""
    return {
        "llm": {
            "base_url": "http://localhost:11434/v1",
            "model": "qwen2.5-coder:3b",
            "api_key": "not-needed",
            "temperature": 0.1,
            "timeout": 30,
        },
        "ui": {
            "hotkey": "super+space",
            "theme": "dark",
            "width": 700,
        },
        "security": security_config,
        "history": {
            "max_context_messages": 5,
            "db_path": ":memory:",
        },
        "logging": {
            "level": "WARNING",
        },
        "agent": {
            "max_retries": 2,
        },
    }


@pytest.fixture
def db_in_memory():
    """Banco de dados SQLite in-memory para testes."""
    from src.storage.database import Database

    return Database(":memory:")


@pytest.fixture
def mock_llm_client():
    """Mock do cliente LLM."""
    client = MagicMock()
    client.base_url = "http://localhost:11434/v1"
    client.model = "qwen2.5-coder:3b"
    client.invoke.return_value = "```bash\nls -la\n```"
    client.health_check.return_value = True
    client.list_models.return_value = [
        {"name": "qwen2.5-coder:3b", "size": "1.9 GB"},
    ]
    return client


@pytest.fixture
def mock_vault():
    """Mock do Vault."""
    from src.storage.vault import Vault

    vault = Vault()
    return vault


@pytest.fixture
def system_context():
    """Contexto de sistema mockado para testes."""
    return {
        "username": "testuser",
        "hostname": "testhost",
        "home": "/home/testuser",
        "desktop": "/home/testuser/Área de Trabalho",
        "documents": "/home/testuser/Documentos",
        "downloads": "/home/testuser/Downloads",
        "music": "/home/testuser/Músicas",
        "pictures": "/home/testuser/Imagens",
        "videos": "/home/testuser/Vídeos",
        "os_version": "Ubuntu 24.04 LTS",
        "kernel": "6.8.0-generic",
        "arch": "x86_64",
        "locale": "pt_BR.UTF-8",
        "shell": "/bin/bash",
        "terminal_emulators": ["gnome-terminal", "x-terminal-emulator"],
        "terminal_command": "gnome-terminal",
    }
