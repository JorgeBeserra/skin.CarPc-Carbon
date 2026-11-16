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
