"""
Ubuntu Agent - Definição do grafo LangGraph.

Implementa o fluxo completo do agente com nós condicionais:
receber_input → consultar_llm → extrair_comando → validar_seguranca →
solicitar_confirmacao / bloquear_cmd / executar_comando → atualizar_ui
"""

from typing import TypedDict, Optional, Literal
from langgraph.graph import StateGraph, END

from src.agent.prompts import SYSTEM_PROMPT, EVALUATION_PROMPT, build_context_messages
from src.agent.llm import LLMClient
from src.executor.bash import extract_command, execute_command, ExtractionResult, ExecutionResult
from src.executor.safety import SecurityValidator, CommandCategory, SafetyResult
from src.storage.database import Database
from src.system.context import collect_system_context, format_system_context
from src.logger import get_logger

log = get_logger("agent.graph")


class AgentState(TypedDict, total=False):
    """Estado compartilhado entre os nós do grafo."""
    # Input
    user_input: str
    history_context: str

    # LLM
    llm_response: str
    llm_error: str

    # Extração
    extraction: ExtractionResult
    extracted_command: str

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

    def __init__(self, llm_client: LLMClient, security: SecurityValidator, db: Database, config: dict, vault=None) -> None:
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
        self.command_timeout = config.get("security", {}).get("command_timeout", 60)
        self.max_retries = config.get("agent", {}).get("max_retries", 2)
        self._step_callback = None  # Callback para UI acompanhar nós

        # Coletar contexto do sistema uma vez
        self._system_ctx = collect_system_context()
        self._system_ctx_str = format_system_context(self._system_ctx)
        log.info("Contexto do sistema coletado: desktop=%s", self._system_ctx.get("desktop"))

        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Constrói o grafo LangGraph com todos os nós e edges."""
        graph = StateGraph(AgentState)

        # Adicionar nós
        graph.add_node("receber_input", self._receber_input)
        graph.add_node("consultar_llm", self._consultar_llm)
        graph.add_node("extrair_comando", self._extrair_comando)
        graph.add_node("solicitar_clarifica", self._solicitar_clarifica)
        graph.add_node("validar_seguranca", self._validar_seguranca)
        graph.add_node("bloquear_cmd", self._bloquear_cmd)
        graph.add_node("preparar_confirmacao", self._preparar_confirmacao)
        graph.add_node("executar_comando", self._executar_comando)
        graph.add_node("avaliar_resultado", self._avaliar_resultado)
        graph.add_node("atualizar_ui", self._atualizar_ui)

        # Definir ponto de entrada
        graph.set_entry_point("receber_input")

        # Edges lineares
        graph.add_edge("receber_input", "consultar_llm")

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
                "valid": "validar_seguranca",
                "invalid": "solicitar_clarifica",
            },
        )

        # Clarificação vai direto para atualizar_ui
        graph.add_edge("solicitar_clarifica", "atualizar_ui")

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

    def _receber_input(self, state: AgentState) -> dict:
        """Captura o input do usuário e carrega o contexto do histórico."""
        history = self.db.get_last_n(self.max_context)
        context = build_context_messages(history)
        return {"history_context": context}

    def _consultar_llm(self, state: AgentState) -> dict:
        """Envia o input + contexto ao LLM."""
        user_input = state.get("user_input", "")
        context = state.get("history_context", "")
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
        if context:
            message_parts.append(context)
        message_parts.append(f"Solicitação do usuário: {user_input}")
        if feedback:
            message_parts.append(f"\nATENÇÃO: A tentativa anterior foi insatisfatória. Feedback: {feedback}\nGere um comando MELHOR que realmente atenda ao pedido.")
        full_message = "\n\n".join(message_parts)

        try:
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
        """Extrai o comando Bash da resposta do LLM."""
        llm_response = state.get("llm_response", "")
        result = extract_command(llm_response)
        log.info("Extração: success=%s, command='%s'", result.success, result.command[:100] if result.command else '')
        return {
            "extraction": result,
            "extracted_command": result.command if result.success else "",
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
        log.info("Segurança: category=%s, is_safe=%s, reason='%s'", result.category.value, result.is_safe, result.reason)
        return {"safety_result": result}

    def _bloquear_cmd(self, state: AgentState) -> dict:
        """Bloqueia o comando e informa o motivo."""
        safety = state.get("safety_result")
        reason = safety.reason if safety else "Motivo desconhecido"
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

        result = execute_command(command, timeout=self.command_timeout, vault=self.vault)
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
        
        # Se o comando deu timeout, não avaliar
        if execution and execution.timed_out:
            return {"is_complete": True}

        # Se já atingiu máximo de retentativas
        if retry_count >= self.max_retries:
            log.info("Máximo de retentativas (%d) atingido.", self.max_retries)
            return {"is_complete": True}

        self._notify_step("🧠 Avaliando resultado...")

        stdout = execution.stdout.strip() if execution and execution.stdout else "(sem saída)"
        exit_code = execution.exit_code if execution else -1

        eval_message = (
            f"Pedido original do usuário: {user_input}\n"
            f"Comando executado: {command}\n"
            f"Código de saída: {exit_code}\n"
            f"Saída do comando: {stdout[:1000]}"
        )

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
        confirmed = state.get("user_confirmed", False)

        self.db.save_command(
            user_input=user_input,
            llm_response=llm_response,
            extracted_command=extracted,
            stdout=execution.stdout if execution else None,
            stderr=execution.stderr if execution else None,
            exit_code=execution.exit_code if execution else None,
            confirmed=confirmed,
        )
        # Preservar is_complete=False se veio de preparar_confirmacao
        # para que a UI consiga abrir o modal de confirmação
        if state.get("needs_confirmation", False):
            log.debug("Confirmação pendente — preservando is_complete=False.")
            return {}
        return {"is_complete": True}

    # ─── Funções de Roteamento (Edges Condicionais) ──────────────────────────

    def _check_llm_result(self, state: AgentState) -> Literal["success", "error"]:
        """Verifica se a consulta ao LLM foi bem-sucedida."""
        if state.get("llm_error"):
            return "error"
        return "success"

    def _check_extraction(self, state: AgentState) -> Literal["valid", "invalid"]:
        """Verifica se a extração do comando foi bem-sucedida."""
        extraction = state.get("extraction")
        if extraction and extraction.success:
            return "valid"
        return "invalid"

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

    def run(self, user_input: str) -> AgentState:
        """
        Executa o grafo completo para um input do usuário.

        Args:
            user_input: Texto em linguagem natural do usuário.

        Returns:
            Estado final do grafo com resultados.
        """
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
        return result

    def execute_confirmed(self, state: AgentState) -> AgentState:
        """
        Executa um comando que foi confirmado pelo usuário.
        Inclui loop de auto-avaliação com até max_retries tentativas.

        Args:
            state: Estado do grafo com o comando confirmado.

        Returns:
            Estado atualizado com o resultado da execução.
        """
        user_input = state.get("user_input", "")
        retry_count = 0

        while retry_count <= self.max_retries:
            command = state.get("extracted_command", "")
            self._notify_step(f"▶ Executando comando..." if retry_count == 0 else f"🔄 Tentativa {retry_count + 1}: executando...")
            log.info("Executando confirmado (tentativa %d): %s", retry_count + 1, command)

            result = execute_command(command, timeout=self.command_timeout, vault=self.vault)
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

        return state
