"""
Ubuntu Agent - Widgets reutilizáveis da interface.

Contém componentes da UI: campo de input com placeholder,
área de log rolável, indicador de status e modal de confirmação.
"""

from collections.abc import Callable

import customtkinter as ctk


class InputField(ctk.CTkFrame):
    """Campo de input estilizado com placeholder."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        placeholder: str = "Digite um comando em português...",
        on_submit: Callable[[str], None] | None = None,
        font_family: str = "JetBrains Mono",
        font_size: int = 13,
        **kwargs,
    ) -> None:
        """
        Inicializa o campo de input.

        Args:
            master: Widget pai.
            placeholder: Texto de placeholder.
            on_submit: Callback chamado ao pressionar Enter.
            font_family: Família da fonte.
            font_size: Tamanho da fonte.
        """
        super().__init__(master, fg_color="transparent", **kwargs)

        self.on_submit = on_submit
        self.placeholder = placeholder

        self.entry = ctk.CTkEntry(
            self,
            placeholder_text=placeholder,
            font=ctk.CTkFont(family=font_family, size=font_size),
            height=35,
            corner_radius=0,
            border_width=0,
            fg_color="transparent",
            text_color=("#f8f8f2", "#f8f8f2"),
            placeholder_text_color=("#6c7086", "#6c7086"),
        )

        self.prompt_label = ctk.CTkLabel(
            self,
            text="user@agent:~$",
            font=ctk.CTkFont(family=font_family, size=font_size, weight="bold"),
            text_color=("#38b44a", "#38b44a"), # Ubuntu green
        )

        self.prompt_label.pack(side="left", padx=(10, 5), pady=2)
        self.entry.pack(side="left", fill="x", expand=True, padx=2, pady=2)
        self.entry.bind("<Return>", self._handle_submit)

    def _handle_submit(self, event=None) -> None:
        """Processa o submit do campo de input."""
        text = self.entry.get().strip()
        if text and self.on_submit:
            self.on_submit(text)

    def clear(self) -> None:
        """Limpa o campo de input."""
        self.entry.delete(0, "end")

    def focus_input(self) -> None:
        """Coloca o foco no campo de input."""
        self.entry.focus_set()

    def set_enabled(self, enabled: bool) -> None:
        """Habilita ou desabilita o campo."""
        self.entry.configure(state="normal" if enabled else "disabled")


class StatusIndicator(ctk.CTkFrame):
    """Indicador de status com ponto colorido."""

    # Cores para cada status
    COLORS = {
        "online": "#a6e3a1",     # Verde - LLM conectado
        "processing": "#f9e2af",  # Amarelo - processando
        "offline": "#f38ba8",     # Vermelho - LLM offline
        "idle": "#6c7086",        # Cinza - inativo
    }

    LABELS = {
        "online": "LLM Conectado",
        "processing": "Processando...",
        "offline": "LLM Offline",
        "idle": "Aguardando",
    }

    def __init__(self, master: ctk.CTkBaseClass, **kwargs) -> None:
        """Inicializa o indicador de status."""
        super().__init__(master, fg_color="transparent", **kwargs)

        self._status = "idle"

        # Container horizontal
        self.dot = ctk.CTkLabel(
            self,
            text="●",
            font=ctk.CTkFont(size=12),
            text_color=self.COLORS["idle"],
            width=20,
        )
        self.dot.pack(side="left", padx=(0, 5))

        self.label = ctk.CTkLabel(
            self,
            text=self.LABELS["idle"],
            font=ctk.CTkFont(size=11),
            text_color=("#6c7086", "#6c7086"),
        )
        self.label.pack(side="left")

    def set_status(self, status: str) -> None:
        """
        Atualiza o status do indicador.

        Args:
            status: Um de 'online', 'processing', 'offline', 'idle'.
        """
        self._status = status
        color = self.COLORS.get(status, self.COLORS["idle"])
        label = self.LABELS.get(status, "Desconhecido")
        self.dot.configure(text_color=color)
        self.label.configure(text=label)


class LogArea(ctk.CTkFrame):
    """Área de log rolável para exibir resultados."""

    # Cores para tipos de mensagem
    STATUS_COLORS = {
        "success": "#a6e3a1",
        "error": "#f38ba8",
        "warning": "#f9e2af",
        "blocked": "#f38ba8",
        "pending": "#89b4fa",
        "info": "#cdd6f4",
    }

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        max_height: int = 200,
        font_family: str = "JetBrains Mono",
        font_size: int = 12,
        **kwargs,
    ) -> None:
        """
        Inicializa a área de log.

        Args:
            master: Widget pai.
            max_height: Altura máxima em pixels.
            font_family: Família da fonte.
            font_size: Tamanho da fonte.
        """
        super().__init__(
            master,
            fg_color=("#181825", "#181825"),
            corner_radius=12,
            **kwargs,
        )

        self.max_height = max_height

        self.textbox = ctk.CTkTextbox(
            self,
            font=ctk.CTkFont(family=font_family, size=font_size),
            fg_color="transparent",
            text_color=("#cdd6f4", "#cdd6f4"),
            wrap="word",
            height=0,
            corner_radius=12,
            activate_scrollbars=True,
        )
        self.textbox.pack(fill="both", expand=True, padx=8, pady=8)

        # Configurar tags para cores
        self.textbox.tag_config("thought", foreground="#888888")
        self.textbox.tag_config("code", foreground="#e95420")
        self.textbox.tag_config("system", foreground="#77216f")
        for status, color in self.STATUS_COLORS.items():
            self.textbox.tag_config(status, foreground=color)

        self.textbox.configure(state="disabled")

        # Começa oculto
        self.pack_forget()
        self._has_content = False

    def add_message(self, message: str, status: str = "info", tags: tuple = ()) -> None:
        """
        Adiciona uma mensagem à área de log.

        Args:
            message: Texto da mensagem.
            status: Tipo de status para coloração.
            tags: Tags extras do Tkinter.
        """
        self.textbox.configure(state="normal")

        if self._has_content:
            self.textbox.insert("end", "\n" + "─" * 60 + "\n", ("system",))

        all_tags = (status,) + tags
        self.textbox.insert("end", message + "\n", all_tags)
        self._has_content = True

        self.textbox.configure(state="disabled")
        self.textbox.see("end")

        # Mostrar a área de log e ajustar altura
        self._update_visibility()

    def append_text(self, text: str, tags: tuple = ()) -> None:
        """
        Adiciona texto contínuo à última mensagem da área de log (útil para streaming).

        Args:
            text: Texto a ser adicionado.
            tags: Tags do Tkinter.
        """
        self.textbox.configure(state="normal")

        if not self._has_content:
            self._has_content = True

        self.textbox.insert("end", text, tags)
        self.textbox.configure(state="disabled")
        self.textbox.see("end")
        self._update_visibility()

    def _update_visibility(self) -> None:
        """Atualiza a visibilidade e altura da área de log."""
        if self._has_content:
            self.pack(fill="x", padx=12, pady=(0, 12))
            # Calcula altura necessária
            num_lines = int(self.textbox.index("end-1c").split(".")[0])
            line_height = 18  # Altura aproximada por linha
            needed_height = min(num_lines * line_height + 20, self.max_height)
            self.textbox.configure(height=max(needed_height, 60))

    def clear(self) -> None:
        """Limpa toda a área de log."""
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        self.textbox.configure(state="disabled")
        self._has_content = False
        self.pack_forget()


class ConfirmationModal(ctk.CTkToplevel):
    """Modal de confirmação para comandos que requerem aprovação."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        command: str,
        reason: str = "",
        on_confirm: Callable[[], None] | None = None,
        on_reject: Callable[[], None] | None = None,
        font_family: str = "JetBrains Mono",
        **kwargs,
    ) -> None:
        """
        Inicializa o modal de confirmação.

        Args:
            master: Widget pai.
            command: Comando Bash a ser confirmado.
            reason: Motivo pelo qual a confirmação é necessária.
            on_confirm: Callback ao confirmar.
            on_reject: Callback ao rejeitar.
            font_family: Família da fonte.
        """
        super().__init__(master, **kwargs)

        self.on_confirm = on_confirm
        self.on_reject = on_reject

        # Configurar janela
        self.title("Confirmação de Comando")
        self.resizable(False, False)
        self.transient(master)
        self.attributes("-topmost", True)

        # Configurar aparência
        self.configure(fg_color=("#1e1e2e", "#1e1e2e"))

        # Título
        title_label = ctk.CTkLabel(
            self,
            text="⚠ Confirmação Necessária",
            font=ctk.CTkFont(family=font_family, size=16, weight="bold"),
            text_color=("#f9e2af", "#f9e2af"),
        )
        title_label.pack(pady=(20, 10))

        # Motivo
        if reason:
            reason_label = ctk.CTkLabel(
                self,
                text=reason,
                font=ctk.CTkFont(family=font_family, size=12),
                text_color=("#a6adc8", "#a6adc8"),
                wraplength=500,
            )
            reason_label.pack(pady=(0, 10))

        # Comando
        cmd_frame = ctk.CTkFrame(
            self,
            fg_color=("#11111b", "#11111b"),
            corner_radius=10,
        )
        cmd_frame.pack(fill="x", padx=20, pady=10)

        cmd_label = ctk.CTkLabel(
            cmd_frame,
            text=f"$ {command}",
            font=ctk.CTkFont(family=font_family, size=13),
            text_color=("#89b4fa", "#89b4fa"),
            wraplength=490,
            justify="left",
        )
        cmd_label.pack(padx=15, pady=15)

        # Botões
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=20)

        reject_btn = ctk.CTkButton(
            btn_frame,
            text="✕ Cancelar",
            font=ctk.CTkFont(family=font_family, size=13),
            width=140,
            height=40,
            corner_radius=10,
            fg_color=("#45475a", "#45475a"),
            hover_color=("#585b70", "#585b70"),
            text_color=("#cdd6f4", "#cdd6f4"),
            command=self._reject,
        )
        reject_btn.pack(side="left", padx=10)

        confirm_btn = ctk.CTkButton(
            btn_frame,
            text="✓ Executar",
            font=ctk.CTkFont(family=font_family, size=13, weight="bold"),
            width=140,
            height=40,
            corner_radius=10,
            fg_color=("#a6e3a1", "#a6e3a1"),
            hover_color=("#94e2d5", "#94e2d5"),
            text_color=("#1e1e2e", "#1e1e2e"),
            command=self._confirm,
        )
        confirm_btn.pack(side="left", padx=10)

        # Esc para cancelar
        self.bind("<Escape>", lambda e: self._reject())
        self.bind("<Return>", lambda e: self._confirm())

        # Fechar pelo botão X também chama reject
        self.protocol("WM_DELETE_WINDOW", self._reject)

        # Posicionar e mostrar DEPOIS de construir todos os widgets
        self.update_idletasks()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = (screen_w - 550) // 2
        y = (screen_h - 320) // 2
        self.geometry(f"550x320+{x}+{y}")
        self.grab_set()
        self.focus_force()

    def _confirm(self) -> None:
        """Confirma a execução."""
        self.grab_release()
        self.destroy()
        if self.on_confirm:
            self.on_confirm()

    def _reject(self) -> None:
        """Rejeita a execução."""
        self.grab_release()
        self.destroy()
        if self.on_reject:
            self.on_reject()
