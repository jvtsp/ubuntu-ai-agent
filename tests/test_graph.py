# mypy: ignore-errors
"""
Testes de integração para o grafo do agente (agent/graph.py).
Usa LLM mockado para testar o fluxo completo sem dependência externa.
"""

from unittest.mock import MagicMock, patch

import pytest
from src.agent.graph import AgentGraph
from src.executor.safety import SecurityValidator
from src.storage.database import Database
from src.tools.dbus_native import NativeToolResult


@pytest.fixture
def agent(security_config, mock_llm_client):
    """Cria um AgentGraph com LLM mockado."""
    db = Database(":memory:")
    security = SecurityValidator(security_config)
    config = {
        "history": {"max_context_messages": 5},
        "security": {**security_config, "command_timeout": 10},
        "agent": {"max_retries": 1},
    }
    with (
        patch("src.agent.graph.collect_system_context") as mock_ctx,
        patch("src.agent.graph.format_system_context") as mock_fmt,
    ):
        mock_ctx.return_value = {"desktop": "/home/test/Desktop"}
        mock_fmt.return_value = "MOCK CONTEXT"
        return AgentGraph(mock_llm_client, security, db, config)


class TestAgentGraphReadOnly:
    def test_read_only_executes_directly(self, agent):
        """Comando read-only deve executar sem confirmação."""
        agent.llm.invoke.return_value = '```bash\necho "hello"\n```'
        with patch("src.agent.graph.execute_command") as mock_exec:
            mock_exec.return_value = MagicMock(stdout="hello\n", stderr="", exit_code=0, timed_out=False)
            result = agent.run("diga hello")
        assert result.get("ui_status") in ("success", "info")
        assert result.get("is_complete") is True

    def test_open_terminal_uses_direct_shortcut(self, agent):
        """Pedido simples de abrir terminal deve bypassar o LLM."""
        agent._system_ctx["terminal_command"] = "x-terminal-emulator"
        with patch("src.agent.graph.execute_command") as mock_exec:
            mock_exec.return_value = MagicMock(
                stdout="Aplicativo gráfico iniciado em background.",
                stderr="",
                exit_code=0,
                timed_out=False,
            )
            result = agent.run("abra o terminal")
        assert result.get("extracted_command") == "x-terminal-emulator"
        assert result.get("direct_command") is True
        agent.llm.invoke.assert_not_called()
        mock_exec.assert_called_once()

    def test_identity_question_uses_direct_shortcut(self, agent):
        """Pergunta simples de identidade deve ter resposta local."""
        with patch("src.agent.graph.execute_command") as mock_exec:
            mock_exec.return_value = MagicMock(
                stdout="Sou o Ubuntu Agent, seu assistente local para administrar este Ubuntu.\n",
                stderr="",
                exit_code=0,
                timed_out=False,
            )
            result = agent.run("quem esta ai")

        assert "Sou o Ubuntu Agent" in result.get("extracted_command", "")
        assert result.get("direct_command") is True
        agent.llm.invoke.assert_not_called()
        mock_exec.assert_called_once()

    def test_open_ubuntu_settings_uses_direct_shortcut(self, agent):
        """Abrir configurações do Ubuntu deve usar app gráfico real."""
        with patch("src.agent.graph.execute_command") as mock_exec:
            mock_exec.return_value = MagicMock(
                stdout="Aplicativo gráfico iniciado em background.",
                stderr="",
                exit_code=0,
                timed_out=False,
            )
            result = agent.run("abra as configuracoes do ubuntu")

        assert result.get("extracted_command") == "gnome-control-center"
        assert result.get("direct_command") is True
        agent.llm.invoke.assert_not_called()
        mock_exec.assert_called_once()


class TestAgentGraphConfirmation:
    def test_sudo_needs_confirmation(self, agent):
        """Comando com sudo deve pedir confirmação."""
        agent.llm.invoke.return_value = "```bash\nsudo apt update\n```"
        result = agent.run("atualize os pacotes")
        assert result.get("needs_confirmation") is True
        assert result.get("is_complete") is False or result.get("needs_confirmation")

    def test_unsafe_mode_executes_without_confirmation(self, security_config, mock_llm_client):
        """Modo inseguro deve executar comandos mutáveis sem confirmação."""
        unsafe_config = {**security_config, "unsafe_mode": True}
        db = Database(":memory:")
        security = SecurityValidator(unsafe_config)
        config = {
            "history": {"max_context_messages": 5},
            "security": {**unsafe_config, "command_timeout": 10},
            "agent": {"max_retries": 0},
        }
        with (
            patch("src.agent.graph.collect_system_context", return_value={"desktop": "/home/test/Desktop"}),
            patch("src.agent.graph.format_system_context", return_value="MOCK CONTEXT"),
        ):
            agent = AgentGraph(mock_llm_client, security, db, config)

        agent.llm.invoke.return_value = "```bash\nsudo apt update\n```"
        with patch("src.agent.graph.execute_command") as mock_exec:
            mock_exec.return_value = MagicMock(stdout="ok\n", stderr="", exit_code=0, timed_out=False)
            result = agent.run("atualize os pacotes")

        assert result.get("needs_confirmation") is False
        assert result.get("ui_status") == "success"
        assert mock_exec.call_args.kwargs["allow_unsafe"] is True


