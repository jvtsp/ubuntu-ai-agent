"""
Ubuntu Agent - Sistema de logging centralizado.

Configura loggers com rotação de arquivos para diagnóstico e auditoria.
Os logs são salvos em data/logs/ com rotação diária e retenção de 30 dias.
"""

import logging
import os
from logging.handlers import TimedRotatingFileHandler

# Diretório de logs (relativo à raiz do projeto)
_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(_ROOT_DIR, "data", "logs")


def _ensure_logs_dir() -> None:
    """Cria o diretório de logs se não existir."""
    os.makedirs(LOGS_DIR, exist_ok=True)


def setup_logging(level: str = "DEBUG") -> logging.Logger:
    """
    Configura e retorna o logger raiz do Ubuntu Agent.

    Cria três handlers:
    - agent.log: Log completo do agente (DEBUG+)
    - errors.log: Apenas erros e exceções (ERROR+)
    - Console: Info e acima para o terminal

    Args:
        level: Nível de log mínimo (DEBUG, INFO, WARNING, ERROR).

    Returns:
        Logger configurado.
    """
    _ensure_logs_dir()

    logger = logging.getLogger("ubuntu_agent")
    logger.setLevel(getattr(logging, level.upper(), logging.DEBUG))

    # Evitar duplicação se chamado múltiplas vezes
    if logger.handlers:
        return logger

    # ─── Formato ─────────────────────────────────────────────────────────────
    detailed_fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)-8s] [%(name)s.%(funcName)s:%(lineno)d] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    simple_fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)-8s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # ─── Handler 1: agent.log (tudo, com rotação diária) ────────────────────
    agent_log_path = os.path.join(LOGS_DIR, "agent.log")
    agent_handler = TimedRotatingFileHandler(
        agent_log_path,
        when="midnight",
        interval=1,
        backupCount=30,  # Manter 30 dias
        encoding="utf-8",
    )
    agent_handler.setLevel(logging.DEBUG)
    agent_handler.setFormatter(detailed_fmt)
    agent_handler.suffix = "%Y-%m-%d"
    logger.addHandler(agent_handler)

    # ─── Handler 2: errors.log (apenas erros) ───────────────────────────────
    error_log_path = os.path.join(LOGS_DIR, "errors.log")
    error_handler = TimedRotatingFileHandler(
        error_log_path,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(detailed_fmt)
    error_handler.suffix = "%Y-%m-%d"
    logger.addHandler(error_handler)

    # ─── Handler 3: Console ─────────────────────────────────────────────────
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(simple_fmt)
    logger.addHandler(console_handler)

    logger.info("Sistema de logging inicializado. Logs em: %s", LOGS_DIR)

    return logger


def get_logger(name: str) -> logging.Logger:
    """
    Retorna um logger filho com o nome do módulo.

    Args:
        name: Nome do módulo (ex: 'ui.app', 'agent.graph').

    Returns:
        Logger filho do logger raiz.
    """
    return logging.getLogger(f"ubuntu_agent.{name}")
