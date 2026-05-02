"""
Serviço D-Bus para o Ubuntu Agent.

Permite integração "Single Instance" e chamadas via atalhos globais do sistema operacional.
Quando acionado via D-Bus, o método Toggle() alternará a visibilidade da interface.
"""

import asyncio
import threading

from dbus_next.aio import MessageBus
from dbus_next.service import ServiceInterface, method

from src.logger import get_logger

log = get_logger("system.dbus")


class UbuntuAgentInterface(ServiceInterface):
    def __init__(self, toggle_callback):
        super().__init__("org.ubuntu.Agent")
        self._toggle_callback = toggle_callback

    @method()
    def Toggle(self):  # noqa: N802
        """Método exposto no D-Bus para alternar a interface."""
        log.info("Sinal Toggle recebido via D-Bus.")
        if self._toggle_callback:
            self._toggle_callback()


def start_dbus_service(toggle_callback) -> None:
    """
    Inicia o serviço D-Bus em uma thread separada rodando asyncio.
    """

    def run_dbus_loop():
        async def setup():
            try:
                bus = await MessageBus().connect()
                interface = UbuntuAgentInterface(toggle_callback)
                bus.export("/org/ubuntu/Agent", interface)
                await bus.request_name("org.ubuntu.Agent")
                log.info("Serviço D-Bus 'org.ubuntu.Agent' registrado com sucesso.")
                await bus.wait_for_disconnect()
            except Exception as e:
                log.error(f"Falha ao iniciar servidor D-Bus: {e}")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(setup())
        except Exception as e:
            log.error(f"Erro no loop D-Bus: {e}")
        finally:
            loop.close()

    thread = threading.Thread(target=run_dbus_loop, daemon=True)
    thread.start()


def send_toggle_signal() -> bool:
    """
    Tenta enviar o sinal Toggle para uma instância existente via D-Bus.
    Retorna True se sucesso (instância já rodando), False caso contrário.
    """
    from dbus_next import Message, MessageType
    from dbus_next.glib import MessageBus as GlibMessageBus

    # Para o cliente simples (cli script send), não precisamos asyncio
    # Usamos o MessageBus síncrono para enviar e aguardar
    try:
        # Import sync bus
        bus = GlibMessageBus().connect()
        msg = Message(
            destination="org.ubuntu.Agent",
            path="/org/ubuntu/Agent",
            interface="org.ubuntu.Agent",
            member="Toggle",
            message_type=MessageType.METHOD_CALL,
        )
        # Tenta enviar a mensagem. Se o serviço não existir, lança erro.
        reply = bus.call_sync(msg)
        return bool(reply.message_type != MessageType.ERROR)
    except Exception:
        # Se ocorrer exceção (ex: nome não existe no bus), assumimos que o app não está rodando.
        return False
