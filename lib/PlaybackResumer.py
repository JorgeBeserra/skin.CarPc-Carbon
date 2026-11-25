"""
Serviço de "Resume" embutido no skin CarPc-Carbon.

Salva periodicamente o que está tocando (playlist completa, faixa atual,
posição, repeat) em addon_data e, ao iniciar o Kodi, retoma a reprodução.
Pensado para o carro: a energia pode cair a qualquer momento, então o estado
é gravado de forma atômica a cada N segundos, e não apenas no desligamento.

Regras:
- Parar manualmente (Stop) ou terminar a playlist apaga o estado -> não retoma.
- Kodi encerrando / queda de energia mantém o estado -> retoma no próximo boot.
- Enquanto a câmera de ré estiver ativa nada é salvo (a ré tem sua própria
  restauração no service.py).

Configuração (Skin settings):
- Skin.HasSetting(DisableResume)        -> desliga o resume
- Skin.String(ResumeSaveInterval)       -> intervalo de gravação em segundos (padrão 10)
- Skin.String(ResumeStartupDelay)       -> espera extra antes de retomar (padrão 0)
"""

import json
import os
import threading
import time

import xbmc
import xbmcgui
import xbmcvfs

ADDON_ID = "skin.CarPc-Carbon"
LOG_PREFIX = "[CarPC Resume]"

DEFAULT_SAVE_INTERVAL = 10
MIN_SAVE_INTERVAL = 3
# Ao retomar, volta alguns segundos para não "perder" o trecho que estava tocando.
REWIND_SECONDS = 3
# Próximo do fim da faixa (sem playlist), considera como terminada.
END_MARGIN_SECONDS = 5


def _log(msg, level=xbmc.LOGINFO):
    xbmc.log(f"{LOG_PREFIX} {msg}", level)


def _jsonrpc(method, params=None):
    payload = {"jsonrpc": "2.0", "method": method, "id": 1}
    if params is not None:
        payload["params"] = params
    try:
        response = json.loads(xbmc.executeJSONRPC(json.dumps(payload)))
    except Exception as e:
        _log(f"JSONRPC {method} falhou: {e}", xbmc.LOGERROR)
        return None
    if "error" in response:
        _log(f"JSONRPC {method} erro: {response['error']}", xbmc.LOGWARNING)
        return None
    return response.get("result")


def _time_to_seconds(t):
    if not t:
        return 0.0
    return (t.get("hours", 0) * 3600 + t.get("minutes", 0) * 60
            + t.get("seconds", 0) + t.get("milliseconds", 0) / 1000.0)


