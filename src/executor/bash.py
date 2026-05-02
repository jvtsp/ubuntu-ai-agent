"""
Ubuntu Agent - Extração e execução de comandos Bash.

Extrai comandos dos blocos de código markdown retornados pelo LLM
e os executa via subprocess com captura de output e timeout.
"""

import os
import re
import subprocess
from dataclasses import dataclass

from src.logger import get_logger

log = get_logger("executor.bash")


def _xdg_dir(name: str) -> str:
    """Resolve um diretório XDG (DESKTOP, DOCUMENTS, etc.) via xdg-user-dir."""
    import contextlib
    import os

    with contextlib.suppress(Exception):
        result = subprocess.run(["xdg-user-dir", name], capture_output=True, text=True, timeout=3)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    return os.path.expanduser("~")


def _sanitize_paths(command: str) -> str:
    """
    Substitui padrões comuns de caminhos XDG por variáveis de ambiente.
    Previne erros de capitalização (Trabalho vs trabalho, etc.).
    """
    # Mapeamento de padrões → variáveis
    replacements = [
        # "Área de Trabalho" / "Área de trabalho" / "Area de Trabalho" (qualquer capitalização)
        (re.compile(r"~/[ÁáAa]rea[\\ ]+de[\\ ]+[Tt]rabalho", re.IGNORECASE), '"$DESKTOP"'),
        (re.compile(r"\$HOME/[ÁáAa]rea[\\ ]+de[\\ ]+[Tt]rabalho", re.IGNORECASE), '"$DESKTOP"'),
        # Desktop (locale en_US)
        (re.compile(r"~/Desktop\b"), '"$DESKTOP"'),
        # Documentos / Documents
        (re.compile(r"~/Documentos\b", re.IGNORECASE), '"$DOCUMENTS"'),
        (re.compile(r"~/Documents\b"), '"$DOCUMENTS"'),
        # Downloads
        (re.compile(r"~/Downloads\b", re.IGNORECASE), '"$DOWNLOADS"'),
        # Músicas / Musicas / Music
        (re.compile(r"~/M[úu]sicas?\b", re.IGNORECASE), '"$MUSIC"'),
        (re.compile(r"~/Music\b"), '"$MUSIC"'),
        # Imagens / Pictures
        (re.compile(r"~/Imagens\b", re.IGNORECASE), '"$PICTURES"'),
        (re.compile(r"~/Pictures\b"), '"$PICTURES"'),
        # Vídeos / Videos
        (re.compile(r"~/V[íi]deos\b", re.IGNORECASE), '"$VIDEOS"'),
        (re.compile(r"~/Videos\b"), '"$VIDEOS"'),
    ]

    original = command
    for pattern, replacement in replacements:
        command = pattern.sub(replacement, command)

    if command != original:
        log.debug("Path sanitizado: '%s' → '%s'", original[:100], command[:100])

    return command


# Padrão regex para blocos ```bash ... ```
BASH_BLOCK_PATTERN = re.compile(
    r"```(?:bash|sh|shell)?\s*\n(.*?)```",
    re.DOTALL | re.IGNORECASE,
)

# Padrão fallback: linhas que parecem comandos (começam com $ ou não são texto puro)
COMMAND_LINE_PATTERN = re.compile(
    r"^\$?\s*((?:sudo\s+)?(?:apt|apt-get|snap|flatpak|pip|npm|"
    r"ls|cat|grep|find|mkdir|cp|mv|rm|chmod|chown|touch|echo|"
    r"cd|pwd|df|free|top|ps|kill|systemctl|journalctl|"
    r"curl|wget|git|docker|python3?|bash|sh|nohup|"
    r"sed|awk|tar|zip|unzip|gzip|ssh|scp|rsync|"
    r"dpkg|ufw|iptables|mount|umount|fdisk|lsblk|"
    r"useradd|userdel|groupadd|passwd|crontab|"
    r"nano|vim|vi|code|gedit|xdg-open)\b.*)",
    re.MULTILINE | re.IGNORECASE,
)

