# -*- coding: utf-8 -*-
"""Tela de conexoes Bluetooth da skin CarPc-Carbon.

Aberta pelo botao Bluetooth da Home:
    RunScript(special://skin/scripts/bluetooth.py)

Conversa com o BlueZ do LibreELEC por meio de lib/carpc_bluetooth.py.
"""

import os
import sys
import threading

import xbmc
import xbmcgui
import xbmcvfs

SKIN_PATH = xbmcvfs.translatePath("special://skin/")
LIB_PATH = os.path.join(SKIN_PATH, "lib")
if LIB_PATH not in sys.path:
    sys.path.insert(0, LIB_PATH)

import carpc_bluetooth as bt  # noqa: E402

WINDOW_XML = "script-carpc-bluetooth.xml"
RUNNING_PROPERTY = "carpc_bluetooth_open"
LIBREELEC_SETTINGS = "service.libreelec.settings"

CTRL_ADAPTER = 2
CTRL_STATUS = 3
CTRL_EMPTY = 4
CTRL_LIST = 50
CTRL_SCAN = 9001
CTRL_VISIBLE = 9002
CTRL_POWER = 9003
CTRL_LIBREELEC = 9004
CTRL_CLOSE = 9005

ACTION_PREVIOUS_MENU = 10
ACTION_NAV_BACK = 92

SCAN_SECONDS = 12
REFRESH_SECONDS = 5


def log(message, level=xbmc.LOGINFO):
    xbmc.log("[CarPc Bluetooth] %s" % (message,), level)


def device_state_label(device):
    if device["connected"]:
        return "Conectado"
    if device["paired"]:
        return "Pareado"
    return "Disponível"


