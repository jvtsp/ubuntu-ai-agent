"""
Ubuntu Agent - Coleta de contexto do sistema.

Coleta informações do ambiente do usuário (diretórios, locale, hardware)
para que o LLM gere comandos precisos para esta máquina específica.
"""

import os
import subprocess
from src.logger import get_logger

log = get_logger("system.context")


def _run_quiet(cmd: str, default: str = "") -> str:
    """Executa um comando e retorna a saída, ou default se falhar."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() if result.returncode == 0 else default
    except Exception:
        return default


def collect_system_context() -> dict:
    """
    Coleta informações do sistema operacional e do usuário.

    Returns:
        Dicionário com informações do sistema.
    """
    ctx = {}

    # Usuário e máquina
    ctx["username"] = os.environ.get("USER", _run_quiet("whoami", "user"))
    ctx["hostname"] = _run_quiet("hostname", "localhost")
    ctx["home"] = os.path.expanduser("~")

    # Diretórios XDG (respeitam locale)
    ctx["desktop"] = _run_quiet("xdg-user-dir DESKTOP", os.path.join(ctx["home"], "Desktop"))
    ctx["documents"] = _run_quiet("xdg-user-dir DOCUMENTS", os.path.join(ctx["home"], "Documents"))
    ctx["downloads"] = _run_quiet("xdg-user-dir DOWNLOAD", os.path.join(ctx["home"], "Downloads"))
    ctx["music"] = _run_quiet("xdg-user-dir MUSIC", os.path.join(ctx["home"], "Music"))
    ctx["pictures"] = _run_quiet("xdg-user-dir PICTURES", os.path.join(ctx["home"], "Pictures"))
    ctx["videos"] = _run_quiet("xdg-user-dir VIDEOS", os.path.join(ctx["home"], "Videos"))

    # Sistema
    ctx["os_version"] = _run_quiet("lsb_release -d -s 2>/dev/null || cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2", "Ubuntu")
    ctx["kernel"] = _run_quiet("uname -r", "")
    ctx["arch"] = _run_quiet("uname -m", "x86_64")
    ctx["locale"] = os.environ.get("LANG", "en_US.UTF-8")
    ctx["shell"] = os.environ.get("SHELL", "/bin/bash")

    log.info("Contexto do sistema coletado: user=%s, desktop=%s, locale=%s", 
             ctx["username"], ctx["desktop"], ctx["locale"])

    return ctx


def format_system_context(ctx: dict) -> str:
    """
    Formata o contexto do sistema para inclusão no prompt do LLM.

    O formato usa mapeamentos genéricos que funcionam para qualquer usuário.
    Os valores são coletados em tempo de execução na máquina do usuário.

    Args:
        ctx: Dicionário retornado por collect_system_context().

    Returns:
        String formatada para o prompt.
    """
    return (
        f"AMBIENTE DA MÁQUINA DO USUÁRIO:\n"
        f"- SO: {ctx['os_version']} ({ctx['arch']})\n"
        f"- Locale: {ctx['locale']}\n"
        f"- Shell: {ctx['shell']}\n"
        f"\n"
        f"VARIÁVEIS DE AMBIENTE DISPONÍVEIS (o sistema as define automaticamente):\n"
        f"- $DESKTOP = \"{ctx['desktop']}\"\n"
        f"- $DOCUMENTS = \"{ctx['documents']}\"\n"
        f"- $DOWNLOADS = \"{ctx['downloads']}\"\n"
        f"- $MUSIC = \"{ctx['music']}\"\n"
        f"- $PICTURES = \"{ctx['pictures']}\"\n"
        f"- $VIDEOS = \"{ctx['videos']}\"\n"
        f"\n"
        f"REGRA OBRIGATÓRIA: Sempre use essas variáveis nos comandos.\n"
        f"Exemplos:\n"
        f"  touch \"$DESKTOP/arquivo.txt\" (NÃO use ~/Área de Trabalho/)\n"
        f"  cp foto.jpg \"$PICTURES/\" (NÃO use ~/Imagens/)\n"
        f"  ls \"$DOWNLOADS\" (NÃO use ~/Downloads/)"
    )
