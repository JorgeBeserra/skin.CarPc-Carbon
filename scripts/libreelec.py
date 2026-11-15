# -*- coding: utf-8 -*-
"""Abre a tela de configuracoes do LibreELEC (a mesma do skin padrao Estuary),
opcionalmente ja em uma das abas.

    RunScript(special://skin/scripts/libreelec.py)             -> primeira aba
    RunScript(special://skin/scripts/libreelec.py,bluetooth)   -> aba Bluetooth
    RunScript(special://skin/scripts/libreelec.py,services)    -> aba Servicos
    RunScript(special://skin/scripts/libreelec.py,connman)     -> aba Rede

A tela pertence ao addon service.libreelec.settings. O menu lateral dela e a
lista 1000 e cada item guarda o nome do modulo na propriedade "modul"; focar o
item faz a tela carregar a aba correspondente.
"""

import sys

import xbmc
import xbmcgui

ADDON_ID = "service.libreelec.settings"
MENU_LIST = 1000
OPEN_TIMEOUT = 10.0


def is_installed():
    return xbmc.getCondVisibility("System.AddonIsEnabled(%s)" % (ADDON_ID,))


def _menu_module(position):
    return xbmc.getInfoLabel(
        "Container(%d).ListItemAbsolute(%d).Property(modul)" % (MENU_LIST, position))


def _menu_size():
    try:
        return int(xbmc.getInfoLabel("Container(%d).NumItems" % (MENU_LIST,)) or 0)
    except ValueError:
        return 0


def open_settings(module=""):
    """Abre a tela. Devolve False se o addon nao existir (nao e um LibreELEC)."""
    if not is_installed():
        return False

    xbmc.executebuiltin("RunAddon(%s)" % (ADDON_ID,))
    module = (module or "").strip().lower()
    if not module:
        return True

    monitor = xbmc.Monitor()
    waited = 0.0
    # espera o menu lateral da tela do LibreELEC ser preenchido
    while waited < OPEN_TIMEOUT and not _menu_module(0):
        if monitor.waitForAbort(0.25):
            return True
        waited += 0.25

    for position in range(_menu_size()):
        if _menu_module(position).lower() == module:
            xbmc.executebuiltin("SetFocus(%d,%d,absolute)" % (MENU_LIST, position))
            break
    else:
        xbmc.log("[CarPc LibreELEC] aba '%s' nao encontrada" % (module,), xbmc.LOGWARNING)
    return True


def main():
    module = sys.argv[1] if len(sys.argv) > 1 else ""
    if not open_settings(module):
        xbmcgui.Dialog().notification(
            "LibreELEC", "Configurações do LibreELEC não encontradas",
            xbmcgui.NOTIFICATION_WARNING, 4000)


if __name__ == "__main__":
    main()
