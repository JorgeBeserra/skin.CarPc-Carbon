# -*- coding: utf-8 -*-
"""Controle do Bluetooth do LibreELEC (BlueZ) atraves do bluetoothctl.

Este modulo nao depende do Kodi, entao pode ser testado fora dele.

O LibreELEC ja traz o bluetoothctl. Todos os comandos sao executados como
"bluetoothctl <comando>" (modo de comando unico), que termina sozinho quando a
operacao acaba. O pareamento e a excecao: ele precisa de um agente registrado
durante toda a operacao, entao e feito por uma sessao que fica aberta
(BluetoothSession).
"""

import os
import re
import shutil
import subprocess
import time

BLUETOOTHCTL = "bluetoothctl"

# O LibreELEC liga o servico Bluetooth (LibreELEC > Servicos > Bluetooth) criando o
# arquivo bluez.conf nesta pasta; desligado, o arquivo se chama bluez.disabled.
LIBREELEC_SERVICES_DIR = "/storage/.cache/services"

_MAC_RE = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")
_DEVICE_LINE_RE = re.compile(r"^Device\s+([0-9A-Fa-f:]{17})\s*(.*)$")
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x01|\x02")


class BluetoothError(Exception):
    """Falha ao executar uma operacao de Bluetooth."""


def _clean(text):
    """Remove as cores e os retornos de carro que o bluetoothctl escreve."""
    return _ANSI_RE.sub("", text or "").replace("\r", "\n")


def normalize_mac(mac):
    """Valida o endereco. Evita repassar texto arbitrario ao bluetoothctl."""
    mac = (mac or "").strip().upper()
    if not _MAC_RE.match(mac):
        raise BluetoothError("Endereco Bluetooth invalido: %r" % (mac,))
    return mac


def is_available():
    """O bluetoothctl existe neste sistema?"""
    return shutil.which(BLUETOOTHCTL) is not None


def run(args, timeout=15):
    """Executa "bluetoothctl <args>" e devolve (codigo de saida, texto)."""
    cmd = [BLUETOOTHCTL] + [str(a) for a in args]
    try:
        proc = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise BluetoothError("bluetoothctl nao encontrado")
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode("utf-8", "ignore") if exc.stdout else ""
        return 124, _clean(out)
    return proc.returncode, _clean(proc.stdout.decode("utf-8", "ignore"))


def parse_properties(text):
    """Converte a saida de "show"/"info" ("Chave: valor") em dicionario.

    Chaves repetidas (ex.: UUID) ficam com o primeiro valor.
    """
    props = {}
    for line in _clean(text).splitlines():
        line = line.strip()
        if ":" not in line:
            continue
        if line.startswith("Device ") or line.startswith("Controller "):
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key and key not in props:
            props[key] = value.strip()
    return props


def parse_devices(text):
    """Converte a saida de "devices" em lista de (mac, nome)."""
    devices = []
    seen = set()
    for line in _clean(text).splitlines():
        match = _DEVICE_LINE_RE.match(line.strip())
        if not match:
            continue
        mac = match.group(1).upper()
        if mac in seen:
            continue
        seen.add(mac)
        devices.append((mac, match.group(2).strip()))
    return devices


def _yes(props, key):
    return props.get(key, "").lower() == "yes"


def adapter_info():
    """Estado do adaptador. Devolve None se nao houver adaptador disponivel
    (servico Bluetooth desligado no LibreELEC ou sem hardware)."""
    code, out = run(["show"], timeout=8)
    props = parse_properties(out)
    if code != 0 or "Powered" not in props:
        return None
    return {
        "name": props.get("Alias") or props.get("Name") or "",
        "powered": _yes(props, "Powered"),
        "discoverable": _yes(props, "Discoverable"),
        "pairable": _yes(props, "Pairable"),
        "discovering": _yes(props, "Discovering"),
    }


def set_power(enabled):
    code, out = run(["power", "on" if enabled else "off"], timeout=10)
    info = adapter_info()
    if info is None or info["powered"] != bool(enabled):
        raise BluetoothError(_last_line(out) or "Nao foi possivel alterar o Bluetooth")
    return True


def set_discoverable(enabled):
    """Deixa o carro visivel para que o celular inicie o pareamento."""
    state = "on" if enabled else "off"
    if enabled:
        run(["pairable", "on"], timeout=10)
    code, out = run(["discoverable", state], timeout=10)
    info = adapter_info()
    if info is None or info["discoverable"] != bool(enabled):
        raise BluetoothError(_last_line(out) or "Nao foi possivel alterar a visibilidade")
    return True


def scan(seconds=10):
    """Procura dispositivos durante "seconds" segundos (bloqueia)."""
    seconds = max(1, int(seconds))
    code, out = run(["--timeout", seconds, "scan", "on"], timeout=seconds + 10)
    return code in (0, 124)