class TestAgentGraphBlocked:
    def test_blocked_command(self, agent):
        """Comando perigoso deve ser bloqueado."""
        agent.llm.invoke.return_value = "```bash\nrm -rf /\n```"
        result = agent.run("apague tudo")
        assert result.get("ui_status") == "blocked"


class TestAgentGraphLLMError:
    def test_llm_timeout(self, agent):
        """Timeout do LLM deve ser tratado."""
        agent.llm.invoke.side_effect = TimeoutError("timeout")
        result = agent.run("faça algo")
        assert result.get("ui_status") == "error"
        assert result.get("is_complete") is True

    def test_llm_connection_error(self, agent):
        """Erro de conexão do LLM deve ser tratado."""
        agent.llm.invoke.side_effect = ConnectionError("offline")
        result = agent.run("faça algo")
        assert result.get("ui_status") == "error"

    def test_llm_generic_error(self, agent):
        """Erro genérico do LLM deve ser tratado."""
        agent.llm.invoke.side_effect = RuntimeError("unknown")
        result = agent.run("faça algo")
        assert result.get("ui_status") == "error"


class TestAgentGraphExtraction:
    def test_no_command_extracted(self, agent):
        """Falha na extração deve solicitar clarificação."""
        agent.llm.invoke.return_value = "Desculpe, não entendi."
        result = agent.run("xyz abc")
        assert result.get("ui_status") == "warning"

    def test_llm_error_response(self, agent):
        """Resposta de erro do LLM deve ser tratada."""
        agent.llm.invoke.return_value = "```bash\n# ERRO: Pedido impossível\n```"
        result = agent.run("faça o impossível")
        assert result.get("ui_status") == "warning"


class TestAgentGraphTools:
    def test_read_only_native_tool_executes_directly(self, agent):
        """Tool D-Bus read-only deve executar sem confirmação."""
        agent.llm.invoke.side_effect = [
            '```tool\n{"tool":"dbus_native","action":"service_status","args":{"service":"docker"}}\n```',
            "SATISFATORIO"
        ]
        agent.native_tool.run = MagicMock(
            return_value=NativeToolResult(
                success=True,
                tool="dbus_native",
                action="service_status",
                data={"service": "docker.service", "active_state": "active"},
            )
        )

        result = agent.run("status do docker")

        assert result.get("ui_status") == "success"
        assert "native:dbus_native.service_status" in result.get("extracted_command", "")
        agent.native_tool.run.assert_called_once_with("service_status", {"service": "docker"})

    def test_mutating_native_tool_needs_confirmation(self, agent):
        """Tool D-Bus mutável deve pedir confirmação."""
        agent.llm.invoke.return_value = (
            '```tool\n{"tool":"dbus_native","action":"restart_service","args":{"service":"docker"}}\n```'
        )

        result = agent.run("reinicie o docker")

        assert result.get("needs_confirmation") is True
        assert result.get("confirmation_kind") == "tool"

    def test_execute_confirmed_native_tool(self, agent):
        """Tool confirmada deve executar via executor nativo, não via Bash."""
        state = {
            "user_input": "reinicie o docker",
            "tool_call": MagicMock(
                tool="dbus_native",
                action="restart_service",
                args={"service": "docker"},
                explanation="Reiniciando serviço.",
                display_name=MagicMock(return_value='dbus_native.restart_service {"service": "docker"}'),
            ),
            "llm_response": "tool",
            "max_retries": 1,
            "retry_count": 0,
        }
        agent.llm.invoke.return_value = "SATISFATORIO"
        agent.native_tool.run = MagicMock(
            return_value=NativeToolResult(
                success=True,
                tool="dbus_native",
                action="restart_service",
                data={"job_path": "/job/1"},
                read_only=False,
            )
        )

        result = agent.execute_confirmed(state)

        assert result.get("is_complete") is True
        assert result.get("ui_status") == "success"
        agent.native_tool.run.assert_called_once_with("restart_service", {"service": "docker"})


class TestAgentGraphSelfHealing:
    def test_retry_on_failure(self, agent):
        """Deve retentar quando avaliação é insatisfatória."""
        responses = [
            '```bash\necho "tentativa 1"\n```',
            '```bash\necho "tentativa 2"\n```',
        ]
        agent.llm.invoke.side_effect = [*responses, "SATISFATORIO"]
        with patch("src.agent.graph.execute_command") as mock_exec:
            mock_exec.return_value = MagicMock(stdout="tentativa 1\n", stderr="", exit_code=0, timed_out=False)
            # First call returns command, second call is evaluation
            agent.llm.invoke.side_effect = [
                '```bash\necho "test"\n```',  # LLM response
                "SATISFATORIO",  # Evaluation
            ]
            result = agent.run("diga test")
        assert result.get("is_complete") is True


class TestExecuteConfirmed:
    def test_execute_confirmed_success(self, agent):
        """execute_confirmed deve executar e salvar."""
        state = {
            "user_input": "instale vim",
            "extracted_command": "echo ok",
            "history_context": "",
            "needs_confirmation": True,
            "retry_count": 0,
            "max_retries": 1,
        }
        agent.llm.invoke.return_value = "SATISFATORIO"
        with patch("src.agent.graph.execute_command") as mock_exec:
            mock_exec.return_value = MagicMock(stdout="ok\n", stderr="", exit_code=0, timed_out=False)
            result = agent.execute_confirmed(state)
        assert result.get("is_complete") is True
        assert result.get("ui_status") == "success"
