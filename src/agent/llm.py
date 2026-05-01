"""
Ubuntu Agent - Integração com o LLM.

Configura e invoca o LLM via langchain-openai, apontando para um
endpoint local compatível com a API OpenAI (Ollama, LM Studio, vLLM).
"""

import requests
import tiktoken
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from src.logger import get_logger

log = get_logger("agent.llm")

class LLMClient:
    """Cliente para interação com o LLM local."""

    def __init__(self, config: dict) -> None:
        """
        Inicializa o cliente LLM com as configurações fornecidas.

        Args:
            config: Dicionário com chaves base_url, model, api_key, temperature, timeout.
        """
        self.config = config
        self.base_url: str = config.get("base_url", "http://localhost:11434/v1")
        self.model: str = config.get("model", "llama3.1:8b")
        self.api_key: str = config.get("api_key", "not-needed")
        self.temperature: float = config.get("temperature", 0.1)
        self.timeout: int = config.get("timeout", 30)

        self._llm = self._create_client()

    def _create_client(self) -> ChatOpenAI:
        """Cria uma instância do ChatOpenAI com as configurações atuais."""
        return ChatOpenAI(
            base_url=self.base_url,
            model=self.model,
            api_key=SecretStr(self.api_key) if self.api_key else None,
            temperature=self.temperature,
            timeout=self.timeout,
            max_retries=1,
        )

    def set_model(self, model: str) -> None:
        """
        Troca o modelo ativo em tempo de execução.

        Args:
            model: Nome do modelo (ex: 'qwen2.5-coder:3b').
        """
        self.model = model
        self._llm = self._create_client()

    def set_endpoint(self, base_url: str) -> None:
        """
        Troca o endpoint do LLM em tempo de execução.

        Args:
            base_url: Nova URL base (ex: 'http://192.168.1.100:11434/v1').
        """
        self.base_url = base_url
        self._llm = self._create_client()

    def list_models(self) -> list[dict]:
        """
        Lista os modelos disponíveis no servidor Ollama.

        Returns:
            Lista de dicts com 'name' e 'size' de cada modelo.
        """
        root_url = self.base_url.rstrip("/v1").rstrip("/")
        try:
            resp = requests.get(f"{root_url}/api/tags", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                models = []
                for m in data.get("models", []):
                    size_gb = m.get("size", 0) / (1024 ** 3)
                    models.append({
                        "name": m.get("name", ""),
                        "size": f"{size_gb:.1f} GB",
                        "modified": m.get("modified_at", ""),
                    })
                return models
        except requests.RequestException:
            pass
        return []

    def invoke(self, system_prompt: str, user_message: str) -> str:
        """
        Envia uma mensagem ao LLM e retorna a resposta.

        Args:
            system_prompt: Prompt de sistema com as instruções do agente.
            user_message: Mensagem do usuário (input + contexto).

        Returns:
            Conteúdo textual da resposta do LLM.

        Raises:
            TimeoutError: Se o LLM exceder o timeout configurado.
            ConnectionError: Se o endpoint não estiver acessível.
        """
        try:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_message),
            ]
            response = self._llm.invoke(messages)
            return str(response.content)

        except Exception as e:
            error_msg = str(e).lower()
            if "timeout" in error_msg or "timed out" in error_msg:
                raise TimeoutError(
                    f"LLM demorou mais de {self.timeout}s para responder."
                ) from e
            if "connection" in error_msg or "connect" in error_msg:
                raise ConnectionError(
                    f"Não foi possível conectar ao LLM em {self.base_url}"
                ) from e
            raise

    def stream(self, system_prompt: str, user_message: str):
        """
        Envia uma mensagem ao LLM e retorna um gerador de tokens de resposta.

        Args:
            system_prompt: Prompt de sistema com as instruções do agente.
            user_message: Mensagem do usuário (input + contexto).

        Yields:
            Pedaços (chunks) da string gerada pelo LLM.
        """
        try:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_message),
            ]
            for chunk in self._llm.stream(messages):
                yield chunk.content

        except Exception as e:
            error_msg = str(e).lower()
            if "timeout" in error_msg or "timed out" in error_msg:
                raise TimeoutError(
                    f"LLM demorou mais de {self.timeout}s para responder durante streaming."
                ) from e
            if "connection" in error_msg or "connect" in error_msg:
                raise ConnectionError(
                    f"Não foi possível conectar ao LLM em {self.base_url}"
                ) from e
            raise

    def health_check(self) -> bool:
        """
        Verifica se o endpoint LLM está acessível.

        Returns:
            True se o endpoint responder, False caso contrário.
        """
        root_url = self.base_url.rstrip("/v1").rstrip("/")
        try:
            resp = requests.get(root_url, timeout=5)
            return resp.status_code < 500
        except requests.RequestException:
            pass

        # Tenta endpoint específico do Ollama
        try:
            resp = requests.get(f"{root_url}/api/tags", timeout=5)
            return resp.status_code < 500
        except requests.RequestException:
            return False

    def count_tokens(self, text: str) -> int:
        """
        Calcula a quantidade aproximada de tokens em um texto.
        Usa o cl100k_base (padrão OpenAI) como aproximação universal rápida.
        """
        if not text:
            return 0
        try:
            encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(text))
        except Exception as e:
            log.warning(f"Erro ao contar tokens: {e}")
            return 0
