"""
Ubuntu Agent - Widgets reutilizáveis da interface.

Contém componentes da UI: campo de input com placeholder,
área de log rolável, indicador de status e modal de confirmação.
"""

from collections.abc import Callable

import customtkinter as ctk
import typing


class InputField(ctk.CTkFrame):
    """Campo de input estilizado com placeholder."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        placeholder: str = "Digite um comando em português...",
        on_submit: Callable[[str], None] | None = None,
        font_family: str = "JetBrains Mono",
        font_size: int = 14,
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
            height=45,
            corner_radius=8,
            border_width=1,
            fg_color=("gray95", "gray15"),
        )

        self.prompt_label = ctk.CTkLabel(
            self,
            text="user@agent:~$",
            font=ctk.CTkFont(family=font_family, size=font_size, weight="bold"),
            text_color=("#2ea043", "#3fb950"), # Ubuntu green adaptable
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

    # Cores para cada status adaptáveis ao tema (Light, Dark)
    COLORS: typing.ClassVar[dict[str, tuple[str, str]]] = {
        "online": ("#198754", "#2ea043"),     # Verde
        "processing": ("#ffc107", "#e3b341"), # Amarelo
        "offline": ("#dc3545", "#f85149"),    # Vermelho
        "idle": ("gray50", "gray60"),         # Cinza
    }

    LABELS: typing.ClassVar[dict[str, str]] = {
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

    # Cores adaptáveis para tags do Tkinter
    # No Text widget do Tkinter não podemos passar uma tupla ("light", "dark")
    # Teria que atualizar no change do tema. Para simplificar e manter robusto,
    # usamos cores que funcionam bem em fundos claros e escuros ou tons intermediários.
    STATUS_COLORS: typing.ClassVar[dict[str, str]] = {
        "success": "#2ea043",
        "error": "#f85149",
        "warning": "#d29922",
        "blocked": "#f85149",
        "pending": "#58a6ff",
        "info": "#8b949e",
    }

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        max_height: int = 400,
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
            fg_color=("gray95", "gray15"),
            corner_radius=12,
            **kwargs,
        )

        self.max_height = max_height

        self.textbox = ctk.CTkTextbox(
            self,
            font=ctk.CTkFont(family=font_family, size=font_size),
            fg_color="transparent",
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

        all_tags = (status, *tags)
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
            self.pack(fill="both", expand=True, padx=12, pady=(0, 12))

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

        # Título
        title_label = ctk.CTkLabel(
            self,
            text="⚠ Confirmação Necessária",
            font=ctk.CTkFont(family=font_family, size=16, weight="bold"),
            text_color=("#d29922", "#e3b341"), # Amarelo/Laranja
        )
        title_label.pack(pady=(20, 10))

        # Motivo
        if reason:
            reason_label = ctk.CTkLabel(
                self,
                text=reason,
                font=ctk.CTkFont(family=font_family, size=12),
                wraplength=500,
            )
            reason_label.pack(pady=(0, 10))

        # Comando
        cmd_frame = ctk.CTkFrame(
            self,
            fg_color=("gray90", "gray10"),
            corner_radius=10,
        )
        cmd_frame.pack(fill="x", padx=20, pady=10)

        cmd_label = ctk.CTkLabel(
            cmd_frame,
            text=f"$ {command}",
            font=ctk.CTkFont(family=font_family, size=13),
            text_color=("#0550ae", "#58a6ff"), # Azul
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
            fg_color=("gray70", "gray30"),
            hover_color=("gray60", "gray40"),
            text_color=("black", "white"),
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
            fg_color=("#198754", "#2ea043"),
            hover_color=("#157347", "#2c974b"),
            text_color="white",
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

