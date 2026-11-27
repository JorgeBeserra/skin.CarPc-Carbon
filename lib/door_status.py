"""Portas do Ford Ka 2019 no CAN 0x3B3 (bytes 6 e 7) e confirmacao de mudancas.

Mapeamento (anotado no carro):
  byte 6: 0x01 traseira esquerda, 0x02 traseira direita (0x80 sempre ligado)
  byte 7: 0x20 motorista, 0x10 passageiro, 0x04 porta-malas
"""
import time

DOOR_BITS = (
    ("driver", 7, 0x20),
    ("passenger", 7, 0x10),
    ("rear_left", 6, 0x01),
    ("rear_right", 6, 0x02),
    ("trunk", 7, 0x04),
)


def door_word(door, is_open):
    # O porta-malas usa "Aberto"/"Fechado"; as portas, "Aberta"/"Fechada"
    if door == "trunk":
        return "Aberto" if is_open else "Fechado"
    return "Aberta" if is_open else "Fechada"


def decode_doors(data):
    """data: lista de bytes (int) do frame 0x3B3. Retorna {porta: texto} ou None."""
    if len(data) < 8:
        return None
    return {door: door_word(door, bool(data[idx] & mask)) for door, idx, mask in DOOR_BITS}


class DoorDebouncer:
    """So aceita a mudanca de uma porta depois de ela ficar estavel por `delay` s.
    O sensor da porta pode oscilar (ex.: 0x81 -> 0x80 por ~1 s com tudo fechado)."""

    def __init__(self, delay=2.0, clock=time.monotonic):
        self.delay = delay
        self.clock = clock
        self.confirmed = {}
        self.pending = {}

    def update(self, raw):
        now = self.clock()
        for door, value in raw.items():
            if not value:
                continue
            if door not in self.confirmed:
                self.confirmed[door] = value  # primeira leitura: aceita direto
                continue
            if value == self.confirmed[door]:
                self.pending.pop(door, None)
                continue
            pend = self.pending.get(door)
            if not pend or pend[0] != value:
                self.pending[door] = (value, now)
            elif now - pend[1] >= self.delay:
                self.confirmed[door] = value
                del self.pending[door]
        return dict(self.confirmed)
