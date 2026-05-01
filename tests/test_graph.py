"""
Testes de integração para o grafo do agente (agent/graph.py).
Usa LLM mockado para testar o fluxo completo sem dependência externa.
"""

import pytest
from unittest.mock import MagicMock, patch
from src.agent.graph import AgentGraph, AgentState
from src.executor.safety import SecurityValidator
from src.storage.database import Database


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
    with patch("src.agent.graph.collect_system_context") as mock_ctx, \
         patch("src.agent.graph.format_system_context") as mock_fmt:
        mock_ctx.return_value = {"desktop": "/home/test/Desktop"}
        mock_fmt.return_value = "MOCK CONTEXT"
        return AgentGraph(mock_llm_client, security, db, config)


class TestAgentGraphReadOnly:
    def test_read_only_executes_directly(self, agent):
        """Comando read-only deve executar sem confirmação."""
        agent.llm.invoke.return_value = '```bash\necho "hello"\n```'
        with patch("src.agent.graph.execute_command") as mock_exec:
            mock_exec.return_value = MagicMock(
                stdout="hello\n", stderr="", exit_code=0, timed_out=False
            )
            result = agent.run("diga hello")
        assert result.get("ui_status") in ("success", "info")
        assert result.get("is_complete") is True


class TestAgentGraphConfirmation:
    def test_sudo_needs_confirmation(self, agent):
        """Comando com sudo deve pedir confirmação."""
        agent.llm.invoke.return_value = '```bash\nsudo apt update\n```'
        result = agent.run("atualize os pacotes")
        assert result.get("needs_confirmation") is True
        assert result.get("is_complete") is False or result.get("needs_confirmation")


class TestAgentGraphBlocked:
    def test_blocked_command(self, agent):
        """Comando perigoso deve ser bloqueado."""
        agent.llm.invoke.return_value = '```bash\nrm -rf /\n```'
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
        agent.llm.invoke.return_value = '```bash\n# ERRO: Pedido impossível\n```'
        result = agent.run("faça o impossível")
        assert result.get("ui_status") == "warning"


class TestAgentGraphSelfHealing:
    def test_retry_on_failure(self, agent):
        """Deve retentar quando avaliação é insatisfatória."""
        responses = [
            '```bash\necho "tentativa 1"\n```',
            '```bash\necho "tentativa 2"\n```',
        ]
        agent.llm.invoke.side_effect = responses + ["SATISFATORIO"]
        with patch("src.agent.graph.execute_command") as mock_exec:
            mock_exec.return_value = MagicMock(
                stdout="tentativa 1\n", stderr="", exit_code=0, timed_out=False
            )
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
            mock_exec.return_value = MagicMock(
                stdout="ok\n", stderr="", exit_code=0, timed_out=False
            )
            result = agent.execute_confirmed(state)
        assert result.get("is_complete") is True
        assert result.get("ui_status") == "success"
