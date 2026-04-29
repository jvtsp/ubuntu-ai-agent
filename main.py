#!/usr/bin/env python3
"""
Ubuntu Agent - Ponto de entrada da aplicação.

Carrega configurações, registra o atalho global e lança a interface.

Uso:
    python main.py           # Iniciar normalmente
    python main.py --toggle  # Alternar visibilidade (para integração com D-Bus/keybinding)
"""

import os
import sys
import signal
import argparse
import threading
import yaml
import pystray
from PIL import Image, ImageDraw

# Adicionar diretório raiz ao path
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT_DIR)

from src.logger import setup_logging, get_logger


def load_config(config_path: str = "config.yaml") -> dict:
    """
    Carrega as configurações do arquivo YAML.

    Args:
        config_path: Caminho para o arquivo de configuração.

    Returns:
        Dicionário com as configurações.
    """
    full_path = os.path.join(ROOT_DIR, config_path)
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        return config or {}
    except FileNotFoundError:
        print(f"[WARN] Arquivo {config_path} não encontrado. Usando valores padrão.")
        return {}
    except yaml.YAMLError as e:
        print(f"[ERRO] Erro ao parsear {config_path}: {e}")
        return {}


def setup_hotkey(app, config: dict) -> None:
    """
    Configura o atalho global para alternar a janela.

    Tenta usar a biblioteca 'keyboard' (pura Python, mas requer sudo),
    depois 'pynput' como fallback. Se nenhuma funcionar, informa ao
    usuário como configurar via GNOME.

    Args:
        app: Instância da janela principal.
        config: Configurações de UI com a chave 'hotkey'.
    """
    hotkey_str = config.get("ui", {}).get("hotkey", "super+space")

    # Tentativa 1: biblioteca 'keyboard'
    try:
        import keyboard

        # Mapear "super" para nomes que a lib keyboard entende
        kb_hotkey = hotkey_str.replace("super", "windows")

        keyboard.add_hotkey(kb_hotkey, lambda: app.after(0, app.toggle_window))
        print(f"[INFO] Atalho global '{hotkey_str}' registrado via keyboard.")
        return
    except ImportError:
        pass
    except Exception as e:
        print(f"[WARN] keyboard: {e}")
        print("[DICA] A biblioteca 'keyboard' requer execução como root (sudo).")

    # Tentativa 2: biblioteca 'pynput'
    try:
        from pynput import keyboard as pynput_kb

        KEY_MAP = {
            "super": pynput_kb.Key.cmd,
            "ctrl": pynput_kb.Key.ctrl,
            "alt": pynput_kb.Key.alt,
            "shift": pynput_kb.Key.shift,
            "space": pynput_kb.Key.space,
        }

        parts = hotkey_str.lower().split("+")
        hotkey_keys = set()
        for part in parts:
            part = part.strip()
            if part in KEY_MAP:
                hotkey_keys.add(KEY_MAP[part])
            elif len(part) == 1:
                hotkey_keys.add(pynput_kb.KeyCode.from_char(part))

        current_keys = set()

        def on_press(key):
            current_keys.add(key)
            if hotkey_keys.issubset(current_keys):
                app.after(0, app.toggle_window)

        def on_release(key):
            current_keys.discard(key)

        listener = pynput_kb.Listener(on_press=on_press, on_release=on_release)
        listener.daemon = True
        listener.start()
        print(f"[INFO] Atalho global '{hotkey_str}' registrado via pynput.")
        return
    except ImportError:
        pass
    except Exception as e:
        print(f"[WARN] pynput: {e}")

    # Nenhuma biblioteca de hotkey funcional
    print("[WARN] Nenhuma biblioteca de atalho global disponível.")
    print("[DICA] Para atalho global no GNOME/Wayland, adicione um atalho personalizado:")
    print(f"       Comando: python3 {os.path.abspath(__file__)} --toggle")
    print("       Configurações > Teclado > Atalhos personalizados")


