"""
Ubuntu Agent - Definição do grafo LangGraph.

Implementa o fluxo completo do agente com nós condicionais:
receber_input → consultar_llm → extrair_comando → validar_seguranca →
solicitar_confirmacao / bloquear_cmd / executar_comando → atualizar_ui
"""

import unicodedata
from typing import Any, Literal, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agent.llm import LLMClient
from src.agent.prompts import EVALUATION_PROMPT, SYSTEM_PROMPT, build_context_messages, build_memory_context
from src.agent.tool_calls import ToolCall, extract_tool_call
from src.executor.bash import ExecutionResult, ExtractionResult, execute_command, extract_command
from src.executor.safety import CommandCategory, SafetyResult, SecurityValidator
from src.logger import get_logger
from src.storage.database import Database
from src.system.context import collect_system_context, format_system_context
from src.tools.dbus_native import NativeSystemTool, NativeToolResult
from src.tools.resources import ResourceMonitorTool

log = get_logger("agent.graph")


class AgentState(TypedDict, total=False):
    """Estado compartilhado entre os nós do grafo."""

    # Input
    user_input: str
    history_context: str
    memory_context: str
    direct_command: bool
    resource_snapshot: dict[str, Any]
    resource_context: str

    # LLM
    llm_response: str
    llm_error: str

    # Extração
    extraction: ExtractionResult
    extracted_command: str
    tool_call: ToolCall
    tool_result: NativeToolResult | dict[str, Any]
    tool_needs_confirmation: bool
    confirmation_kind: str

    # Segurança
    safety_result: SafetyResult
    blocked_reason: str

    # Confirmação
    needs_confirmation: bool
    user_confirmed: bool

    # Execução
    execution_result: ExecutionResult

    # Auto-avaliação
    retry_count: int
    max_retries: int
    evaluation_feedback: str

    # UI
    ui_message: str
    ui_status: str  # "success", "error", "warning", "blocked", "pending"
    is_complete: bool


