import os
import yaml

class Vault:
    """Gerencia credenciais armazenadas estritamente em memória (RAM)."""
    
    def __init__(self, secrets_path: str = ""):
        # secrets_path é ignorado de propósito por retrocompatibilidade na inicialização
        self._sudo_password = ""
            
    def get_sudo_password(self) -> str:
        return self._sudo_password
            
    def set_sudo_password(self, password: str) -> None:
        self._sudo_password = password