# Aplicativos gráficos conhecidos
GRAPHICAL_APPS = {
    "nautilus",
    "firefox",
    "google-chrome",
    "chromium",
    "code",
    "gedit",
    "gnome-text-editor",
    "eog",
    "evince",
    "totem",
    "rhythmbox",
    "shotwell",
    "gimp",
    "inkscape",
    "libreoffice",
    "thunderbird",
    "vlc",
    "mpv",
    "xdg-open",
    "gnome-terminal",
    "gnome-calculator",
    "gnome-system-monitor",
    "gnome-disks",
    "gnome-control-center",
    "gnome-tweaks",
    "gnome-software",
    "transmission-gtk",
    "blender",
    "obs-studio",
    "kdenlive",
    "telegram-desktop",
    "discord",
    "slack",
    "spotify",
    "nemo",
    "thunar",
    "dolphin",
    "kate",
    "okular",
}


@dataclass
class ExtractionResult:
    """Resultado da extração de comando."""

    success: bool
    command: str = ""
    is_error_response: bool = False
    error_message: str = ""


@dataclass
class ExecutionResult:
    """Resultado da execução de um comando."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    timed_out: bool = False
    error_message: str = ""


def extract_command(llm_response: str) -> ExtractionResult:
    """
    Extrai o comando Bash da resposta do LLM.

    Tenta primeiro extrair de blocos ```bash```, depois usa fallback
    para linhas que parecem comandos.

    Args:
        llm_response: Resposta bruta do LLM.

    Returns:
        ExtractionResult com o comando extraído ou mensagem de erro.
    """
    if not llm_response or not llm_response.strip():
        return ExtractionResult(
            success=False,
            error_message="Resposta do LLM está vazia.",
        )

    # 1. Tentar extrair de bloco ```bash```
    matches = BASH_BLOCK_PATTERN.findall(llm_response)
    if matches:
        command = matches[0].strip()

        # Verificar se é uma resposta de erro do LLM
        if command.startswith("# ERRO:"):
            return ExtractionResult(
                success=False,
                is_error_response=True,
                error_message=command.replace("# ERRO:", "").strip(),
            )

        if command:
            return ExtractionResult(success=True, command=command)

    # 2. Fallback: procurar linhas que parecem comandos
    fallback_matches = COMMAND_LINE_PATTERN.findall(llm_response)
    if fallback_matches:
        command = fallback_matches[0].strip()
        if command:
            return ExtractionResult(success=True, command=command)

    # 3. Nada encontrado
    return ExtractionResult(
        success=False,
        error_message="Não foi possível extrair um comando da resposta do LLM.",
    )


def _should_wrap_graphical(command: str) -> bool:
    """
    Verifica se o comando inicia um aplicativo gráfico que deve ser
    envolvido com nohup para não bloquear o terminal.

    Args:
        command: Comando Bash.

    Returns:
        True se o comando deve ser envolvido com nohup.
    """
    # Se já tem nohup, não precisa envolver
    if "nohup" in command:
        return False

    # Pega o primeiro token (pode ter sudo antes)
    tokens = command.strip().split()
    if not tokens:
        return False

    base_cmd = tokens[0]
    if base_cmd == "sudo" and len(tokens) > 1:
        base_cmd = tokens[1]

    # Remove path completo
    base_cmd = base_cmd.split("/")[-1]

    return base_cmd in GRAPHICAL_APPS


def execute_command(
    command: str,
    timeout: int = 60,
    working_dir: str | None = None,
    vault=None,
) -> ExecutionResult:
    """
    Executa um comando Bash via subprocess.

    Args:
        command: Comando Bash a ser executado.
        timeout: Timeout em segundos (padrão: 60).
        working_dir: Diretório de trabalho (padrão: home do usuário).

    Returns:
        ExecutionResult com stdout, stderr, exit_code e status de timeout.
    """
    if not command or not command.strip():
        return ExecutionResult(
            exit_code=-1,
            error_message="Comando vazio.",
        )

    # Sanitizar paths XDG (corrige capitalização e usa variáveis de ambiente)
    command = _sanitize_paths(command)

    import shutil

    bwrap_path = shutil.which("bwrap")
    is_graphical = _should_wrap_graphical(command)
    has_sudo = "sudo" in command.lower()

    # Verificar se AppArmor está bloqueando userns (padrão no Ubuntu 24.04)
    apparmor_blocks_userns = False
    if bwrap_path:
        import contextlib

        with contextlib.suppress(Exception), open("/proc/sys/kernel/apparmor_restrict_unprivileged_userns") as f:
            apparmor_blocks_userns = f.read().strip() == "1"

    # Envolver aplicativos gráficos com nohup
    if is_graphical:
        command = f"nohup {command} > /dev/null 2>&1 &"
        log.debug("Comando envolvido com nohup para app gráfico.")

    # Comando base usando bash
    cmd_args = ["bash", "-c", command]

    # Aplicar sandbox se bwrap disponível, não for app gráfico, não usar sudo e AppArmor permitir
    if bwrap_path and not is_graphical and not has_sudo and not apparmor_blocks_userns:
        log.info("Aplicando sandbox bwrap ao comando.")
        home_dir = os.path.expanduser("~")
        cmd_args = [
            bwrap_path,
            "--ro-bind",
            "/usr",
            "/usr",
            "--ro-bind",
            "/bin",
            "/bin",
            "--ro-bind",
            "/lib",
            "/lib",
            "--ro-bind",
            "/etc",
            "/etc",
            "--dev",
            "/dev",
            "--proc",
            "/proc",
            "--bind",
            "/tmp",
            "/tmp",  # noqa: S108
            "--bind",
            home_dir,
            home_dir,
            "--die-with-parent",
            "--",
            *cmd_args,
        ]
    elif bwrap_path and apparmor_blocks_userns and not is_graphical and not has_sudo:
        log.debug("Bwrap skipado: bloqueado pelo AppArmor restritivo no Ubuntu 24.04.")
    elif bwrap_path and has_sudo:
        log.debug("Bwrap skipado: comando requer sudo.")

    # Diretório de trabalho padrão: home do usuário
    cwd = working_dir or os.path.expanduser("~")

    # Injetar sudo password se necessário
    stdin_data = None
    if vault and has_sudo:
        password = vault.get_sudo_password()
        if password:
            # Substituir sudo por sudo -S para forçar a leitura do stdin
            command_with_sudo_s = re.sub(r"\bsudo\b", "sudo -S", command, flags=re.IGNORECASE)
            cmd_args[-1] = command_with_sudo_s  # Atualiza o script no comando bash -c
            stdin_data = password + "\n"
            log.info("Senha sudo injetada via vault.")

    log.info("Executando: '%s' em '%s'", command[:200], cwd)

    # Preparar variáveis de ambiente com diretórios XDG
    env = os.environ.copy()
    env["DESKTOP"] = _xdg_dir("DESKTOP")
    env["DOCUMENTS"] = _xdg_dir("DOCUMENTS")
    env["DOWNLOADS"] = _xdg_dir("DOWNLOAD")
    env["MUSIC"] = _xdg_dir("MUSIC")
    env["PICTURES"] = _xdg_dir("PICTURES")
    env["VIDEOS"] = _xdg_dir("VIDEOS")

    try:
        # Usando a lista de argumentos construída (bwrap ou bash -c)
        result = subprocess.run(
            cmd_args,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            input=stdin_data,
            env=env,
        )
        return ExecutionResult(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.returncode,
        )

    except subprocess.TimeoutExpired:
        log.warning("Comando excedeu timeout de %ds: %s", timeout, command[:100])
        return ExecutionResult(
            exit_code=-1,
            timed_out=True,
            error_message=f"Comando excedeu o timeout de {timeout}s.",
        )
    except OSError as e:
        log.exception("Erro de OS ao executar comando: %s", command[:100])
        return ExecutionResult(
            exit_code=-1,
            error_message=f"Erro ao executar comando: {e}",
        )
