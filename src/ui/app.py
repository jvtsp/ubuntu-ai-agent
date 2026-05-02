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
from src.ui.components import YARU, ConfirmationModal, InputField, LogArea, ResourceStrip, StatusIndicator

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
        self._is_expanded = False

        # Registrar callback para acompanhar nós do grafo
        self.agent.set_step_callback(self._on_agent_step)

        log.info("Inicializando janela principal.")

        # ─── Configuração da Janela ──────────────────────────────────────────────
        self.width = self.ui_config.get("width", 760)
        self.title("Ubuntu Agent")
        self.resizable(True, True)
        self.minsize(400, 80)

        # Tentar definir opacidade (pode não funcionar em Wayland)
        opacity = self.ui_config.get("opacity", 0.95)
        import contextlib

        with contextlib.suppress(Exception):
            self.attributes("-alpha", opacity)

        # Tema padrão adaptável ao sistema
        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        # Posicionar no centro-superior da tela
        self.update_idletasks()
        screen_w = self.winfo_screenwidth()
        x = (screen_w - self.width) // 2
        y = int(self.winfo_screenheight() * 0.2)  # 20% do topo da tela para a barra de busca

        # Alturas da UI
        self._base_height = 92  # Barra inicial
        self._expanded_height = 520  # Janela expandida

        self.geometry(f"{self.width}x{self._base_height}+{x}+{y}")
        self._x_pos = x
        self._y_pos = y

        # Fonte configurável
        self.font_family = self.ui_config.get("font_family", "JetBrains Mono")
        self.font_size = self.ui_config.get("font_size", 14)
        self.max_log_height = self.ui_config.get("max_log_height", 400)

        # ─── Construir Interface ─────────────────────────────────────────────
        self._build_ui()
        self._schedule_resource_refresh()

        # ─── Bindings ────────────────────────────────────────────────────────
        self.bind("<Escape>", lambda e: self.iconify())  # Minimizar com Esc
        self.bind("<Control-equal>", self._zoom_in)
        self.bind("<Control-plus>", self._zoom_in)
        self.bind("<Control-minus>", self._zoom_out)
        self.bind("<Control-0>", self._zoom_reset)
        self.bind("<Configure>", self._on_resize)

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
            corner_radius=8,
            border_width=1,
            border_color=(YARU["border_light"], YARU["border_dark"]),
            fg_color=(YARU["surface_light"], YARU["surface_dark"]),
        )
        self.main_frame.pack(fill="both", expand=True, padx=2, pady=2)

        # Container interno centralizável para limitar a largura (estilo web chat)
        self.content_container = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.content_container.pack(fill="both", expand=True, padx=8, pady=8)

        # --- Componentes (Header, Log, Footer, Input) ---

        # Header com título, status e ações
        self.header = ctk.CTkFrame(self.content_container, fg_color="transparent")

        title_box = ctk.CTkFrame(self.header, fg_color="transparent")
        title_box.pack(side="left", fill="x", expand=True)

        title = ctk.CTkLabel(
            title_box,
            text="Ubuntu Agent",
            font=ctk.CTkFont(family=self.font_family, size=16, weight="bold"),
            anchor="w",
        )
        title.pack(fill="x", anchor="w")

        subtitle = ctk.CTkLabel(
            title_box,
            text="co-operador sysadmin local",
            font=ctk.CTkFont(family=self.font_family, size=10),
            text_color=(YARU["text_muted_light"], YARU["text_muted_dark"]),
            anchor="w",
        )
        subtitle.pack(fill="x", anchor="w")

        clear_btn = ctk.CTkButton(
            self.header,
            text="Limpar",
            width=64,
            height=30,
            corner_radius=6,
            fg_color="transparent",
            border_width=1,
            border_color=(YARU["border_light"], YARU["border_dark"]),
            text_color=(YARU["text_muted_light"], YARU["text_muted_dark"]),
            font=ctk.CTkFont(family=self.font_family, size=11),
            command=self._clear_log,
        )
        clear_btn.pack(side="right", padx=(5, 0))

        settings_btn = ctk.CTkButton(
            self.header,
            text="Ajustes",
            width=70,
            height=30,
            corner_radius=6,
            fg_color=(YARU["accent"], "#FF6B35"),
            hover_color=(YARU["accent_hover"], "#E95420"),
            font=ctk.CTkFont(family=self.font_family, size=11, weight="bold"),
            command=self._open_settings,
        )
        settings_btn.pack(side="right", padx=(5, 0))

        self.status = StatusIndicator(self.header)
        self.status.pack(side="right")

        self.resource_strip = ResourceStrip(self.content_container, font_family=self.font_family)

        # Log Area
        self.log_area = LogArea(
            self.content_container,
            max_height=self.max_log_height,
            font_family=self.font_family,
            font_size=self.font_size,
        )

        # Footer
        self.footer = ctk.CTkFrame(self.content_container, fg_color="transparent", height=20)
        hint = ctk.CTkLabel(
            self.footer,
            text="Enter envia · Esc minimiza · Ctrl +/- ajusta zoom",
            font=ctk.CTkFont(size=10),
            text_color=(YARU["text_muted_light"], YARU["text_muted_dark"]),
        )
        hint.pack(side="left")

        self.token_label = ctk.CTkLabel(
            self.footer,
            text="Tokens: 0",
            font=ctk.CTkFont(size=10),
            text_color=(YARU["text_muted_light"], YARU["text_muted_dark"]),
        )
        self.token_label.pack(side="right")

        # Input Field
        self.input_field = InputField(
            self.content_container,
            placeholder="Peça um diagnóstico, ajuste de serviço, rede ou pacote...",
            on_submit=self._on_submit,
            font_family=self.font_family,
            font_size=self.font_size,
        )

        # Layout inicial: Apenas o input_field
        self.input_field.pack(fill="x", side="top", padx=10, pady=5)

    def _expand_ui(self) -> None:
        """Expande a janela para o modo Chat após o primeiro uso."""
        if not self._is_expanded:
            self._is_expanded = True

            # Limpa o layout atual do content_container
            self.input_field.pack_forget()

            # Empacota no formato chat
            self.header.pack(fill="x", side="top", padx=12, pady=(5, 0))
            self.resource_strip.pack(fill="x", side="top", padx=12, pady=(8, 10))
            self.footer.pack(fill="x", side="bottom", padx=12, pady=(2, 5))
            self.input_field.pack(fill="x", side="bottom", padx=12, pady=(0, 5))
            # O LogArea fará o pack dele mesmo no _update_visibility

            # Ajustar altura
            self.minsize(500, 300)
            self.geometry(f"{self.width}x{self._expanded_height}+{self._x_pos}+{self._y_pos}")

    def _on_resize(self, event) -> None:
        """Garante que a UI fique centralizada (max-width) se for muito larga."""
        if getattr(event, "widget", None) is self:
            w = event.width
            max_content_width = 850

            # Se a janela passou do limite, fixamos a largura do content e centramos
            if w > max_content_width + 40:
                self.content_container.pack_configure(fill="y", expand=True)
                self.content_container.configure(width=max_content_width)
                self.content_container.pack_propagate(False)
            else:
                self.content_container.pack_configure(fill="both", expand=True)
                self.content_container.pack_propagate(True)

    def _open_settings(self) -> None:
        """Abre uma janela modal com as configurações."""
        settings_window = ctk.CTkToplevel(self)
        settings_window.title("Configurações")
        settings_window.geometry("450x400")
        settings_window.resizable(False, False)
        settings_window.transient(self)

        frame = ctk.CTkFrame(
            settings_window,
            fg_color=(YARU["surface_light"], YARU["surface_dark"]),
            corner_radius=8,
        )
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        self._build_settings_tab(frame)

        settings_window.wait_visibility()
        settings_window.grab_set()

    def _zoom_in(self, event=None):
        current = ctk.ScalingTracker.get_widget_scaling(self)
        ctk.set_widget_scaling(current + 0.1)

    def _zoom_out(self, event=None):
        current = ctk.ScalingTracker.get_widget_scaling(self)
        if current > 0.5:
            ctk.set_widget_scaling(current - 0.1)

    def _zoom_reset(self, event=None):
        ctk.set_widget_scaling(1.0)

    def _build_settings_tab(self, parent: ctk.CTkFrame) -> None:
        """Constrói o painel de configurações."""
        # Seção: Temas
        theme_label = ctk.CTkLabel(
            parent,
            text="🎨 Aparência",
            font=ctk.CTkFont(family=self.font_family, size=13, weight="bold"),
            anchor="w",
        )
        theme_label.pack(fill="x", padx=12, pady=(10, 4))

        theme_frame = ctk.CTkFrame(parent, fg_color="transparent")
        theme_frame.pack(fill="x", padx=12, pady=(0, 8))

        self._appearance_mode_var = ctk.StringVar(value=ctk.get_appearance_mode())
        appearance_dropdown = ctk.CTkComboBox(
            theme_frame,
            variable=self._appearance_mode_var,
            values=["System", "Light", "Dark"],
            font=ctk.CTkFont(family=self.font_family, size=12),
            height=35,
            corner_radius=8,
            command=self._change_appearance_mode,
            state="readonly",
        )
        appearance_dropdown.pack(side="left", fill="x", expand=True, padx=(0, 8))

        # Seção: Endpoint
        endpoint_label = ctk.CTkLabel(
            parent,
            text="🌐 Endpoint do LLM",
            font=ctk.CTkFont(family=self.font_family, size=13, weight="bold"),
            anchor="w",
        )
        endpoint_label.pack(fill="x", padx=12, pady=(15, 4))

        endpoint_frame = ctk.CTkFrame(parent, fg_color="transparent")
        endpoint_frame.pack(fill="x", padx=12, pady=(0, 8))

        self._endpoint_var = ctk.StringVar(value=self.llm.base_url)
        endpoint_entry = ctk.CTkEntry(
            endpoint_frame,
            textvariable=self._endpoint_var,
            font=ctk.CTkFont(family=self.font_family, size=12),
            height=35,
            corner_radius=8,
            fg_color=(YARU["panel_light"], YARU["panel_dark"]),
        )
        endpoint_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        apply_endpoint_btn = ctk.CTkButton(
            endpoint_frame,
            text="Aplicar",
            width=80,
            height=35,
            corner_radius=8,
            font=ctk.CTkFont(family=self.font_family, size=12, weight="bold"),
            command=self._apply_endpoint,
        )
        apply_endpoint_btn.pack(side="right")

        # Seção: Modelo
        model_label = ctk.CTkLabel(
            parent,
            text="🤖 Modelo Ativo",
            font=ctk.CTkFont(family=self.font_family, size=13, weight="bold"),
            anchor="w",
        )
        model_label.pack(fill="x", padx=12, pady=(15, 4))

        self._model_info_label = ctk.CTkLabel(
            parent,
            text=f"Modelo atual: {self.llm.model}",
            font=ctk.CTkFont(family=self.font_family, size=11),
            text_color=("gray50", "gray60"),
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
            height=35,
            corner_radius=8,
            state="readonly",
        )
        self._model_dropdown.pack(side="left", fill="x", expand=True, padx=(0, 8))

        refresh_btn = ctk.CTkButton(
            model_frame,
            text="🔄",
            width=40,
            height=35,
            corner_radius=8,
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
            font=ctk.CTkFont(family=self.font_family, size=12, weight="bold"),
            command=self._apply_model,
        )
        apply_model_btn.pack(side="right")

        # Status label
        self._settings_status = ctk.CTkLabel(
            parent,
            text="",
            font=ctk.CTkFont(family=self.font_family, size=11),
            anchor="w",
        )
        self._settings_status.pack(fill="x", padx=12, pady=(10, 8))

        # Carregar modelos na inicialização
        self.after(1000, self._refresh_models)

    def _change_appearance_mode(self, new_appearance_mode: str):
        """Altera o modo de aparência."""
        ctk.set_appearance_mode(new_appearance_mode)

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

        info_parts = [f"{m['name']} ({m['size']})" for m in models[:5]]
        if info_parts:
            self._settings_status.configure(
                text=f"✓ {len(models)} modelo(s) disponível(is)",
                text_color=("#198754", "#2ea043"),
            )
        else:
            self._settings_status.configure(
                text="⚠ Não foi possível listar modelos",
                text_color=("#d29922", "#e3b341"),
            )
        log.info("Modelos disponíveis: %s", [m["name"] for m in models])

    def _apply_model(self) -> None:
        """Aplica o modelo selecionado."""
        new_model = self._model_var.get()
        if new_model and new_model != self.llm.model:
            old = self.llm.model
            self.llm.set_model(new_model)
            self._model_info_label.configure(text=f"Modelo atual: {new_model}")
            self._settings_status.configure(
                text=f"✓ Modelo trocado: {old} → {new_model}",
                text_color=("#198754", "#2ea043"),
            )
            log.info("Modelo trocado: %s → %s", old, new_model)
        else:
            self._settings_status.configure(
                text=f"Modelo já ativo: {new_model}",
                text_color=("#d29922", "#e3b341"),
            )

    def _apply_endpoint(self) -> None:
        """Aplica o novo endpoint."""
        new_url = self._endpoint_var.get().strip()
        if new_url and new_url != self.llm.base_url:
            old = self.llm.base_url
            self.llm.set_endpoint(new_url)
            self._settings_status.configure(
                text="✓ Endpoint alterado. Recarregando modelos...",
                text_color=("#198754", "#2ea043"),
            )
            log.info("Endpoint trocado: %s → %s", old, new_url)
            self.after(500, self._refresh_models)
        else:
            self._settings_status.configure(
                text="Endpoint já ativo.",
                text_color=("#d29922", "#e3b341"),
            )

    def _on_agent_step(self, message: str) -> None:
        """Callback chamado pelo grafo para mostrar passos na UI."""
        self.after(0, lambda m=message: self.log_area.add_message(m, "info"))

    def _on_submit(self, text: str) -> None:
        """
        Processa o submit do campo de input.
        Executa o grafo do agente em uma thread separada.
        """
        # Expandir UI no primeiro uso
        self._expand_ui()

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
        """Executa o grafo do agente em background."""
        try:
            # Prepara a primeira mensagem do streaming
            self.after(0, lambda: self.log_area.add_message("🤖 Raciocínio LLM:\n", "system"))

            # Conta tokens de entrada
            in_tokens = self.llm.count_tokens(user_input)
            self.after(0, lambda: self.token_label.configure(text=f"Tokens: {in_tokens} In | ... Out"))

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
            self.after(0, lambda: self.token_label.configure(text=f"Tokens: {in_tokens} In | {out_tokens} Out"))

            # Adiciona uma quebra de linha ao final do streaming
            self.after(0, lambda: self.log_area.append_text("\n"))

            # Atualizar UI na thread principal
            self.after(0, self._handle_agent_result, result)
        except Exception as e:
            log.exception("Erro ao executar agente para input: %s", user_input)
            error_msg = f"⚠ Erro interno: {str(e)[:300]}"
            self.after(0, self._show_result, error_msg, "error")

    def _handle_agent_result(self, state: AgentState) -> None:
        """Processa o resultado do grafo do agente na thread principal."""
        ui_message = state.get("ui_message", "")
        ui_status = state.get("ui_status", "info")
        needs_confirmation = state.get("needs_confirmation", False)
        log.debug("Resultado do agente: status=%s, needs_confirmation=%s", ui_status, needs_confirmation)

        if needs_confirmation and not state.get("is_complete", True):
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

        thread = threading.Thread(target=self._execute_confirmed, args=(state,), daemon=True)
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
        """Exibe um resultado na área de log e atualiza o status."""
        if message:
            self.log_area.add_message(message, status)

        self._is_processing = False
        self.input_field.set_enabled(True)
        self.input_field.focus_input()
        log.debug("Resultado exibido na UI: status=%s", status)

        if status in ("error", "blocked"):
            self.status.set_status("online")
        else:
            self.status.set_status("online")

        self._adjust_height()

    def _adjust_height(self) -> None:
        """Ajusta a altura da janela baseado no conteúdo quando expandido."""
        if not self._is_expanded:
            return

        self.update_idletasks()
        needed = self.main_frame.winfo_reqheight() + 10
        max_h = self._expanded_height + self.max_log_height
        new_h = min(max(needed, self._expanded_height), max_h)
        self.geometry(f"{self.width}x{new_h}+{self._x_pos}+{self._y_pos}")

    def _clear_log(self) -> None:
        """Limpa a área de log."""
        self.log_area.clear()
        if self._is_expanded:
            self._adjust_height()

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
        self.after(30000, self._schedule_health_check)

    def _schedule_resource_refresh(self) -> None:
        """Agenda atualização read-only dos indicadores de recursos."""
        self._refresh_resources()
        self.after(5000, self._schedule_resource_refresh)

    def _refresh_resources(self) -> None:
        """Atualiza a faixa de recursos em background."""

        def read_snapshot():
            try:
                snapshot = self.agent.get_resource_snapshot()
            except Exception as e:
                log.debug("Snapshot de recursos indisponível: %s", str(e)[:120])
                return
            self.after(0, lambda: self.resource_strip.update_snapshot(snapshot))

        threading.Thread(target=read_snapshot, daemon=True).start()

    def _fade_in(self) -> None:
        """Animação sutil de fade-in ao aparecer."""
        import contextlib

        with contextlib.suppress(Exception):
            self.attributes("-alpha", 0.0)
            self._fade_step(0.0)

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
        pass

    def _check_focus(self) -> None:
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