def device_info(mac):
    mac = normalize_mac(mac)
    code, out = run(["info", mac], timeout=8)
    props = parse_properties(out)
    if code != 0 or not props:
        return None
    return {
        "mac": mac,
        "name": props.get("Alias") or props.get("Name") or mac,
        "paired": _yes(props, "Paired"),
        "trusted": _yes(props, "Trusted"),
        "connected": _yes(props, "Connected"),
        "icon": props.get("Icon", ""),
    }


def list_devices():
    """Dispositivos conhecidos pelo adaptador (pareados e encontrados na busca),
    ordenados: conectados, pareados e depois os demais, por nome."""
    code, out = run(["devices"], timeout=8)
    devices = []
    for mac, name in parse_devices(out):
        info = device_info(mac)
        if info is None:
            info = {"mac": mac, "name": name or mac, "paired": False,
                    "trusted": False, "connected": False, "icon": ""}
        elif info["name"] == mac and name:
            info["name"] = name
        devices.append(info)
    devices.sort(key=lambda d: (not d["connected"], not d["paired"], d["name"].lower()))
    return devices


def _last_line(text):
    lines = [l.strip() for l in _clean(text).splitlines() if l.strip()]
    return lines[-1] if lines else ""


def _wait_for(mac, key, wanted, timeout):
    """Espera ate a propriedade do dispositivo ter o valor desejado."""
    deadline = time.time() + timeout
    while True:
        info = device_info(mac)
        if info is not None and info[key] == wanted:
            return True
        if time.time() >= deadline:
            return False
        time.sleep(1.0)


def connect(mac, timeout=25):
    mac = normalize_mac(mac)
    code, out = run(["connect", mac], timeout=timeout)
    if _wait_for(mac, "connected", True, 3):
        return True
    raise BluetoothError(_last_line(out) or "Falha ao conectar")


def disconnect(mac, timeout=15):
    mac = normalize_mac(mac)
    code, out = run(["disconnect", mac], timeout=timeout)
    if _wait_for(mac, "connected", False, 3):
        return True
    raise BluetoothError(_last_line(out) or "Falha ao desconectar")


def trust(mac):
    """Dispositivo confiavel reconecta sozinho, sem perguntar de novo."""
    mac = normalize_mac(mac)
    run(["trust", mac], timeout=10)
    return True


def remove(mac):
    """Esquece o dispositivo (desfaz o pareamento)."""
    mac = normalize_mac(mac)
    code, out = run(["remove", mac], timeout=15)
    if device_info(mac) is None:
        return True
    raise BluetoothError(_last_line(out) or "Falha ao remover")


class BluetoothSession(object):
    """Sessao do bluetoothctl que fica aberta com um agente registrado.

    O agente e quem responde aos pedidos de pareamento. Com a capacidade
    "NoInputNoOutput" o pareamento e aceito sem digitar codigo na tela do carro
    (a confirmacao aparece somente no celular). Enquanto a sessao esta aberta
    ela tambem aceita pareamentos iniciados pelo celular.
    """

    def __init__(self, capability="NoInputNoOutput"):
        self.capability = capability
        self.proc = None

    def is_open(self):
        return self.proc is not None and self.proc.poll() is None

    def open(self):
        if self.is_open():
            return True
        try:
            self.proc = subprocess.Popen(
                [BLUETOOTHCTL, "--agent=" + self.capability],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            self.proc = None
            raise BluetoothError("Nao foi possivel iniciar o bluetoothctl: %s" % (exc,))
        # da tempo de conectar ao bluetoothd e registrar o agente
        time.sleep(1.0)
        self._send("default-agent")
        return self.is_open()

    def _send(self, command):
        if not self.is_open():
            raise BluetoothError("Sessao Bluetooth fechada")
        try:
            self.proc.stdin.write((command + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except (OSError, ValueError) as exc:
            raise BluetoothError("Falha ao enviar comando: %s" % (exc,))

    def pair(self, mac, timeout=40):
        """Pareia, marca como confiavel e conecta."""
        mac = normalize_mac(mac)
        self.open()
        info = device_info(mac)
        if info is None:
            raise BluetoothError("Dispositivo nao encontrado. Faca uma nova busca.")
        if not info["paired"]:
            self._send("pair " + mac)
            if not _wait_for(mac, "paired", True, timeout):
                raise BluetoothError("Pareamento nao concluido. Confirme no celular e tente de novo.")
        trust(mac)
        if not _wait_for(mac, "connected", True, 2):
            try:
                connect(mac)
            except BluetoothError:
                # pareou mas nao conectou (ex.: aparelho sem perfil de audio)
                return False
        return True

    def close(self):
        proc, self.proc = self.proc, None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                try:
                    proc.stdin.write(b"quit\n")
                    proc.stdin.flush()
                    proc.stdin.close()
                except (OSError, ValueError):
                    pass
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)
        except Exception:
            pass


def libreelec_service_enabled():
    """O servico Bluetooth esta habilitado nas configuracoes do LibreELEC?

    Devolve None quando nao e um LibreELEC (pasta de servicos inexistente).
    """
    if not os.path.isdir(LIBREELEC_SERVICES_DIR):
        return None
    return os.path.isfile(os.path.join(LIBREELEC_SERVICES_DIR, "bluez.conf"))