def _seconds_to_time(seconds):
    seconds = max(0.0, float(seconds))
    return {
        "hours": int(seconds // 3600),
        "minutes": int((seconds % 3600) // 60),
        "seconds": int(seconds % 60),
        "milliseconds": int((seconds - int(seconds)) * 1000),
    }


class PlaybackResumer(xbmc.Player):
    def __init__(self, monitor, is_suspended=None, ignored_file=None):
        """
        monitor:       xbmc.Monitor compartilhado do serviço
        is_suspended:  callable -> True enquanto a câmera de ré está ativa
        ignored_file:  callable -> URL do stream da câmera (nunca salvar)
        """
        super().__init__()
        self.monitor = monitor
        self.is_suspended = is_suspended or (lambda: False)
        self.ignored_file = ignored_file or (lambda: None)

        profile = xbmcvfs.translatePath(f"special://profile/addon_data/{ADDON_ID}/")
        if not os.path.isdir(profile):
            try:
                os.makedirs(profile)
            except Exception as e:
                _log(f"Não foi possível criar {profile}: {e}", xbmc.LOGERROR)
        self.state_file = os.path.join(profile, "resume.json")

        self._lock = threading.Lock()
        self._items_cache = None       # (playlistid, [files])
        self._items_dirty = True
        self._restoring = False
        self._last_state = None

    # ------------------------------------------------------------------ config
    @staticmethod
    def enabled():
        return not xbmc.getCondVisibility("Skin.HasSetting(DisableResume)")

    @staticmethod
    def _int_skin_string(name, default):
        try:
            value = int(xbmc.getInfoLabel(f"Skin.String({name})") or default)
        except ValueError:
            value = default
        return value

    def save_interval(self):
        return max(MIN_SAVE_INTERVAL, self._int_skin_string("ResumeSaveInterval", DEFAULT_SAVE_INTERVAL))

    # ------------------------------------------------------------ persistência
    def _write_state(self, state):
        tmp = self.state_file + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.state_file)  # atômico: sobrevive a queda de energia
        except Exception as e:
            _log(f"Falha ao gravar estado: {e}", xbmc.LOGERROR)

    def _read_state(self):
        if not os.path.exists(self.state_file):
            return None
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            _log(f"Estado inválido, ignorando: {e}", xbmc.LOGERROR)
            return None

    def clear_state(self, reason=""):
        with self._lock:
            self._last_state = None
            if os.path.exists(self.state_file):
                try:
                    os.remove(self.state_file)
                    _log(f"Estado apagado ({reason})")
                except Exception as e:
                    _log(f"Falha ao apagar estado: {e}", xbmc.LOGERROR)

    # ---------------------------------------------------------------- snapshot
    @staticmethod
    def _active_player():
        players = _jsonrpc("Player.GetActivePlayers") or []
        for wanted in ("audio", "video"):
            for p in players:
                if p.get("type") == wanted:
                    return p
        return None

    def _playlist_items(self, playlistid):
        cache = self._items_cache
        if not self._items_dirty and cache and cache[0] == playlistid:
            # Confere se o tamanho mudou (itens adicionados/removidos).
            props = _jsonrpc("Playlist.GetProperties",
                             {"playlistid": playlistid, "properties": ["size"]}) or {}
            if props.get("size") == len(cache[1]):
                return cache[1]

        result = _jsonrpc("Playlist.GetItems",
                          {"playlistid": playlistid, "properties": ["file"]}) or {}
        files = [it.get("file") for it in result.get("items", []) if it.get("file")]
        self._items_cache = (playlistid, files)
        self._items_dirty = False
        return files

    def _should_ignore(self, file_path):
        if not file_path:
            return True
        ignored = self.ignored_file()
        if ignored and (file_path == ignored or file_path.startswith("udp://")
                        or "video_pipe" in file_path):
            return True
        return False

    def snapshot(self):
        player = self._active_player()
        if not player:
            return None
        playerid = player["playerid"]
        props = _jsonrpc("Player.GetProperties", {
            "playerid": playerid,
            "properties": ["playlistid", "position", "time", "totaltime", "repeat", "live"],
        }) or {}
        try:
            current_file = self.getPlayingFile()
        except RuntimeError:
            return None
        if self._should_ignore(current_file):
            return None

        playlistid = props.get("playlistid", -1)
        position = props.get("position", -1)
        items = self._playlist_items(playlistid) if playlistid is not None and playlistid >= 0 else []
        if position is None or position < 0 or position >= len(items) or items[position] != current_file:
            # Reprodução avulsa (sem playlist ou playlist inconsistente).
            items, position = [], -1

        return {
            "version": 1,
            "saved_at": time.time(),
            "type": player.get("type"),
            "file": current_file,
            "time": _time_to_seconds(props.get("time")),
            "totaltime": _time_to_seconds(props.get("totaltime")),
            "live": bool(props.get("live")),
            "playlistid": playlistid,
            "position": position,
            "items": items,
            "repeat": props.get("repeat", "off"),
        }

    def save_now(self):
        if self._restoring or self.is_suspended() or not self.enabled():
            return
        if not self.isPlaying():
            return
        state = self.snapshot()
        if not state:
            return
        with self._lock:
            self._last_state = state
            self._write_state(state)

    # ------------------------------------------------------------ eventos Kodi
    def onAVStarted(self):
        self._items_dirty = True
        # Pequena espera para o player estabilizar antes do primeiro snapshot.
        # (callbacks rodam dentro do loop do serviço: usar time.sleep, não waitForAbort)
        time.sleep(1.5)
        if not self.monitor.abortRequested():
            self.save_now()

    def onPlayBackSeek(self, time_ms, seek_offset_ms):
        self.save_now()

    def onPlayBackPaused(self):
        self.save_now()

    def onPlayBackStopped(self):
        self._handle_end("parado pelo usuário")

    def onPlayBackEnded(self):
        self._handle_end("reprodução terminou")

    def _handle_end(self, reason):
        if self._restoring or self.is_suspended():
            return
        # Se o Kodi está fechando (Quit/desligamento), o Stop vem antes do abort:
        # espera um pouco para distinguir e preservar o estado.
        for _ in range(30):
            if self.monitor.abortRequested():
                _log("Kodi encerrando: estado preservado para o próximo boot")
                return
            if self.isPlaying() or self.is_suspended():
                # Outra mídia (ou a câmera de ré) começou: não apaga.
                return
            time.sleep(0.1)
        self.clear_state(reason)

    # ---------------------------------------------------------------- restore
    def _wait_until_playing(self, timeout):
        end = time.time() + timeout
        while time.time() < end:
            if self.monitor.abortRequested():
                return False
            if self.isPlaying():
                return True
            xbmc.sleep(100)
        return False

    def _seek(self, seconds, timeout=8.0):
        if seconds <= 0:
            return True
        end = time.time() + timeout
        while time.time() < end and not self.monitor.abortRequested():
            try:
                if self.isPlaying() and self.getTotalTime() > 0:
                    self.seekTime(seconds)
                    xbmc.sleep(300)
                    if self.getTime() >= seconds - 2:
                        return True
            except RuntimeError:
                pass
            xbmc.sleep(200)
        _log(f"Não foi possível posicionar em {seconds:.0f}s", xbmc.LOGWARNING)
        return False

    def _wait_for_home(self, timeout=30):
        end = time.time() + timeout
        while time.time() < end and not self.monitor.abortRequested():
            if xbmc.getCondVisibility("Window.IsActive(home)") and \
               not xbmc.getCondVisibility("Window.IsActive(startup)"):
                return True
            xbmc.sleep(250)
        return False

    def resume_on_startup(self):
        if not self.enabled():
            _log("Resume desativado nas configurações do skin")
            return False
        state = self._read_state()
        if not state or not state.get("file"):
            _log("Nada para retomar")
            return False

        self._wait_for_home()
        delay = self._int_skin_string("ResumeStartupDelay", 0)
        if delay > 0 and self.monitor.waitForAbort(delay):
            return False

        if self.isPlaying() or self.is_suspended():
            _log("Já há algo tocando (ou ré engatada): resume ignorado")
            return False

        resume_at = 0.0
        if not state.get("live") and state.get("totaltime", 0) > 0:
            resume_at = max(0.0, state.get("time", 0) - REWIND_SECONDS)
            if state["totaltime"] - resume_at <= END_MARGIN_SECONDS and not state.get("items"):
                resume_at = 0.0

        self._restoring = True
        try:
            started = False
            items = state.get("items") or []
            playlistid = state.get("playlistid", -1)
            position = state.get("position", -1)

            if items and playlistid is not None and playlistid >= 0 and 0 <= position < len(items):
                _log(f"Retomando playlist {playlistid}: {len(items)} itens, faixa {position + 1}, {resume_at:.0f}s")
                _jsonrpc("Playlist.Clear", {"playlistid": playlistid})
                _jsonrpc("Playlist.Add", {"playlistid": playlistid,
                                          "item": [{"file": f} for f in items]})
                _jsonrpc("Player.Open", {"item": {"playlistid": playlistid, "position": position}})
                started = self._wait_until_playing(10)
                if started and state.get("repeat") in ("one", "all"):
                    player = self._active_player()
                    if player:
                        _jsonrpc("Player.SetRepeat", {"playerid": player["playerid"],
                                                      "repeat": state["repeat"]})
            else:
                _log(f"Retomando mídia {state['file']} em {resume_at:.0f}s")
                self.play(state["file"])
                started = self._wait_until_playing(10)

            if not started:
                _log("Kodi não iniciou a reprodução salva", xbmc.LOGERROR)
                return False

            self._seek(resume_at)
            label = xbmc.getInfoLabel("Player.Title") or os.path.basename(state["file"])
            xbmcgui.Dialog().notification("Retomando", label, xbmcgui.NOTIFICATION_INFO, 3000, False)
            return True
        except Exception as e:
            _log(f"Erro ao retomar: {e}", xbmc.LOGERROR)
            return False
        finally:
            self._restoring = False
            self._items_dirty = True
            self.save_now()

    # -------------------------------------------------------------------- loop
    def run(self):
        """Executa em uma thread própria: retoma no boot e salva periodicamente."""
        _log("Serviço iniciado")
        self.resume_on_startup()

        while not self.monitor.abortRequested():
            interval = self.save_interval()
            if self.monitor.waitForAbort(interval):
                break
            try:
                self.save_now()
            except Exception as e:
                _log(f"Erro no salvamento periódico: {e}", xbmc.LOGERROR)

        _log("Serviço encerrado (estado preservado)")
