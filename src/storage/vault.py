class Vault:
    """Gerencia credenciais armazenadas estritamente em memória (RAM)."""

    def __init__(self, secrets_path: str = ""):
        # secrets_path é ignorado de propósito por retrocompatibilidade na inicialização
        self._sudo_password = ""

    def get_sudo_password(self) -> str:
        return self._sudo_password

    def set_sudo_password(self, password: str) -> None:
        self._sudo_password = password

    def clear(self) -> None:
        """Limpa a senha da memória de forma segura."""
        import ctypes

        # Sobrescrever a string em memória se possível
        if self._sudo_password:
            # Em Python strings são imutáveis, mas podemos tentar
            # dar uma dica para o garbage collector ou usar ctypes
            # para zerar o buffer (best effort).
            import contextlib

            with contextlib.suppress(Exception):
                buffer_size = len(self._sudo_password) * 2  # utf-16/utf-8 var size
                ctypes.memset(id(self._sudo_password) + 24, 0, buffer_size)

        self._sudo_password = ""
