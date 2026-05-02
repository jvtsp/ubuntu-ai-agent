"""
Testes para o módulo de contexto do sistema (system/context.py).
"""

from unittest.mock import MagicMock, patch

from src.system.context import collect_system_context, format_system_context


class TestCollectSystemContext:
    @patch("src.system.context.subprocess.run")
    @patch.dict("os.environ", {"USER": "testuser", "LANG": "pt_BR.UTF-8", "SHELL": "/bin/bash"})
    def test_collects_basic_info(self, mock_run):
        """Deve coletar informações básicas do sistema."""
        mock_run.return_value = MagicMock(returncode=0, stdout="mock_value\n")
        ctx = collect_system_context()
        assert ctx["username"] == "testuser"
        assert ctx["locale"] == "pt_BR.UTF-8"
        assert ctx["shell"] == "/bin/bash"
        assert "home" in ctx

    @patch("src.system.context.subprocess.run")
    def test_collects_xdg_dirs(self, mock_run):
        """Deve coletar diretórios XDG."""
        mock_run.return_value = MagicMock(returncode=0, stdout="/home/u/Desktop\n")
        ctx = collect_system_context()
        for key in ["desktop", "documents", "downloads", "music", "pictures", "videos"]:
            assert key in ctx

    @patch("src.system.context.subprocess.run")
    def test_handles_subprocess_failure(self, mock_run):
        """Deve usar defaults quando subprocess falha."""
        mock_run.side_effect = Exception("cmd not found")
        ctx = collect_system_context()
        assert isinstance(ctx, dict)
        assert "username" in ctx

    @patch("src.system.context.shutil.which")
    def test_collects_terminal_context(self, mock_which):
        """Deve detectar emuladores de terminal disponíveis."""
        mock_which.side_effect = lambda cmd: f"/usr/bin/{cmd}" if cmd in {"x-terminal-emulator", "gnome-terminal"} else None
        ctx = collect_system_context()
        assert ctx["terminal_command"] == "gnome-terminal"
        assert "gnome-terminal" in ctx["terminal_emulators"]


class TestFormatSystemContext:
    def test_format_contains_all_fields(self, system_context):
        """Formato deve conter todas as variáveis de ambiente."""
        result = format_system_context(system_context)
        assert "$DESKTOP" in result
        assert "$DOCUMENTS" in result
        assert "$DOWNLOADS" in result
        assert "$MUSIC" in result
        assert "$PICTURES" in result
        assert "$VIDEOS" in result
        assert "Terminal padrão detectado" in result

    def test_format_contains_os_info(self, system_context):
        """Formato deve conter informações do SO."""
        result = format_system_context(system_context)
        assert "Ubuntu 24.04" in result
        assert "x86_64" in result
        assert "pt_BR" in result

    def test_format_contains_usage_examples(self, system_context):
        """Formato deve conter exemplos de uso das variáveis."""
        result = format_system_context(system_context)
        assert "touch" in result or "cp" in result or "ls" in result

    def test_format_is_string(self, system_context):
        """Formato deve retornar uma string."""
        assert isinstance(format_system_context(system_context), str)