class BluetoothWindow(xbmcgui.WindowXMLDialog):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.monitor = xbmc.Monitor()
        self.session = bt.BluetoothSession()
        self.devices = []
        self.adapter = None
        self.closing = False
        self.ready = False
        self.busy = False
        self.busy_lock = threading.Lock()
        self.ui_lock = threading.Lock()

    # ------------------------------------------------------------------ Kodi

    def onInit(self):
        if self.ready:
            return
        self.ready = True
        self.set_status("Carregando...")
        threading.Thread(target=self._background_loop, daemon=True).start()

    def onAction(self, action):
        if action.getId() in (ACTION_PREVIOUS_MENU, ACTION_NAV_BACK):
            self.shutdown()

    def onClick(self, control_id):
        if control_id == CTRL_CLOSE:
            self.shutdown()
        elif control_id == CTRL_LIBREELEC:
            self.open_libreelec_settings()
        elif control_id == CTRL_SCAN:
            self.run_task("Procurando dispositivos...", self.task_scan)
        elif control_id == CTRL_VISIBLE:
            self.run_task("Alterando visibilidade...", self.task_toggle_visible)
        elif control_id == CTRL_POWER:
            self.run_task("Aguarde...", self.task_toggle_power)
        elif control_id == CTRL_LIST:
            self.device_menu()

    def shutdown(self):
        self.closing = True
        self.close()

    # --------------------------------------------------------------- helpers

    def set_status(self, text):
        try:
            self.getControl(CTRL_STATUS).setLabel(text)
        except Exception:
            pass

    def run_task(self, status, target, *args):
        """Executa a operacao fora da thread da interface, uma por vez."""
        with self.busy_lock:
            if self.busy:
                self.set_status("Aguarde a operação atual terminar...")
                return
            self.busy = True
        self.set_status(status)

        def worker():
            message = ""
            try:
                message = target(*args) or ""
            except bt.BluetoothError as exc:
                message = "Erro: %s" % (exc,)
                log(message, xbmc.LOGERROR)
            except Exception as exc:  # nunca derruba a tela
                message = "Erro inesperado: %s" % (exc,)
                log(message, xbmc.LOGERROR)
            finally:
                with self.busy_lock:
                    self.busy = False
            if not self.closing:
                self.refresh()
                self.set_status(message)

        threading.Thread(target=worker, daemon=True).start()

    def _background_loop(self):
        """Mantem o agente de pareamento aberto e a lista atualizada."""
        try:
            if bt.is_available() and bt.adapter_info() is not None:
                try:
                    self.session.open()
                except bt.BluetoothError as exc:
                    log("Agente de pareamento indisponivel: %s" % (exc,), xbmc.LOGWARNING)
            self.refresh()
            if not self.closing:
                self.set_status("")
            while not self.closing and not self.monitor.waitForAbort(REFRESH_SECONDS):
                if self.closing:
                    break
                if not self.busy:
                    self.refresh()
        finally:
            self.session.close()

    # --------------------------------------------------------------- refresh

    def refresh(self):
        """Le o estado do adaptador e dos dispositivos e redesenha a tela."""
        if self.closing:
            return
        with self.ui_lock:
            empty_message = ""
            adapter = None
            devices = []
            try:
                if not bt.is_available():
                    empty_message = ("O bluetoothctl não foi encontrado.[CR]"
                                     "Esta tela funciona no LibreELEC.")
                else:
                    adapter = bt.adapter_info()
                    if adapter is None:
                        if bt.libreelec_service_enabled() is False:
                            empty_message = ("O Bluetooth está desativado no LibreELEC.[CR]"
                                             "Toque em LibreELEC > Serviços e ative o Bluetooth.")
                        else:
                            empty_message = "Nenhum adaptador Bluetooth encontrado."
                    elif not adapter["powered"]:
                        empty_message = "Bluetooth desligado."
                    else:
                        devices = bt.list_devices()
                        if not devices:
                            empty_message = ("Nenhum dispositivo.[CR]Toque em Procurar ou deixe o "
                                             "carro visível e pareie pelo celular.")
            except bt.BluetoothError as exc:
                empty_message = "Erro: %s" % (exc,)
                log(empty_message, xbmc.LOGERROR)

            if self.closing:
                return
            self.adapter = adapter
            self.devices = devices
            try:
                self._draw(empty_message)
            except Exception as exc:
                log("Falha ao desenhar a tela: %s" % (exc,), xbmc.LOGERROR)

    def _draw(self, empty_message):
        adapter = self.adapter
        powered = bool(adapter and adapter["powered"])

        if adapter is None:
            adapter_text = "Indisponível"
        elif not powered:
            adapter_text = "Desligado"
        else:
            adapter_text = adapter["name"] or "Ligado"
            if adapter["discoverable"]:
                adapter_text += " - visível"
        self.getControl(CTRL_ADAPTER).setLabel(adapter_text)
        self.getControl(CTRL_EMPTY).setLabel(empty_message)

        self.getControl(CTRL_POWER).setLabel("Desligar Bluetooth" if powered else "Ligar Bluetooth")
        self.getControl(CTRL_POWER).setEnabled(adapter is not None)
        self.getControl(CTRL_SCAN).setEnabled(powered)
        self.getControl(CTRL_VISIBLE).setEnabled(powered)
        self.getControl(CTRL_VISIBLE).setLabel(
            "Ficar oculto" if (adapter and adapter["discoverable"]) else "Ficar visível")

        device_list = self.getControl(CTRL_LIST)
        selected = device_list.getSelectedPosition()
        items = []
        for device in self.devices:
            item = xbmcgui.ListItem(device["name"], device_state_label(device))
            item.setProperty("mac", device["mac"])
            items.append(item)
        device_list.reset()
        if items:
            device_list.addItems(items)
            if 0 <= selected < len(items):
                device_list.selectItem(selected)

    # ----------------------------------------------------------------- tasks

    def task_scan(self):
        bt.scan(SCAN_SECONDS)
        return "Busca concluída."

    def task_toggle_visible(self):
        info = bt.adapter_info()
        if info is None:
            raise bt.BluetoothError("Adaptador indisponível")
        enable = not info["discoverable"]
        bt.set_discoverable(enable)
        if enable:
            return "Carro visível. Procure por \"%s\" no celular." % (info["name"] or "LibreELEC",)
        return "Carro oculto."

    def task_toggle_power(self):
        info = bt.adapter_info()
        if info is None:
            raise bt.BluetoothError("Adaptador indisponível")
        bt.set_power(not info["powered"])
        if not info["powered"]:
            try:
                self.session.open()
            except bt.BluetoothError:
                pass
            return "Bluetooth ligado."
        return "Bluetooth desligado."

    def task_pair(self, device):
        connected = self.session.pair(device["mac"])
        if connected:
            return "%s pareado e conectado." % (device["name"],)
        return "%s pareado, mas não conectou." % (device["name"],)

    def task_connect(self, device):
        bt.connect(device["mac"])
        return "%s conectado." % (device["name"],)

    def task_disconnect(self, device):
        bt.disconnect(device["mac"])
        return "%s desconectado." % (device["name"],)

    def task_remove(self, device):
        bt.remove(device["mac"])
        return "%s removido." % (device["name"],)

    # ------------------------------------------------------------------ menu

    def device_menu(self):
        position = self.getControl(CTRL_LIST).getSelectedPosition()
        if position < 0 or position >= len(self.devices):
            return
        device = self.devices[position]

        if device["connected"]:
            options = [("Desconectar", "Desconectando...", self.task_disconnect),
                       ("Esquecer dispositivo", "Removendo...", self.task_remove)]
        elif device["paired"]:
            options = [("Conectar", "Conectando...", self.task_connect),
                       ("Esquecer dispositivo", "Removendo...", self.task_remove)]
        else:
            options = [("Parear e conectar", "Pareando... confirme no celular.", self.task_pair)]

        choice = xbmcgui.Dialog().select(device["name"], [option[0] for option in options])
        if choice < 0:
            return
        label, status, task = options[choice]
        if task == self.task_remove:
            if not xbmcgui.Dialog().yesno("Bluetooth", "Esquecer %s?" % (device["name"],)):
                return
        self.run_task(status, task, device)

    def open_libreelec_settings(self):
        if xbmc.getCondVisibility("System.HasAddon(%s)" % (LIBREELEC_SETTINGS,)):
            self.shutdown()
            xbmc.executebuiltin("RunAddon(%s)" % (LIBREELEC_SETTINGS,))
        else:
            xbmcgui.Dialog().notification(
                "Bluetooth", "Configurações do LibreELEC não encontradas",
                xbmcgui.NOTIFICATION_WARNING, 4000)


def main():
    home = xbmcgui.Window(10000)
    if home.getProperty(RUNNING_PROPERTY):
        return  # ja esta aberta
    home.setProperty(RUNNING_PROPERTY, "true")
    try:
        window = BluetoothWindow(WINDOW_XML, SKIN_PATH, "Default", "720p")
        window.doModal()
        window.closing = True
        del window
    finally:
        home.clearProperty(RUNNING_PROPERTY)


if __name__ == "__main__":
    main()
