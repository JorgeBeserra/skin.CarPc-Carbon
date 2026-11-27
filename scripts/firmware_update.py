# -*- coding: utf-8 -*-
"""Atualiza o firmware do ESP32 pelo Raspberry.

    RunScript(special://skin/scripts/firmware_update.py)

1. Busca o ultimo release do firmware no GitHub (build-N) e baixa os .bin.
2. Confere o SHA256 de cada arquivo antes de tocar no ESP32.
3. Pede a porta serial ao service.py (ele fecha a porta e confirma).
4. Grava com lib/firmware_flash.py (sem erase_flash, com verificacao e novas
   tentativas) e devolve a porta ao service.py no final, mesmo com erro.
"""
import json
import os
import shutil
import sys
import time
import urllib.request

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

SKIN_DIR = xbmcvfs.translatePath("special://skin/")
sys.path.insert(0, os.path.join(SKIN_DIR, "lib"))

from firmware_flash import IMAGES, FlashError, flash, parse_sha256sums, verify_files  # noqa: E402

REPO = "JorgeBeserra/esp32_carpc-carbon"
RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/latest"
TITLE = "Firmware do ESP32"

SERIAL_PAUSE_PROP = "carpc_serial_pause_until"
SERIAL_RELEASED_PROP = "carpc_serial_released"
PAUSE_SECONDS = 600  # o service.py retoma a serial sozinho depois disso
LOG_FILE = xbmcvfs.translatePath("special://temp/firmware_update.log")


def log(msg, level=xbmc.LOGINFO):
    xbmc.log(f"[firmware_update] {msg}", level)


def serial_port():
    try:
        port = xbmcaddon.Addon("skin.CarPc-Carbon").getSetting("serial_port")
    except Exception:
        port = ""
    return port or "/dev/ttyUSB0"


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "CarPc-Carbon-skin"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def latest_release():
    data = json.loads(http_get(RELEASE_API).decode("utf-8"))
    assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}
    needed = [name for _, name in IMAGES] + ["SHA256SUMS"]
    missing = [n for n in needed if n not in assets]
    if missing:
        raise FlashError("Release sem os arquivos: " + ", ".join(missing))
    return data.get("tag_name", "?"), assets


def download(assets, folder, progress):
    if os.path.isdir(folder):
        shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder)
    names = [name for _, name in IMAGES] + ["SHA256SUMS"]
    for i, name in enumerate(names):
        progress.update(int(100 * i / len(names)), f"Baixando {name}...")
        content = http_get(assets[name], timeout=60)
        path = os.path.join(folder, name)
        with open(path, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
    with open(os.path.join(folder, "SHA256SUMS"), encoding="utf-8") as f:
        return parse_sha256sums(f.read())


def acquire_serial(home, monitor, timeout=10):
    home.clearProperty(SERIAL_RELEASED_PROP)
    home.setProperty(SERIAL_PAUSE_PROP, str(time.time() + PAUSE_SECONDS))
    end = time.time() + timeout
    while time.time() < end and not monitor.abortRequested():
        if home.getProperty(SERIAL_RELEASED_PROP) == "true":
            monitor.waitForAbort(1)  # deixa a porta fechar de vez
            return True
        monitor.waitForAbort(0.2)
    return False


def release_serial(home):
    home.clearProperty(SERIAL_PAUSE_PROP)


def main():
    dialog = xbmcgui.Dialog()
    monitor = xbmc.Monitor()
    home = xbmcgui.Window(10000)
    folder = xbmcvfs.translatePath("special://temp/esp32_firmware/")
    port = serial_port()

    if home.getProperty(SERIAL_PAUSE_PROP):
        try:
            busy = float(home.getProperty(SERIAL_PAUSE_PROP)) > time.time()
        except ValueError:
            busy = False
        if busy:
            dialog.ok(TITLE, "Ja existe uma atualizacao de firmware em andamento.")
            return

    progress = xbmcgui.DialogProgress()
    progress.create(TITLE, "Procurando a versao mais recente...")
    try:
        tag, assets = latest_release()
        sums = download(assets, folder, progress)
        progress.update(100, "Conferindo os arquivos...")
        verify_files(folder, sums)
    except Exception as e:
        progress.close()
        log(f"Falha no download: {e}", xbmc.LOGERROR)
        dialog.ok(TITLE, f"Nao foi possivel baixar o firmware.[CR]{e}[CR][CR]Nada foi gravado no ESP32.")
        return
    progress.close()

    if not dialog.yesno(TITLE,
                        f"Gravar o firmware {tag} no ESP32 ({port})?[CR][CR]"
                        "Leva de 2 a 4 minutos. Mantenha a ignicao ligada e nao desligue o carro.",
                        nolabel="Cancelar", yeslabel="Gravar"):
        return

    progress.create(TITLE, "Liberando a porta serial...")
    log_lines = []
    try:
        if not acquire_serial(home, monitor):
            raise FlashError("O servico do skin nao liberou a porta serial")

        def on_progress(pct, text):
            progress.update(pct, text + "[CR]Nao desligue o carro.")

        tools_dir = os.path.join(SKIN_DIR, "tools")
        lib_dir = os.path.join(SKIN_DIR, "lib")
        flash(folder, port, tools_dir, lib_dir, on_progress=on_progress, on_log=log_lines.append)
        ok, message = True, f"Firmware {tag} gravado e verificado.[CR]O ESP32 foi reiniciado."
    except FlashError as e:
        ok, message = False, (f"A gravacao falhou: {e}[CR][CR]O ESP32 continua podendo ser gravado; "
                              f"tente de novo. Detalhes em {LOG_FILE}")
    except Exception as e:
        ok, message = False, f"Erro inesperado: {e}"
    finally:
        release_serial(home)
        progress.close()
        try:
            with open(LOG_FILE, "w", encoding="utf-8") as f:
                f.write("\n".join(log_lines))
        except Exception:
            pass

    log(message.replace("[CR]", " "), xbmc.LOGINFO if ok else xbmc.LOGERROR)
    dialog.ok(TITLE, message)


if __name__ == "__main__":
    main()
