"""
Testes para o cliente LLM.
"""

from unittest.mock import MagicMock, patch

from src.agent.llm import LLMClient


def _client(base_url: str = "http://localhost:1234") -> LLMClient:
    with patch("src.agent.llm.ChatOpenAI"):
        return LLMClient(
            {
                "base_url": base_url,
                "model": "test-model",
                "api_key": "not-needed",
            }
        )


class TestLLMClientEndpoint:
    def test_normalizes_base_url_with_v1(self):
        client = _client("http://192.168.1.119:1234")
        assert client.base_url == "http://192.168.1.119:1234/v1"

    def test_keeps_existing_v1_suffix(self):
        client = _client("http://192.168.1.119:1234/v1")
        assert client.base_url == "http://192.168.1.119:1234/v1"

    def test_set_endpoint_normalizes_url(self):
        client = _client()
        client.set_endpoint("http://10.0.0.2:1234")
        assert client.base_url == "http://10.0.0.2:1234/v1"


class TestLLMClientModels:
    @patch("src.agent.llm.requests.get")
    def test_health_check_uses_openai_models_endpoint(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)
        client = _client("http://192.168.1.119:1234")

        assert client.health_check() is True

        mock_get.assert_called_once()
        assert mock_get.call_args.args[0] == "http://192.168.1.119:1234/v1/models"

    @patch("src.agent.llm.requests.get")
    def test_list_models_reads_openai_compatible_response(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"data": [{"id": "qwen/qwen3-coder-30b"}, {"id": "l3-8b"}]}),
        )
        client = _client("http://192.168.1.119:1234")

        assert client.list_models() == [
            {"name": "qwen/qwen3-coder-30b", "size": "n/a", "modified": ""},
            {"name": "l3-8b", "size": "n/a", "modified": ""},
        ]

    @patch("src.agent.llm.requests.get")
    def test_list_models_falls_back_to_ollama_tags(self, mock_get):
        openai_response = MagicMock(status_code=404)
        ollama_response = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"models": [{"name": "qwen2.5-coder:3b", "size": 2 * 1024**3}]}),
        )
        mock_get.side_effect = [openai_response, ollama_response]
        client = _client("http://localhost:11434")

        assert client.list_models() == [
            {"name": "qwen2.5-coder:3b", "size": "2.0 GB", "modified": ""},
        ]
        assert mock_get.call_args_list[1].args[0] == "http://localhost:11434/api/tags"
