"""
Testes para o módulo de extração e execução (executor/bash.py).
"""

from unittest.mock import MagicMock, patch

import pytest
from src.executor.bash import (
    _sanitize_paths,
    _should_wrap_graphical,
    execute_command,
    extract_command,
)


class TestExtractCommand:
    def test_extract_from_bash_block(self):
        result = extract_command("```bash\nls -la /home\n```")
        assert result.success is True
        assert result.command == "ls -la /home"

    def test_extract_from_sh_block(self):
        result = extract_command('```sh\necho "hello"\n```')
        assert result.success is True
        assert result.command == 'echo "hello"'

    def test_extract_multiline(self):
        result = extract_command("```bash\nsudo apt update && sudo apt upgrade -y\n```")
        assert result.success is True
        assert "apt update" in result.command

    def test_extract_error_response(self):
        result = extract_command("```bash\n# ERRO: Ambígua\n```")
        assert result.success is False
        assert result.is_error_response is True

    def test_extract_empty(self):
        assert extract_command("").success is False
        assert extract_command(None).success is False  # type: ignore
        assert extract_command("   \n  ").success is False

    def test_extract_fallback(self):
        result = extract_command("Você pode rodar:\nls -la /home/user")
        assert result.success is True
        assert "ls" in result.command

    def test_extract_no_command(self):
        result = extract_command("Não entendi o pedido.")
        assert result.success is False

    def test_extract_with_surrounding_text(self):
        response = "Comando:\n\n```bash\nls -la\n```\n\nPronto."
        result = extract_command(response)
        assert result.success is True
        assert result.command == "ls -la"

    def test_extract_first_block(self):
        response = '```bash\necho "a"\n```\n```bash\necho "b"\n```'
        result = extract_command(response)
        assert result.success and "a" in result.command


class TestSanitizePaths:
    def test_area_de_trabalho(self):
        assert '"$DESKTOP"' in _sanitize_paths("touch ~/Área de Trabalho/t.txt")

    def test_desktop_en(self):
        assert '"$DESKTOP"' in _sanitize_paths("ls ~/Desktop")

    def test_documentos(self):
        assert '"$DOCUMENTS"' in _sanitize_paths("cp f ~/Documentos/")

    def test_downloads(self):
        assert '"$DOWNLOADS"' in _sanitize_paths("ls ~/Downloads")

    def test_musicas(self):
        assert '"$MUSIC"' in _sanitize_paths("cp s ~/Músicas/")

    def test_imagens(self):
        assert '"$PICTURES"' in _sanitize_paths("cp f ~/Imagens/")

    def test_videos(self):
        assert '"$VIDEOS"' in _sanitize_paths("cp v ~/Vídeos/")

    def test_no_change(self):
        assert _sanitize_paths("ls /tmp") == "ls /tmp"

    def test_case_insensitive(self):
        assert '"$DOCUMENTS"' in _sanitize_paths("ls ~/documentos")

    def test_home_var(self):
        assert '"$DESKTOP"' in _sanitize_paths("touch $HOME/Área de Trabalho/t")


class TestShouldWrapGraphical:
    @pytest.mark.parametrize("cmd", ["firefox", "nautilus", "code", "vlc", "gimp"])
    def test_detected(self, cmd):
        assert _should_wrap_graphical(cmd) is True

    def test_with_args(self):
        assert _should_wrap_graphical("firefox https://g.com") is True

    def test_sudo(self):
        assert _should_wrap_graphical("sudo nautilus /root") is True

    def test_nohup_skip(self):
        assert _should_wrap_graphical("nohup firefox &") is False

    def test_cli_not_detected(self):
        assert _should_wrap_graphical("ls -la") is False
        assert _should_wrap_graphical("apt install vim") is False

    def test_empty(self):
        assert _should_wrap_graphical("") is False


class TestExecuteCommand:
    def test_simple(self):
        r = execute_command("echo 'hello'")
        assert r.exit_code == 0 and "hello" in r.stdout

    def test_empty(self):
        r = execute_command("")
        assert r.exit_code == -1

    def test_failing(self):
        assert execute_command("false").exit_code != 0

    def test_timeout(self):
        r = execute_command("sleep 10", timeout=1)
        assert r.timed_out is True

    def test_working_dir(self):
        r = execute_command("pwd", working_dir="/tmp")  # noqa: S108
        assert r.exit_code == 0 and "/tmp" in r.stdout  # noqa: S108

    def test_xdg_env(self):
        r = execute_command('echo "$DESKTOP"')
        assert r.exit_code == 0 and r.stdout.strip() != ""

    @patch("src.executor.bash.subprocess.run")
    def test_vault_sudo(self, mock_run):
        from src.storage.vault import Vault

        vault = Vault()
        vault.set_sudo_password("pwd123")
        mock_run.return_value = MagicMock(stdout="ok", stderr="", returncode=0)
        execute_command("sudo apt update", vault=vault)
        kw = mock_run.call_args.kwargs
        assert kw.get("input") and "pwd123" in kw["input"]