class AgentGraph:
    """Grafo do agente Ubuntu que processa comandos em linguagem natural."""

    def __init__(
        self, llm_client: LLMClient, security: SecurityValidator, db: Database, config: dict, vault=None
    ) -> None:
        """
        Inicializa o grafo com suas dependências.

        Args:
            llm_client: Cliente do LLM.
            security: Validador de segurança.
            db: Banco de dados para histórico.
            config: Configurações gerais.
        """
        self.llm = llm_client
        self.security = security
        self.db = db
        self.config = config
        self.vault = vault
        self.max_context = config.get("history", {}).get("max_context_messages", 5)
        self.max_memory = config.get("history", {}).get("max_memory_items", 8)
        self.command_timeout = config.get("security", {}).get("command_timeout", 60)
        self.max_retries = config.get("agent", {}).get("max_retries", 2)
        self._step_callback = None  # Callback para UI acompanhar nós
        self.resource_tool = ResourceMonitorTool()
        self.native_tool = NativeSystemTool()
        self.unsafe_mode = bool(getattr(self.security, "unsafe_mode", False))

        # Rate limiting
        self._last_request_time = 0.0
        self._min_request_interval = config.get("agent", {}).get("min_request_interval", 2.0)

        # Coletar contexto do sistema uma vez
        self._system_ctx = collect_system_context()
        self._system_ctx_str = format_system_context(self._system_ctx)
        log.info("Contexto do sistema coletado: desktop=%s", self._system_ctx.get("desktop"))

        self.graph = self._build_graph()

    def _build_graph(self) -> CompiledStateGraph:
        """Constrói o grafo LangGraph com todos os nós e edges."""
        graph = StateGraph(AgentState)

        # Adicionar nós
        graph.add_node("receber_input", self._receber_input)
        graph.add_node("coletar_recursos", self._coletar_recursos)
        graph.add_node("consultar_llm", self._consultar_llm)
        graph.add_node("extrair_comando", self._extrair_comando)
        graph.add_node("solicitar_clarifica", self._solicitar_clarifica)
        graph.add_node("validar_tool", self._validar_tool)
        graph.add_node("preparar_tool_confirmacao", self._preparar_tool_confirmacao)
        graph.add_node("executar_tool", self._executar_tool)
        graph.add_node("validar_seguranca", self._validar_seguranca)
        graph.add_node("bloquear_cmd", self._bloquear_cmd)
        graph.add_node("preparar_confirmacao", self._preparar_confirmacao)
        graph.add_node("executar_comando", self._executar_comando)
        graph.add_node("avaliar_resultado", self._avaliar_resultado)
        graph.add_node("atualizar_ui", self._atualizar_ui)

        # Definir ponto de entrada
        graph.set_entry_point("receber_input")

        # Edges lineares e atalhos determinísticos
        graph.add_conditional_edges(
            "receber_input",
            self._check_direct_command,
            {
                "direct": "validar_seguranca",
                "llm": "coletar_recursos",
            },
        )
        graph.add_edge("coletar_recursos", "consultar_llm")

        # Edge condicional após consultar_llm (verifica erro do LLM)
        graph.add_conditional_edges(
            "consultar_llm",
            self._check_llm_result,
            {
                "success": "extrair_comando",
                "error": "atualizar_ui",
            },
        )

        # Edge condicional após extração
        graph.add_conditional_edges(
            "extrair_comando",
            self._check_extraction,
            {
                "tool": "validar_tool",
                "valid": "validar_seguranca",
                "invalid": "solicitar_clarifica",
            },
        )

        # Clarificação vai direto para atualizar_ui
        graph.add_edge("solicitar_clarifica", "atualizar_ui")

        # Edge condicional após validação de tool
        graph.add_conditional_edges(
            "validar_tool",
            self._check_tool_safety,
            {
                "read_only": "executar_tool",
                "needs_confirmation": "preparar_tool_confirmacao",
                "blocked": "bloquear_cmd",
            },
        )

        graph.add_edge("preparar_tool_confirmacao", "atualizar_ui")
        graph.add_edge("executar_tool", "avaliar_resultado")

        # Edge condicional após validação de segurança
        graph.add_conditional_edges(
            "validar_seguranca",
            self._check_safety,
            {
                "read_only": "executar_comando",
                "needs_confirmation": "preparar_confirmacao",
                "blocked": "bloquear_cmd",
            },
        )

        # Bloqueio vai para atualizar_ui
        graph.add_edge("bloquear_cmd", "atualizar_ui")

        # Preparar confirmação vai para atualizar_ui (a UI decide se executa)
        graph.add_edge("preparar_confirmacao", "atualizar_ui")

        # Execução vai para avaliação de resultado
        graph.add_edge("executar_comando", "avaliar_resultado")

        # Edge condicional após avaliação: satisfatório vai para UI, insatisfatório tenta de novo
        graph.add_conditional_edges(
            "avaliar_resultado",
            self._check_evaluation,
            {
                "satisfatorio": "atualizar_ui",
                "retry": "consultar_llm",
                "max_retries": "atualizar_ui",
            },
        )

        # Fim
        graph.add_edge("atualizar_ui", END)

        return graph.compile()

    # ─── Nós do Grafo ────────────────────────────────────────────────────────

    def _notify_step(self, message: str) -> None:
        """Notifica a UI sobre o passo atual do grafo."""
        if self._step_callback:
            self._step_callback(message)

    def set_step_callback(self, callback) -> None:
        """Define callback para a UI acompanhar os passos do grafo."""
        self._step_callback = callback

    def set_unsafe_mode(self, enabled: bool) -> None:
        """Liga/desliga o modo de acesso total em tempo de execução."""
        self.unsafe_mode = bool(enabled)
        if hasattr(self.security, "set_unsafe_mode"):
            self.security.set_unsafe_mode(self.unsafe_mode)

    def _receber_input(self, state: AgentState) -> dict:
        """Captura o input do usuário e carrega histórico + memória operacional."""
        history = self.db.get_last_n(self.max_context)
        context = build_context_messages(history)
        memories = self.db.get_recent_memories(self.max_memory)
        memory_context = build_memory_context(memories)
        update: dict[str, Any] = {"history_context": context, "memory_context": memory_context}

        direct_command = self._direct_command_for(state.get("user_input", ""))
        if direct_command:
            self._notify_step("Usando atalho local para pedido simples...")
            update.update(
                {
                    "direct_command": True,
                    "llm_response": f"direct:{direct_command}",
                    "extracted_command": direct_command,
                }
            )

        return update

    def _direct_command_for(self, user_input: str) -> str:
        """Resolve pedidos simples e seguros sem depender do LLM."""
        normalized = self._normalize_intent(user_input)
        words = set(normalized.split())

        identity_phrases = {
            "quem esta ai",
            "quem esta aqui",
            "quem e voce",
            "quem e vc",
            "quem voce e",
            "who are you",
        }
        if normalized in identity_phrases:
            return 'echo "Sou o Ubuntu Agent, seu assistente local para administrar este Ubuntu."'

        settings_words = {"configuracoes", "configuracao", "settings", "ajustes", "preferencias"}
        ubuntu_words = {"ubuntu", "sistema", "gnome"}
        if words & settings_words and (words & ubuntu_words or "configuracoes" in words):
            return "gnome-control-center"

        if "terminal" not in words:
            return ""

        close_words = {"feche", "fecha", "fechar", "encerre", "encerrar", "mate", "matar", "kill", "close"}
        if words & close_words:
            return ""

        open_words = {
            "abra",
            "abre",
            "abrir",
            "inicie",
            "iniciar",
            "execute",
            "executar",
            "lance",
            "lancar",
            "open",
            "start",
            "launch",
        }
        if words & open_words or normalized.strip() == "terminal":
            return str(self._system_ctx.get("terminal_command") or "x-terminal-emulator")

        return ""

    @staticmethod
    def _normalize_intent(text: str) -> str:
        without_accents = "".join(
            char for char in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(char)
        )
        return " ".join(without_accents.replace("-", " ").split())

    def _coletar_recursos(self, state: AgentState) -> dict:
        """Coleta snapshot read-only de recursos para orientar o roteador."""
        self._notify_step("Lendo recursos do sistema...")
        try:
            snapshot = self.resource_tool.run()
            resource_context = (
                "--- Estado atual da máquina (snapshot read-only) ---\n"
                f"{self.resource_tool.run_json() if not snapshot else self._resource_json(snapshot)}\n"
                "---"
            )
            return {"resource_snapshot": snapshot, "resource_context": resource_context}
        except Exception as e:
            log.warning("Falha ao coletar recursos: %s", str(e)[:200])
            return {
                "resource_snapshot": {},
                "resource_context": f"--- Estado atual da máquina indisponível: {str(e)[:160]} ---",
            }

    @staticmethod
    def _resource_json(snapshot: dict[str, Any]) -> str:
        import json

        return json.dumps(snapshot, ensure_ascii=False, sort_keys=True)

    def _consultar_llm(self, state: AgentState) -> dict:
        """Envia o input + contexto ao LLM."""
        user_input = state.get("user_input", "")
        context = state.get("history_context", "")
        memory_context = state.get("memory_context", "")
        resource_context = state.get("resource_context", "")
        feedback = state.get("evaluation_feedback", "")
        retry_count = state.get("retry_count", 0)

        if retry_count > 0:
            self._notify_step(f"🔄 Tentativa {retry_count + 1}: consultando LLM...")
        else:
            self._notify_step("🤖 Consultando LLM...")

        # Monta a mensagem completa
        message_parts = []
        # Contexto do sistema (diretórios reais, locale, etc.)
        message_parts.append(self._system_ctx_str)
        if resource_context:
            message_parts.append(resource_context)
        if memory_context:
            message_parts.append(memory_context)
        if context:
            message_parts.append(context)
        message_parts.append(f"Solicitação do usuário: {user_input}")
        if feedback:
            message_parts.append(
                f"\nATENÇÃO: A tentativa anterior foi insatisfatória. Feedback: {feedback}\nGere um comando MELHOR que realmente atenda ao pedido."
            )
        full_message = "\n\n".join(message_parts)

        try:
            if hasattr(self, "_stream_callback") and self._stream_callback:
                response_chunks = []
                for chunk in self.llm.stream(SYSTEM_PROMPT, full_message):
                    response_chunks.append(chunk)
                    self._stream_callback(chunk)
                response = "".join(response_chunks)
            else:
                response = self.llm.invoke(SYSTEM_PROMPT, full_message)

            log.info("LLM respondeu com sucesso (%d chars).", len(response))
            log.debug("Resposta LLM: %s", response[:500])
            return {"llm_response": response, "llm_error": ""}
        except TimeoutError:
            return {
                "llm_error": "⏱ LLM demorou demais. Tente novamente.",
                "ui_message": "⏱ LLM demorou demais. Tente novamente.",
                "ui_status": "error",
                "is_complete": True,
            }
        except ConnectionError:
            return {
                "llm_error": "⚠ LLM não acessível. Verifique o endpoint.",
                "ui_message": "⚠ LLM não acessível. Verifique o endpoint.",
                "ui_status": "error",
                "is_complete": True,
            }
        except Exception as e:
            return {
                "llm_error": f"⚠ Erro ao consultar LLM: {str(e)[:200]}",
                "ui_message": f"⚠ Erro ao consultar LLM: {str(e)[:200]}",
                "ui_status": "error",
                "is_complete": True,
            }

    def _extrair_comando(self, state: AgentState) -> dict:
        """Extrai chamada de tool nativa ou comando Bash da resposta do LLM."""
        llm_response = state.get("llm_response", "")
        tool_extraction = extract_tool_call(llm_response)
        if tool_extraction.success and tool_extraction.tool_call:
            tool_call = tool_extraction.tool_call
            log.info("Tool extraída: %s.%s", tool_call.tool, tool_call.action)
            return {
                "tool_call": tool_call,
                "extracted_command": "",
            }

        result = extract_command(llm_response)
        log.info("Extração: success=%s, command='%s'", result.success, result.command[:100] if result.command else "")
        return {
            "extraction": result,
            "extracted_command": result.command if result.success else "",
        }

    def _validar_tool(self, state: AgentState) -> dict:
        """Valida tool call nativa e decide se precisa de confirmação."""
        tool_call = state.get("tool_call")
        if not tool_call:
            return {
                "blocked_reason": "Nenhuma tool call encontrada.",
                "ui_message": "Tool call ausente.",
                "ui_status": "blocked",
            }

        if tool_call.tool == "resource_snapshot" and tool_call.action == "read":
            return {"tool_needs_confirmation": False}
        if tool_call.tool == "resource_snapshot":
            return {
                "blocked_reason": f"Ação resource_snapshot desconhecida: {tool_call.action}",
                "ui_message": f"Ação resource_snapshot desconhecida: {tool_call.action}",
                "ui_status": "blocked",
            }

        if tool_call.tool != self.native_tool.name:
            return {
                "blocked_reason": f"Tool desconhecida: {tool_call.tool}",
                "ui_message": f"Tool desconhecida: {tool_call.tool}",
                "ui_status": "blocked",
            }

        if not self.native_tool.is_known_action(tool_call.action):
            return {
                "blocked_reason": f"Ação nativa desconhecida: {tool_call.action}",
                "ui_message": f"Ação nativa desconhecida: {tool_call.action}",
                "ui_status": "blocked",
            }

        return {
            "tool_needs_confirmation": False
            if self.unsafe_mode
            else not self.native_tool.is_read_only(tool_call.action)
        }

    def _preparar_tool_confirmacao(self, state: AgentState) -> dict:
        """Prepara confirmação para tool nativa mutável."""
        tool_call = state.get("tool_call")
        display = tool_call.display_name() if tool_call else "tool desconhecida"
        explanation = f"\n\n{tool_call.explanation}" if tool_call and tool_call.explanation else ""
        return {
            "needs_confirmation": True,
            "confirmation_kind": "tool",
            "extracted_command": f"native:{display}",
            "ui_message": f"Confirmação necessária para ação nativa:\n\n{display}{explanation}",
            "ui_status": "pending",
            "is_complete": False,
        }

    def _executar_tool(self, state: AgentState) -> dict:
        """Executa tool nativa ou resource snapshot."""
        tool_call = state.get("tool_call")
        if not tool_call:
            return {
                "ui_message": "Não foi possível executar: tool call ausente.",
                "ui_status": "error",
                "is_complete": True,
            }

        self._notify_step(f"Executando tool {tool_call.tool}.{tool_call.action}...")
        if tool_call.tool == "resource_snapshot":
            snapshot = self.resource_tool.run()
            return {
                "tool_result": snapshot,
                "ui_message": f"Snapshot de recursos:\n\n{self._resource_json(snapshot)}",
                "ui_status": "success",
                "is_complete": True,
            }

        result = self.native_tool.run(tool_call.action, tool_call.args)
        status = "success" if result.success else "warning"
        message = self._format_tool_result(tool_call, result)
        return {
            "tool_result": result,
            "extracted_command": f"native:{tool_call.display_name()}",
            "ui_message": message,
            "ui_status": status,
            "is_complete": True,
        }

    def _solicitar_clarifica(self, state: AgentState) -> dict:
        """Informa ao usuário que o comando não pôde ser extraído."""
        extraction = state.get("extraction")
        if extraction and extraction.is_error_response:
            msg = f"⚠ O LLM reportou: {extraction.error_message}"
        else:
            msg = "❌ Não consegui gerar um comando. Reformule o pedido."
        return {
            "ui_message": msg,
            "ui_status": "warning",
            "is_complete": True,
        }

    def _validar_seguranca(self, state: AgentState) -> dict:
        """Valida o comando extraído contra a blocklist de segurança."""
        command = state.get("extracted_command", "")
        result = self.security.validate(command)
        log.info(
            "Segurança: category=%s, is_safe=%s, reason='%s'", result.category.value, result.is_safe, result.reason
        )
        return {"safety_result": result}

    def _bloquear_cmd(self, state: AgentState) -> dict:
        """Bloqueia o comando e informa o motivo."""
        safety = state.get("safety_result")
        reason = safety.reason if safety else state.get("blocked_reason", "Motivo desconhecido")
        pattern = safety.matched_pattern if safety else ""

        msg = f"🚫 Comando bloqueado por segurança: {reason}"
        if pattern:
            msg += f"\nPadrão detectado: {pattern}"

        return {
            "ui_message": msg,
            "ui_status": "blocked",
            "blocked_reason": reason,
            "is_complete": True,
        }

    @staticmethod
    def _format_tool_result(tool_call: ToolCall, result: NativeToolResult) -> str:
        prefix = tool_call.explanation or f"Tool nativa: {tool_call.action}"
        if result.success:
            return f"{prefix}\n\nResultado:\n{result.to_json()}"
        return f"{prefix}\n\nFalha controlada:\n{result.to_json()}"

    def _preparar_confirmacao(self, state: AgentState) -> dict:
        """Prepara o estado para solicitar confirmação do usuário."""
        command = state.get("extracted_command", "")
        safety = state.get("safety_result")
        reason = safety.reason if safety else ""

        return {
            "needs_confirmation": True,
            "ui_message": f"⚠ Confirmação necessária:\n\n$ {command}\n\n{reason}",
            "ui_status": "pending",
            "is_complete": False,  # A UI vai decidir
        }

    def _executar_comando(self, state: AgentState) -> dict:
        """Executa o comando Bash via subprocess."""
        command = state.get("extracted_command", "")
        self._notify_step("▶ Executando comando...")
        log.info("Executando comando: %s", command)

        result = execute_command(command, timeout=self.command_timeout, vault=self.vault, allow_unsafe=self.unsafe_mode)
        log.info("Resultado: exit_code=%d, timed_out=%s", result.exit_code, result.timed_out)
        if result.stderr:
            log.debug("stderr: %s", result.stderr[:500])

        if result.timed_out:
            return {
                "execution_result": result,
                "ui_message": f"⏱ Comando excedeu timeout de {self.command_timeout}s.",
                "ui_status": "error",
                "is_complete": True,
            }

        if result.exit_code == 0:
            output = result.stdout.strip() if result.stdout.strip() else "(sem saída)"
            return {
                "execution_result": result,
                "ui_message": f"✅ Executado com sucesso:\n\n$ {command}\n\n{output}",
                "ui_status": "success",
            }
        else:
            error_out = result.stderr.strip() if result.stderr.strip() else result.stdout.strip()
            return {
                "execution_result": result,
                "ui_message": f"❌ Erro (código {result.exit_code}):\n\n$ {command}\n\n{error_out}",
                "ui_status": "error",
            }

    def _avaliar_resultado(self, state: AgentState) -> dict:
        """Avalia se o resultado da execução satisfez a intenção do usuário."""
        retry_count = state.get("retry_count", 0)
        user_input = state.get("user_input", "")
        command = state.get("extracted_command", "")
        execution = state.get("execution_result")
        tool_result = state.get("tool_result")

        # Se o comando deu timeout, não avaliar
        if execution and execution.timed_out:
            return {"is_complete": True}

        # Atalhos locais já são intencionais e não precisam de avaliação do LLM.
        if state.get("direct_command"):
            return {"is_complete": True}

        # Se já atingiu máximo de retentativas
        if retry_count >= self.max_retries:
            log.info("Máximo de retentativas (%d) atingido.", self.max_retries)
            return {"is_complete": True}

        self._notify_step("🧠 Avaliando resultado...")

        if execution:
            stdout = execution.stdout.strip() if execution and execution.stdout else "(sem saída)"
            exit_code = execution.exit_code if execution else -1
            eval_message = (
                f"Pedido original do usuário: {user_input}\n"
                f"Comando executado: {command}\n"
                f"Código de saída: {exit_code}\n"
                f"Saída do comando: {stdout[:1000]}"
            )
        elif tool_result:
            if not isinstance(tool_result, NativeToolResult):
                return {"is_complete": True}

            if tool_result.success:
                return {"is_complete": True}
            else:
                feedback = f"A ferramenta nativa falhou: {tool_result.error_message}. NÃO USE a ferramenta nativa novamente. Gere um comando BASH alternativo."
                self._notify_step("🔄 Retentando: Falha na tool nativa")
                log.info("Auto-retentando tool nativa: %s", feedback)
                return {
                    "retry_count": retry_count + 1,
                    "evaluation_feedback": feedback,
                    "is_complete": False,
                }
        else:
            return {"is_complete": True}

        try:
            evaluation = self.llm.invoke(EVALUATION_PROMPT, eval_message)
            log.info("Avaliação (tentativa %d/%d): %s", retry_count + 1, self.max_retries, evaluation[:200])

            if "SATISFATORIO" in evaluation.upper() and "INSATISFATORIO" not in evaluation.upper():
                return {"is_complete": True}
            else:
                # Extrair feedback para a próxima tentativa
                feedback = evaluation.replace("INSATISFATORIO:", "").strip()
                self._notify_step(f"🔄 Tentativa {retry_count + 1}/{self.max_retries}: {feedback[:80]}")
                log.info("Retentando com feedback: %s", feedback[:200])
                return {
                    "retry_count": retry_count + 1,
                    "evaluation_feedback": feedback,
                    "is_complete": False,
                }
        except Exception as e:
            log.warning("Erro na avaliação, aceitando resultado: %s", str(e)[:200])
            return {"is_complete": True}

    def _atualizar_ui(self, state: AgentState) -> dict:
        """Salva o resultado no banco e finaliza o fluxo."""
        user_input = state.get("user_input", "")
        llm_response = state.get("llm_response")
        extracted = state.get("extracted_command")
        execution = state.get("execution_result")
        tool_result = state.get("tool_result")
        confirmed = state.get("user_confirmed", False)
        stdout = execution.stdout if execution else self._tool_stdout(tool_result)
        stderr = execution.stderr if execution else None
        exit_code = execution.exit_code if execution else self._tool_exit_code(tool_result)

        self.db.save_command(
            user_input=user_input,
            llm_response=llm_response,
            extracted_command=extracted,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            confirmed=confirmed,
        )

        if not state.get("needs_confirmation", False):
            self.db.remember_interaction(
                user_input=user_input,
                extracted_command=extracted,
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                confirmed=confirmed,
            )
        # Preservar is_complete=False se veio de preparar_confirmacao
        # para que a UI consiga abrir o modal de confirmação
        if state.get("needs_confirmation", False):
            log.debug("Confirmação pendente — preservando is_complete=False.")
            return {}
        return {"is_complete": True}

    @staticmethod
    def _tool_stdout(tool_result: NativeToolResult | dict[str, Any] | None) -> str | None:
        if tool_result is None:
            return None
        if isinstance(tool_result, NativeToolResult):
            return tool_result.to_json()
        return AgentGraph._resource_json(tool_result)

    @staticmethod
    def _tool_exit_code(tool_result: NativeToolResult | dict[str, Any] | None) -> int | None:
        if tool_result is None:
            return None
        if isinstance(tool_result, NativeToolResult):
            return 0 if tool_result.success else 1
        return 0

    # ─── Funções de Roteamento (Edges Condicionais) ──────────────────────────

    def _check_llm_result(self, state: AgentState) -> Literal["success", "error"]:
        """Verifica se a consulta ao LLM foi bem-sucedida."""
        if state.get("llm_error"):
            return "error"
        return "success"

    def _check_direct_command(self, state: AgentState) -> Literal["direct", "llm"]:
        """Roteia atalhos locais antes de consultar o LLM."""
        if state.get("direct_command") and state.get("extracted_command"):
            return "direct"
        return "llm"

    def _check_extraction(self, state: AgentState) -> Literal["tool", "valid", "invalid"]:
        """Verifica se a extração do comando foi bem-sucedida."""
        if state.get("tool_call"):
            return "tool"
        extraction = state.get("extraction")
        if extraction and extraction.success:
            return "valid"
        return "invalid"

    def _check_tool_safety(self, state: AgentState) -> Literal["read_only", "needs_confirmation", "blocked"]:
        """Roteia tool calls conforme permissividade."""
        if state.get("blocked_reason"):
            return "blocked"
        if state.get("tool_needs_confirmation", False):
            return "needs_confirmation"
        return "read_only"

    def _check_safety(self, state: AgentState) -> Literal["read_only", "needs_confirmation", "blocked"]:
        """Roteia baseado no resultado da validação de segurança."""
        safety = state.get("safety_result")
        if not safety:
            return "needs_confirmation"

        if safety.category == CommandCategory.BLOCKED:
            return "blocked"
        elif safety.category == CommandCategory.READ_ONLY:
            return "read_only"
        else:
            return "needs_confirmation"

    def _check_evaluation(self, state: AgentState) -> Literal["satisfatorio", "retry", "max_retries"]:
        """Roteia baseado na avaliação do resultado."""
        retry_count = state.get("retry_count", 0)
        if state.get("is_complete", True):
            if retry_count >= self.max_retries:
                return "max_retries"
            return "satisfatorio"
        return "retry"

    # ─── Interface Pública ───────────────────────────────────────────────────

    def run(self, user_input: str, stream_callback=None) -> AgentState:
        """
        Executa o grafo completo para um input do usuário.

        Args:
            user_input: Texto em linguagem natural do usuário.
            stream_callback: Função chamada a cada token gerado pelo LLM.

        Returns:
            Estado final do grafo com resultados.
        """
        self._stream_callback = stream_callback
        import time

        now = time.time()
        if now - self._last_request_time < self._min_request_interval:
            return {
                "user_input": user_input,
                "ui_message": "⏳ Aguarde um momento antes de enviar outro comando (Rate Limit).",
                "ui_status": "warning",
                "is_complete": True,
            }
        self._last_request_time = now

        initial_state: AgentState = {
            "user_input": user_input,
            "needs_confirmation": False,
            "user_confirmed": False,
            "is_complete": False,
            "retry_count": 0,
            "max_retries": self.max_retries,
            "evaluation_feedback": "",
        }

        result = self.graph.invoke(initial_state)
        from typing import cast

        return cast(AgentState, result)

    def get_resource_snapshot(self) -> dict[str, Any]:
        """Exposto para a UI atualizar indicadores sem acionar o LLM."""
        return self.resource_tool.run()

    def execute_confirmed(self, state: AgentState) -> AgentState:
        """
        Executa um comando que foi confirmado pelo usuário.
        Inclui loop de auto-avaliação com até max_retries tentativas.

        Args:
            state: Estado do grafo com o comando confirmado.

        Returns:
            Estado atualizado com o resultado da execução.
        """
        if state.get("tool_call"):
            return self._execute_confirmed_tool(state)

        user_input = state.get("user_input", "")
        retry_count = 0

        while retry_count <= self.max_retries:
            command = state.get("extracted_command", "")
            self._notify_step(
                "▶ Executando comando..." if retry_count == 0 else f"🔄 Tentativa {retry_count + 1}: executando..."
            )
            log.info("Executando confirmado (tentativa %d): %s", retry_count + 1, command)

            result = execute_command(
                command, timeout=self.command_timeout, vault=self.vault, allow_unsafe=self.unsafe_mode
            )
            state["user_confirmed"] = True
            state["execution_result"] = result

            if result.timed_out:
                state["ui_message"] = f"⏱ Comando excedeu timeout de {self.command_timeout}s."
                state["ui_status"] = "error"
                break

            if result.exit_code == 0:
                output = result.stdout.strip() if result.stdout.strip() else "(sem saída)"
                state["ui_message"] = f"✅ Executado com sucesso:\n\n$ {command}\n\n{output}"
                state["ui_status"] = "success"
            else:
                error_out = result.stderr.strip() if result.stderr.strip() else result.stdout.strip()
                state["ui_message"] = f"❌ Erro (código {result.exit_code}):\n\n$ {command}\n\n{error_out}"
                state["ui_status"] = "error"

            # Auto-avaliação
            if retry_count >= self.max_retries:
                break

            self._notify_step("🧠 Avaliando resultado...")
            stdout = result.stdout.strip() if result.stdout else "(sem saída)"
            stderr = result.stderr.strip() if result.stderr else ""
            eval_message = (
                f"Pedido original do usuário: {user_input}\n"
                f"Comando executado: {command}\n"
                f"Código de saída: {result.exit_code}\n"
                f"Saída: {stdout[:1000]}\n"
                f"Erro: {stderr[:500]}"
            )

            try:
                evaluation = self.llm.invoke(EVALUATION_PROMPT, eval_message)
                log.info("Avaliação confirmada (tentativa %d): %s", retry_count + 1, evaluation[:200])

                if "SATISFATORIO" in evaluation.upper() and "INSATISFATORIO" not in evaluation.upper():
                    break  # Resultado OK
                else:
                    feedback = evaluation.replace("INSATISFATORIO:", "").strip()
                    self._notify_step(f"🔄 Retentando: {feedback[:80]}")
                    log.info("Retentando com feedback: %s", feedback[:200])

                    # Re-consultar LLM com feedback
                    context = state.get("history_context", "")
                    message_parts = [self._system_ctx_str]
                    if context:
                        message_parts.append(context)
                    message_parts.append(f"Solicitação do usuário: {user_input}")
                    message_parts.append(
                        f"\nATENÇÃO: A tentativa anterior falhou.\n"
                        f"Comando: {command}\nErro: {stderr[:300]}\n"
                        f"Feedback: {feedback}\n"
                        f"Gere um comando CORRIGIDO."
                    )
                    full_message = "\n\n".join(message_parts)

                    new_response = self.llm.invoke(SYSTEM_PROMPT, full_message)
                    new_extraction = extract_command(new_response)
                    if new_extraction.success:
                        safety = self.security.validate(new_extraction.command)
                        if safety.category == CommandCategory.BLOCKED:
                            state["ui_message"] = f"Retentativa bloqueada por segurança: {safety.reason}"
                            state["ui_status"] = "blocked"
                            break
                        if safety.category == CommandCategory.NEEDS_CONFIRMATION:
                            state["ui_message"] = (
                                "A retentativa gerou um novo comando que precisa de nova confirmação:\n\n"
                                f"$ {new_extraction.command}\n\n{safety.reason}"
                            )
                            state["ui_status"] = "pending"
                            state["needs_confirmation"] = True
                            break
                        state["extracted_command"] = new_extraction.command
                        state["llm_response"] = new_response
                    else:
                        break  # Não conseguiu gerar um novo comando
            except Exception as e:
                log.warning("Erro na avaliação confirmada: %s", str(e)[:200])
                break

            retry_count += 1

        state["is_complete"] = True

        # Salvar no banco
        self.db.save_command(
            user_input=state.get("user_input", ""),
            llm_response=state.get("llm_response"),
            extracted_command=state.get("extracted_command", ""),
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            confirmed=True,
        )
        self.db.remember_interaction(
            user_input=state.get("user_input", ""),
            extracted_command=state.get("extracted_command", ""),
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            confirmed=True,
        )

        return state

    def _execute_confirmed_tool(self, state: AgentState) -> AgentState:
        """Executa tool nativa mutável já confirmada, com auto-recuperação."""
        tool_call = state.get("tool_call")
        if not tool_call:
            state["ui_message"] = "Tool call ausente."
            state["ui_status"] = "error"
            state["is_complete"] = True
            return state

        self._notify_step(f"Executando tool confirmada {tool_call.tool}.{tool_call.action}...")

        if tool_call.tool == "resource_snapshot":
            snapshot = self.resource_tool.run()
            state["tool_result"] = snapshot
            state["ui_message"] = f"Snapshot de recursos:\n\n{self._resource_json(snapshot)}"
            state["ui_status"] = "success"

            state["user_confirmed"] = True
            state["is_complete"] = True
            extracted = "native:resource_snapshot"
            state["extracted_command"] = extracted
            self.db.save_command(
                user_input=state.get("user_input", ""),
                llm_response=state.get("llm_response"),
                extracted_command=extracted,
                stdout=self._resource_json(snapshot),
                stderr=None,
                exit_code=0,
                confirmed=True,
            )
            return state

        result = self.native_tool.run(tool_call.action, tool_call.args)
        state["tool_result"] = result
        state["user_confirmed"] = True

        extracted = f"native:{tool_call.display_name()}"
        state["extracted_command"] = extracted

        if result.success:
            state["ui_message"] = self._format_tool_result(tool_call, result)
            state["ui_status"] = "success"
            state["is_complete"] = True

            self.db.save_command(
                user_input=state.get("user_input", ""),
                llm_response=state.get("llm_response"),
                extracted_command=extracted,
                stdout=result.to_json(),
                stderr=None,
                exit_code=0,
                confirmed=True,
            )
            return state

        # Falhou. Vamos tentar recuperar gerando um comando alternativo (ex: Bash).
        state["ui_message"] = self._format_tool_result(tool_call, result)
        state["ui_status"] = "warning"

        feedback = f"A ferramenta nativa falhou: {result.error_message}. NÃO USE a ferramenta nativa. Gere um comando BASH ou CLI nativo alternativo que cumpra o mesmo objetivo."
        self._notify_step("🔄 Retentando: Falha na tool nativa. Consultando LLM...")
        log.info("Auto-retentando tool nativa confirmada: %s", feedback)

        user_input = state.get("user_input", "")
        context = state.get("history_context", "")
        message_parts = [self._system_ctx_str]
        if context:
            message_parts.append(context)
        message_parts.append(f"Solicitação do usuário: {user_input}")
        message_parts.append(
            f"\nATENÇÃO: A tentativa anterior falhou.\n"
            f"Ação: {tool_call.action}\nErro: {result.error_message}\n"
            f"Feedback: {feedback}\n"
            f"Gere um comando CORRIGIDO."
        )
        full_message = "\n\n".join(message_parts)

        try:
            new_response = self.llm.invoke(SYSTEM_PROMPT, full_message)
            new_extraction = extract_command(new_response)
            if new_extraction.success:
                safety = self.security.validate(new_extraction.command)
                if safety.category == CommandCategory.BLOCKED:
                    state["ui_message"] = f"Retentativa bloqueada por segurança: {safety.reason}"
                    state["ui_status"] = "blocked"
                    state["is_complete"] = True
                elif safety.category == CommandCategory.NEEDS_CONFIRMATION:
                    state["ui_message"] = (
                        "A retentativa gerou um novo comando que precisa de nova confirmação:\n\n"
                        f"$ {new_extraction.command}\n\n{safety.reason}"
                    )
                    state["ui_status"] = "pending"
                    state["needs_confirmation"] = True
                    state["is_complete"] = False
                    # Remove tool_call so the next execute_confirmed handles it as bash
                    state.pop("tool_call", None)
                    state["extracted_command"] = new_extraction.command
                    state["llm_response"] = new_response
                else:
                    # Execute imediatamente e use o evaluate loop principal se necessário
                    # Para simplificar, configuramos o state para a UI re-acinar execute_confirmed.
                    # Mas como isso precisa de "pending", passamos como pending mesmo sem bloqueio.
                    state["ui_message"] = (
                        "A retentativa gerou um novo comando Bash (automático, mas aguarda confirmação para segurança):\n\n"
                        f"$ {new_extraction.command}"
                    )
                    state["ui_status"] = "pending"
                    state["needs_confirmation"] = True
                    state["is_complete"] = False
                    state.pop("tool_call", None)
                    state["extracted_command"] = new_extraction.command
                    state["llm_response"] = new_response
            else:
                state["is_complete"] = True
        except Exception as e:
            log.warning("Erro na auto-recuperação da tool: %s", str(e)[:200])
            state["is_complete"] = True

        self.db.save_command(
            user_input=state.get("user_input", ""),
            llm_response=state.get("llm_response"),
            extracted_command=extracted,
            stdout=result.to_json(),
            stderr=result.error_message,
            exit_code=1,
            confirmed=True,
        )
        return state