def setup_tray(app) -> None:
    """Configura o ícone na bandeja do sistema (System Tray)."""
    def create_image():
        # Cria um ícone simples com um círculo azul
        image = Image.new('RGB', (64, 64), color=("#1e1e2e"))
        draw = ImageDraw.Draw(image)
        draw.ellipse((16, 16, 48, 48), fill=("#89b4fa"))
        return image

    def on_activate(icon, item):
        # Chama a função na thread principal do Tkinter
        app.after(0, app.toggle_window)
        
    def on_quit(icon, item):
        icon.stop()
        app.after(0, app.destroy)

    menu = pystray.Menu(
        pystray.MenuItem("Mostrar/Ocultar", on_activate, default=True),
        pystray.MenuItem("Sair do Ubuntu Agent", on_quit)
    )
    
    icon = pystray.Icon("UbuntuAgent", create_image(), "Ubuntu Agent", menu)
    
    # Executar em thread separada para não bloquear a UI principal
    threading.Thread(target=icon.run, daemon=True).start()
    print("[INFO] Ícone da bandeja do sistema criado.")


def main() -> None:
    """Função principal: inicializa e executa o Ubuntu Agent."""
    # Parsear argumentos
    parser = argparse.ArgumentParser(description="Ubuntu Agent - Assistente de comandos")
    parser.add_argument(
        "--toggle",
        action="store_true",
        help="Alternar visibilidade da janela (para integração com keybindings do GNOME)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.yaml",
        help="Caminho para o arquivo de configuração",
    )
    args = parser.parse_args()

    # Carregar configurações
    config = load_config(args.config)

    # ─── Inicializar logging ─────────────────────────────────────────────────
    log_level = config.get("logging", {}).get("level", "DEBUG")
    setup_logging(log_level)
    log = get_logger("main")
    log.info("Ubuntu Agent iniciando...")

    # Se --toggle, tentar enviar sinal para instância existente
    if args.toggle:
        # Por enquanto, apenas inicia a aplicação normalmente
        # Uma implementação futura poderia usar D-Bus ou arquivo PID
        pass

    # ─── Inicializar componentes ─────────────────────────────────────────────

    # Banco de dados
    from src.storage.database import Database
    db_path = config.get("history", {}).get("db_path", "data/history.db")
    db = Database(os.path.join(ROOT_DIR, db_path))
    log.info("Banco de dados inicializado: %s", db_path)

    # Vault (Cofre)
    from src.storage.vault import Vault
    vault = Vault()
    log.info("Cofre de credenciais inicializado (in-memory).")

    # Cliente LLM
    from src.agent.llm import LLMClient
    llm_config = config.get("llm", {})
    llm_client = LLMClient(llm_config)
    log.info("Cliente LLM configurado: model=%s, base_url=%s", llm_config.get('model'), llm_config.get('base_url'))

    # Validador de segurança
    from src.executor.safety import SecurityValidator
    security_config = config.get("security", {})
    security = SecurityValidator(security_config)

    # Grafo do agente
    from src.agent.graph import AgentGraph
    agent = AgentGraph(llm_client, security, db, config, vault)
    log.info("Grafo do agente construído.")

    # ─── Criar e configurar a UI ─────────────────────────────────────────────
    from src.ui.app import UbuntuAgentApp
    app = UbuntuAgentApp(agent, llm_client, config)
    log.info("Interface gráfica inicializada.")

    # Registrar atalho global
    setup_hotkey(app, config)

    # Adicionar ícone na bandeja do sistema (Tray Icon)
    try:
        setup_tray(app)
    except Exception as e:
        print(f"[WARN] Falha ao criar tray icon: {e}")

    # Tratar Ctrl+C graciosamente
    signal.signal(signal.SIGINT, lambda s, f: app.destroy())

    # ─── Loop principal ──────────────────────────────────────────────────────
    print("[INFO] Ubuntu Agent iniciado. Use Super+Space para alternar.")
    print("[INFO] Pressione Ctrl+C no terminal para encerrar.")

    try:
        app.mainloop()
    except KeyboardInterrupt:
        print("\n[INFO] Ubuntu Agent encerrado.")


if __name__ == "__main__":
    main()
