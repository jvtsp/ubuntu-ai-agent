"""
Ubuntu Agent - Janela principal da aplicação.

Implementa a janela flutuante (CustomTkinter) sem bordas, com campo de input,
área de log, indicador de status e integração com o grafo do agente.
"""

import threading

import customtkinter as ctk

from src.agent.graph import AgentGraph, AgentState
from src.agent.llm import LLMClient
from src.logger import get_logger
from src.ui.components import ConfirmationModal, InputField, LogArea, StatusIndicator

log = get_logger("ui.app")


class UbuntuAgentApp(ctk.CTk):
    """Janela principal do Ubuntu Agent."""

    def __init__(self, agent_graph: AgentGraph, llm_client: LLMClient, config: dict) -> None:
        """
        Inicializa a janela principal.

        Args:
            agent_graph: Grafo do agente para processar comandos.
            llm_client: Cliente LLM para health checks.
            config: Configurações de UI.
        """
        super().__init__()

        self.agent = agent_graph
        self.llm = llm_client
        self.ui_config = config.get("ui", {})
        self._pending_state: AgentState | None = None
        self._is_visible = True
        self._modal_open = False
        self._is_processing = False

        # Registrar callback para acompanhar nós do grafo
        self.agent.set_step_callback(self._on_agent_step)

        log.info("Inicializando janela principal.")

        # ─── Configuração da Janela ──────────────────────────────────────────────
        self.width = self.ui_config.get("width", 700)
        self.title("🐧 Ubuntu Agent")
        self.resizable(True, True)
        self.minsize(500, 200)

        # Tentar definir opacidade (pode não funcionar em Wayland)
        opacity = self.ui_config.get("opacity", 0.95)
        try:
            self.attributes("-alpha", opacity)
        except Exception:
            pass

        # Tema escuro
        ctk.set_appearance_mode("dark")
        self.configure(fg_color=("#1e1e2e", "#1e1e2e"))

        # Posicionar no centro-superior da tela
        self.update_idletasks()
        screen_w = self.winfo_screenwidth()
        x = (screen_w - self.width) // 2
        y = 80  # Margem superior
        self._base_height = 300  # Altura mínima para acomodar as abas
        self.geometry(f"{self.width}x{self._base_height}+{x}+{y}")
        self._x_pos = x
        self._y_pos = y

        # Fonte configurável
        self.font_family = self.ui_config.get("font_family", "JetBrains Mono")
        self.font_size = self.ui_config.get("font_size", 13)
        self.max_log_height = self.ui_config.get("max_log_height", 200)

        # ─── Construir Interface ─────────────────────────────────────────────
        self._build_ui()

        # ─── Bindings ────────────────────────────────────────────────────────
        self.bind("<Escape>", lambda e: self.iconify())  # Minimizar com Esc
        self.bind("<Control-equal>", self._zoom_in)
        self.bind("<Control-plus>", self._zoom_in)
        self.bind("<Control-minus>", self._zoom_out)
        self.bind("<Control-0>", self._zoom_reset)

        # ─── Health check inicial ────────────────────────────────────────────
        self.after(500, self._check_llm_status)

        # ─── Health check periódico ──────────────────────────────────────────
        self._schedule_health_check()

        # ─── Fade-in ─────────────────────────────────────────────────────────
        self._fade_in()

    def _build_ui(self) -> None:
        """Constrói os componentes da interface."""
        # Container principal
        self.main_frame = ctk.CTkFrame(
            self,
            fg_color=("#1e1e2e", "#1e1e2e"),
            corner_radius=16,
            border_width=1,
            border_color=("#313244", "#313244"),
        )
        self.main_frame.pack(fill="both", expand=True, padx=2, pady=2)

        # Header com título e status
        header = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(10, 0))

        title = ctk.CTkLabel(
            header,
            text="🐧 Ubuntu Agent",
            font=ctk.CTkFont(family=self.font_family, size=14, weight="bold"),
            text_color=("#89b4fa", "#89b4fa"),
        )
        title.pack(side="left")

        # Botão limpar histórico
        clear_btn = ctk.CTkButton(
            header,
            text="🗑",
            width=30,
            height=25,
            corner_radius=8,
            fg_color="transparent",
            hover_color=("#313244", "#313244"),
            font=ctk.CTkFont(size=14),
            command=self._clear_log,
        )
        clear_btn.pack(side="right", padx=(5, 0))

        # Botão de configurações
        settings_btn = ctk.CTkButton(
            header,
            text="⚙",
            width=30,
            height=25,
            corner_radius=8,
            fg_color="transparent",
            hover_color=("#313244", "#313244"),
            font=ctk.CTkFont(size=14),
            command=self._open_settings,
        )
        settings_btn.pack(side="right", padx=(5, 0))

        self.status = StatusIndicator(header)
        self.status.pack(side="right")

        # ─── Área Principal do Terminal ──────────────────────────────────────
        terminal_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        terminal_frame.pack(fill="both", expand=True, padx=8, pady=(5, 8))

        self.log_area = LogArea(
            terminal_frame,
            max_height=self.max_log_height,
            font_family=self.font_family,
            font_size=self.font_size,
        )
        self.log_area.pack(fill="both", expand=True, pady=(0, 5))

        self.input_field = InputField(
            terminal_frame,
            placeholder="Digite um comando em português...",
            on_submit=self._on_submit,
            font_family=self.font_family,
            font_size=self.font_size,
        )
        self.input_field.pack(fill="x", side="bottom")

        # Rodapé de info (Atalhos e Tokens)
        footer = ctk.CTkFrame(terminal_frame, fg_color="transparent", height=20)
        footer.pack(fill="x", side="bottom", pady=(2, 0))

        hint = ctk.CTkLabel(
            footer,
            text="Zoom: Ctrl + / -  |  Enter ↵ enviar",
            font=ctk.CTkFont(size=10),
            text_color=("#6c7086", "#6c7086"),
        )
        hint.pack(side="left")

        self.token_label = ctk.CTkLabel(
            footer,
            text="📊 Tokens: 0",
            font=ctk.CTkFont(size=10),
            text_color=("#6c7086", "#6c7086"),
        )
        self.token_label.pack(side="right")

    def _open_settings(self) -> None:
        """Abre uma janela modal com as configurações (substituindo a antiga aba)."""
        settings_window = ctk.CTkToplevel(self)
        settings_window.title("Configurações")
        settings_window.geometry("450x300")
        settings_window.resizable(False, False)
        settings_window.transient(self)
        settings_window.grab_set()

        # Frame principal do settings
        frame = ctk.CTkFrame(settings_window, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        self._build_settings_tab(frame)

    def _zoom_in(self, event=None):
        current = ctk.ScalingTracker.get_widget_scaling()
        ctk.set_widget_scaling(current + 0.1)

    def _zoom_out(self, event=None):
        current = ctk.ScalingTracker.get_widget_scaling()
        if current > 0.5:
            ctk.set_widget_scaling(current - 0.1)

    def _zoom_reset(self, event=None):
        ctk.set_widget_scaling(1.0)

    def _build_settings_tab(self, parent: ctk.CTkFrame) -> None:
        """Constrói o painel de configurações (agora no modal)."""
        # Seção: Endpoint
        endpoint_label = ctk.CTkLabel(
            parent,
            text="🌐 Endpoint do LLM",
            font=ctk.CTkFont(family=self.font_family, size=13, weight="bold"),
            text_color=("#89b4fa", "#89b4fa"),
            anchor="w",
        )
        endpoint_label.pack(fill="x", padx=12, pady=(10, 4))

        endpoint_frame = ctk.CTkFrame(parent, fg_color="transparent")
        endpoint_frame.pack(fill="x", padx=12, pady=(0, 8))

        self._endpoint_var = ctk.StringVar(value=self.llm.base_url)
        endpoint_entry = ctk.CTkEntry(
            endpoint_frame,
            textvariable=self._endpoint_var,
            font=ctk.CTkFont(family=self.font_family, size=12),
            height=35,
            corner_radius=8,
            fg_color=("#181825", "#181825"),
            border_color=("#4a4a5e", "#4a4a5e"),
            text_color=("#cdd6f4", "#cdd6f4"),
        )
        endpoint_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        apply_endpoint_btn = ctk.CTkButton(
            endpoint_frame,
            text="Aplicar",
            width=80,
            height=35,
            corner_radius=8,
            fg_color=("#89b4fa", "#89b4fa"),
            hover_color=("#74c7ec", "#74c7ec"),
            text_color=("#1e1e2e", "#1e1e2e"),
            font=ctk.CTkFont(family=self.font_family, size=12, weight="bold"),
            command=self._apply_endpoint,
        )
        apply_endpoint_btn.pack(side="right")

        # Seção: Modelo
        model_label = ctk.CTkLabel(
            parent,
            text="🤖 Modelo Ativo",
            font=ctk.CTkFont(family=self.font_family, size=13, weight="bold"),
            text_color=("#89b4fa", "#89b4fa"),
            anchor="w",
        )
        model_label.pack(fill="x", padx=12, pady=(8, 4))

        self._model_info_label = ctk.CTkLabel(
            parent,
            text=f"Modelo atual: {self.llm.model}",
            font=ctk.CTkFont(family=self.font_family, size=11),
            text_color=("#a6adc8", "#a6adc8"),
            anchor="w",
        )
        self._model_info_label.pack(fill="x", padx=12, pady=(0, 6))

        # Frame com dropdown e botão de refresh
        model_frame = ctk.CTkFrame(parent, fg_color="transparent")
        model_frame.pack(fill="x", padx=12, pady=(0, 8))

        self._model_var = ctk.StringVar(value=self.llm.model)
        self._model_dropdown = ctk.CTkComboBox(
            model_frame,
            variable=self._model_var,
            values=[self.llm.model],
            font=ctk.CTkFont(family=self.font_family, size=12),
            dropdown_font=ctk.CTkFont(family=self.font_family, size=12),
            height=35,
            corner_radius=8,
            fg_color=("#181825", "#181825"),
            border_color=("#4a4a5e", "#4a4a5e"),
            button_color=("#4a4a5e", "#4a4a5e"),
            button_hover_color=("#585b70", "#585b70"),
            dropdown_fg_color=("#181825", "#181825"),
            dropdown_hover_color=("#313244", "#313244"),
            text_color=("#cdd6f4", "#cdd6f4"),
            dropdown_text_color=("#cdd6f4", "#cdd6f4"),
            state="readonly",
        )
        self._model_dropdown.pack(side="left", fill="x", expand=True, padx=(0, 8))

        refresh_btn = ctk.CTkButton(
            model_frame,
            text="🔄",
            width=40,
            height=35,
            corner_radius=8,
            fg_color=("#313244", "#313244"),
            hover_color=("#45475a", "#45475a"),
            font=ctk.CTkFont(size=16),
            command=self._refresh_models,
        )
        refresh_btn.pack(side="right", padx=(0, 8))

        apply_model_btn = ctk.CTkButton(
            model_frame,
            text="Usar",
            width=80,
            height=35,
            corner_radius=8,
            fg_color=("#a6e3a1", "#a6e3a1"),
            hover_color=("#94e2d5", "#94e2d5"),
            text_color=("#1e1e2e", "#1e1e2e"),
            font=ctk.CTkFont(family=self.font_family, size=12, weight="bold"),
            command=self._apply_model,
        )
        apply_model_btn.pack(side="right")

        # Status label
        self._settings_status = ctk.CTkLabel(
            parent,
            text="",
            font=ctk.CTkFont(family=self.font_family, size=11),
            text_color=("#a6e3a1", "#a6e3a1"),
            anchor="w",
        )
        self._settings_status.pack(fill="x", padx=12, pady=(0, 8))

        # Carregar modelos na inicialização
        self.after(1000, self._refresh_models)

    def _refresh_models(self) -> None:
        """Busca os modelos disponíveis no Ollama e atualiza o dropdown."""
        import threading
        def fetch():
            models = self.llm.list_models()
            names = [m["name"] for m in models]
            if not names:
                names = [self.llm.model]
            self.after(0, lambda: self._update_model_dropdown(names, models))
        threading.Thread(target=fetch, daemon=True).start()

    def _update_model_dropdown(self, names: list[str], models: list[dict]) -> None:
        """Atualiza o dropdown com os nomes dos modelos."""
        self._model_dropdown.configure(values=names)
        if self.llm.model in names:
            self._model_var.set(self.llm.model)
        elif names:
            self._model_var.set(names[0])

        # Mostrar info dos modelos
        info_parts = [f"{m['name']} ({m['size']})" for m in models[:5]]
        if info_parts:
            self._settings_status.configure(
                text=f"✓ {len(models)} modelo(s) disponível(is)",
                text_color=("#a6e3a1", "#a6e3a1"),
            )
        else:
            self._settings_status.configure(
                text="⚠ Não foi possível listar modelos",
                text_color=("#f9e2af", "#f9e2af"),
            )
        log.info("Modelos disponíveis: %s", [m['name'] for m in models])

    def _apply_model(self) -> None:
        """Aplica o modelo selecionado."""
        new_model = self._model_var.get()
        if new_model and new_model != self.llm.model:
            old = self.llm.model
            self.llm.set_model(new_model)
            self._model_info_label.configure(text=f"Modelo atual: {new_model}")
            self._settings_status.configure(
                text=f"✓ Modelo trocado: {old} → {new_model}",
                text_color=("#a6e3a1", "#a6e3a1"),
            )
            log.info("Modelo trocado: %s → %s", old, new_model)
        else:
            self._settings_status.configure(
                text=f"Modelo já ativo: {new_model}",
                text_color=("#f9e2af", "#f9e2af"),
            )

    def _apply_endpoint(self) -> None:
        """Aplica o novo endpoint."""
        new_url = self._endpoint_var.get().strip()
        if new_url and new_url != self.llm.base_url:
            old = self.llm.base_url
            self.llm.set_endpoint(new_url)
            self._settings_status.configure(
                text="✓ Endpoint alterado. Recarregando modelos...",
                text_color=("#a6e3a1", "#a6e3a1"),
            )
            log.info("Endpoint trocado: %s → %s", old, new_url)
            self.after(500, self._refresh_models)
        else:
            self._settings_status.configure(
                text="Endpoint já ativo.",
                text_color=("#f9e2af", "#f9e2af"),
            )

    def _on_agent_step(self, message: str) -> None:
        """Callback chamado pelo grafo para mostrar passos na UI."""
        self.after(0, lambda m=message: self.log_area.add_message(m, "info"))

    def _on_submit(self, text: str) -> None:
        """
        Processa o submit do campo de input.
        Executa o grafo do agente em uma thread separada.

        Args:
            text: Texto digitado pelo usuário.
        """
        self.input_field.clear()
        self.input_field.set_enabled(False)
        self._is_processing = True
        self.status.set_status("processing")
        self.log_area.add_message(f"🔍 {text}", "info")
        log.info("Usuário submeteu: %s", text)

        # Executar em thread separada para não bloquear a UI
        thread = threading.Thread(target=self._run_agent, args=(text,), daemon=True)
        thread.start()

    def _run_agent(self, user_input: str) -> None:
        """
        Executa o grafo do agente em background.

        Args:
            user_input: Texto do usuário.
        """
        try:
            # Prepara a primeira mensagem do streaming
            self.after(0, lambda: self.log_area.add_message("🤖 Raciocínio LLM:\n", "system"))

            # Conta tokens de entrada
            in_tokens = self.llm.count_tokens(user_input)
            self.after(0, lambda: self.token_label.configure(text=f"📊 Tokens: {in_tokens} In | ... Out"))

            stream_state: dict[str, object] = {"in_code": False, "buffer": ""}

            def on_token(token: str):
                stream_state["buffer"] = str(stream_state["buffer"]) + token
                buf = str(stream_state["buffer"])

                # Detecção simples de bloco de código markdown
                if not stream_state["in_code"] and "```" in buf:
                    stream_state["in_code"] = True
                    stream_state["buffer"] = ""
                elif stream_state["in_code"] and "```" in buf:
                    stream_state["in_code"] = False
                    stream_state["buffer"] = ""

                tag = "code" if stream_state["in_code"] else "thought"
                self.after(0, lambda t=token, tg=tag: self.log_area.append_text(t, (tg,)))

            result = self.agent.run(user_input, stream_callback=on_token)

            # Atualiza tokens totais
            out_tokens = self.llm.count_tokens(result.get("llm_response", ""))
            self.after(0, lambda: self.token_label.configure(text=f"📊 Tokens: {in_tokens} In | {out_tokens} Out"))

            # Adiciona uma quebra de linha ao final do streaming
            self.after(0, lambda: self.log_area.append_text("\n"))

            # Atualizar UI na thread principal
            self.after(0, self._handle_agent_result, result)
        except Exception as e:
            log.exception("Erro ao executar agente para input: %s", user_input)
            error_msg = f"⚠ Erro interno: {str(e)[:300]}"
            self.after(0, self._show_result, error_msg, "error")

    def _handle_agent_result(self, state: AgentState) -> None:
        """
        Processa o resultado do grafo do agente na thread principal.

        Args:
            state: Estado final do grafo.
        """
        ui_message = state.get("ui_message", "")
        ui_status = state.get("ui_status", "info")
        needs_confirmation = state.get("needs_confirmation", False)
        log.debug("Resultado do agente: status=%s, needs_confirmation=%s", ui_status, needs_confirmation)

        if needs_confirmation and not state.get("is_complete", True):
            # Mostrar modal de confirmação
            self._modal_open = True
            self._pending_state = state
            command = state.get("extracted_command", "")
            log.info("Solicitar confirmação para: %s", command)
            safety = state.get("safety_result")
            reason = safety.reason if safety else ""

            ConfirmationModal(
                self,
                command=command,
                reason=reason,
                on_confirm=self._on_confirm,
                on_reject=self._on_reject,
                font_family=self.font_family,
            )
        else:
            self._show_result(ui_message, ui_status)

    def _on_confirm(self) -> None:
        """Callback quando o usuário confirma a execução de um comando."""
        self._modal_open = False
        if not self._pending_state:
            return

        state = self._pending_state
        self._pending_state = None
        self._is_processing = True
        self.status.set_status("processing")
        log.info("Usuário confirmou execução do comando.")
        self.log_area.add_message("✓ Confirmado. Executando...", "info")

        # Executar em thread separada
        thread = threading.Thread(
            target=self._execute_confirmed, args=(state,), daemon=True
        )
        thread.start()

    def _execute_confirmed(self, state: AgentState) -> None:
        """Executa o comando confirmado em background."""
        try:
            result = self.agent.execute_confirmed(state)
            ui_message = result.get("ui_message", "")
            ui_status = result.get("ui_status", "info")
            log.info("Comando confirmado executado: status=%s", ui_status)
            self.after(0, self._show_result, ui_message, ui_status)
        except Exception as e:
            log.exception("Erro ao executar comando confirmado.")
            self.after(0, self._show_result, f"⚠ Erro: {str(e)[:300]}", "error")

    def _on_reject(self) -> None:
        """Callback quando o usuário rejeita a execução."""
        self._modal_open = False
        self._is_processing = False
        self._pending_state = None
        log.info("Usuário rejeitou execução do comando.")
        self._show_result("✕ Execução cancelada pelo usuário.", "warning")

    def _show_result(self, message: str, status: str = "info") -> None:
        """
        Exibe um resultado na área de log e atualiza o status.

        Args:
            message: Mensagem a exibir.
            status: Tipo de status.
        """
        if message:
            self.log_area.add_message(message, status)

        self._is_processing = False
        self.input_field.set_enabled(True)
        self.input_field.focus_input()
        log.debug("Resultado exibido na UI: status=%s", status)

        # Atualizar indicador de status baseado no resultado
        if status in ("error", "blocked"):
            self.status.set_status("online")  # LLM funciona, só deu erro
        else:
            self.status.set_status("online")

        # Ajustar altura da janela
        self._adjust_height()

    def _adjust_height(self) -> None:
        """Ajusta a altura da janela baseado no conteúdo."""
        self.update_idletasks()
        needed = self.main_frame.winfo_reqheight() + 10
        max_h = self._base_height + self.max_log_height + 80
        new_h = min(max(needed, self._base_height), max_h)
        self.geometry(f"{self.width}x{new_h}+{self._x_pos}+{self._y_pos}")

    def _clear_log(self) -> None:
        """Limpa a área de log."""
        self.log_area.clear()
        self._adjust_height()
        self.geometry(f"{self.width}x{self._base_height}+{self._x_pos}+{self._y_pos}")

    def _check_llm_status(self) -> None:
        """Verifica o status do LLM em background."""
        def check():
            is_online = self.llm.health_check()
            self.after(0, lambda: self.status.set_status("online" if is_online else "offline"))
        thread = threading.Thread(target=check, daemon=True)
        thread.start()

    def _schedule_health_check(self) -> None:
        """Agenda verificações periódicas do status do LLM."""
        self._check_llm_status()
        self.after(30000, self._schedule_health_check)  # A cada 30s

    def _fade_in(self) -> None:
        """Animação sutil de fade-in ao aparecer."""
        try:
            self.attributes("-alpha", 0.0)
            self._fade_step(0.0)
        except Exception:
            # Wayland pode não suportar alpha
            pass

    def _fade_step(self, alpha: float) -> None:
        """Step da animação de fade-in."""
        target = self.ui_config.get("opacity", 0.95)
        if alpha < target:
            alpha = min(alpha + 0.08, target)
            try:
                self.attributes("-alpha", alpha)
            except Exception:
                return
            self.after(20, self._fade_step, alpha)

    def _on_focus_out(self, event=None) -> None:
        """Evento de perda de foco — nenhuma ação necessária para janela normal."""
        pass

    def _check_focus(self) -> None:
        """Verificação de foco — desativada para janela normal."""
        pass

    def hide_window(self) -> None:
        """Minimiza a janela."""
        log.debug("Janela minimizada.")
        self._is_visible = False
        self.iconify()

    def show_window(self) -> None:
        """Mostra/restaura a janela."""
        log.debug("Janela restaurada.")
        self._is_visible = True
        self.deiconify()
        self.focus_force()
        self.input_field.focus_input()
        self.lift()

    def toggle_window(self) -> None:
        """Alterna a visibilidade da janela."""
        if self._is_visible:
            self.hide_window()
        else:
            self.show_window()

    @property
    def is_visible(self) -> bool:
        """Retorna se a janela está visível."""
        return self._is_visible
