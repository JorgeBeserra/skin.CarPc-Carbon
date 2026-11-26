"""Confirma mudancas do sensor de luz sem bloquear a leitura dos comandos."""
import time


class NightMode:
    def __init__(self, delay=2.0, clock=time.monotonic):
        self.delay = delay
        self.clock = clock
        self.active = False
        self.pending = None
        self.since = None

    def update(self, lighting):
        if lighting not in ("Claro", "Escuro"):
            self.pending = None
            self.since = None
            return self.active
        target = lighting == "Escuro"
        if target == self.active:
            self.pending = None
            self.since = None
        elif self.pending != target:
            self.pending = target
            self.since = self.clock()
        elif self.clock() - self.since >= self.delay:
            self.active = target
            self.pending = None
            self.since = None
        return self.active

def lighting_from_byte(value):
    """Byte 1 do CAN 0x3B3 (BCM Ford): bit 7 = escuro (0x88), bit 6 = claro (0x48).
    Os outros bits mudam com o pisca-alerta (0x4A/0x8A), por isso testa so os bits."""
    if value & 0x80:
        return "Escuro"
    if value & 0x40:
        return "Claro"
    return None
