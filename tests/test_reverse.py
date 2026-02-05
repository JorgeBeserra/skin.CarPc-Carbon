# -*- coding: utf-8 -*-
import sys
import os
import xbmc
import xbmcaddon

# Ensure addon path is on sys.path
ADDON_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ADDON_PATH not in sys.path:
    sys.path.append(ADDON_PATH)

# Force addon id for service.py import when script is not executed as addon
_real_addon = xbmcaddon.Addon

def _addon(id=None):
    try:
        return _real_addon("skin.CarPc-Carbon")
    except Exception:
        if id:
            return _real_addon(id)
        return _real_addon("skin.CarPc-Carbon")

xbmcaddon.Addon = _addon

try:
    import service
except Exception as e:
    xbmc.log(f"test_reverse: falha ao importar service.py: {e}", xbmc.LOGERROR)
    raise


def _get_action():
    if len(sys.argv) > 1:
        return sys.argv[1].strip().lower()
    return "play"


def run():
    action = _get_action()
    player = service.ReverseVideoPlayer()

    xbmc.log(f"test_reverse: action={action}", xbmc.LOGINFO)

    if action in ("play", "start", "reverse", "on"):
        player.play_reverse_video()
        xbmc.log("test_reverse: play_reverse_video executado", xbmc.LOGINFO)
    elif action in ("stop", "off"):
        player.stop_reverse_video()
        xbmc.log("test_reverse: stop_reverse_video executado", xbmc.LOGINFO)
    else:
        xbmc.log(f"test_reverse: acao desconhecida: {action}", xbmc.LOGERROR)


if __name__ == "__main__":
    run()
