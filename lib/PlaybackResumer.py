"""
Serviço de "Resume" embutido no skin CarPc-Carbon.

Funciona como o add-on script.service.playbackresumer, mais o suporte a
playlists de música:

- Salva periodicamente o que está tocando (padrão: a cada 5 s) em
  addon_data/skin.CarPc-Carbon/resume.json, com gravação atômica (sobrevive
  a queda de energia).
- Para vídeos, também grava o ponto de retomada no banco do Kodi
  (Files.SetFileDetails / VideoLibrary.Set*Details), então o "Retomar de ..."
  nativo do Kodi fica sempre atualizado.
- Respeita o advancedsettings.xml do Kodi (video/ignoresecondsatstart e
  video/ignorepercentatend): não salva nos primeiros segundos nem perto do fim.
- Parar (Stop) mantém o ponto salvo; o vídeo é retomado no próximo boot.
- Terminar o vídeo / a playlist zera o ponto (não retoma).
- Kodi encerrando / queda de energia mantém o ponto.
- Ao iniciar o Kodi, retoma o vídeo já na posição salva (StartOffset), ou
  recria a playlist de música na faixa e posição salvas.
- Enquanto a câmera de ré estiver ativa nada é salvo (a ré tem sua própria
  restauração no service.py).

Configuração (Skin settings):
- Skin.HasSetting(DisableResume)        -> desliga o resume
- Skin.String(ResumeSaveInterval)       -> intervalo de gravação em segundos (padrão 5)
- Skin.String(ResumeStartupDelay)       -> espera extra antes de retomar (padrão 0)
"""

import json
import os
import threading
import time
import xml.etree.ElementTree as ET

import xbmc
import xbmcgui
import xbmcvfs

ADDON_ID = "skin.CarPc-Carbon"
LOG_PREFIX = "[CarPC Resume]"

DEFAULT_SAVE_INTERVAL = 5
MIN_SAVE_INTERVAL = 2
# Padrões do Kodi quando não há advancedsettings.xml
DEFAULT_IGNORE_SECONDS_AT_START = 180
DEFAULT_IGNORE_PERCENT_AT_END = 8


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


def _fmt(seconds):
    seconds = int(seconds or 0)
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _read_advanced_settings():
    ignore_start = DEFAULT_IGNORE_SECONDS_AT_START
    ignore_end = DEFAULT_IGNORE_PERCENT_AT_END
    path = xbmcvfs.translatePath("special://profile/advancedsettings.xml")
    if os.path.exists(path):
        try:
            root = ET.parse(path).getroot()
            value = root.findtext("video/ignoresecondsatstart")
            if value is not None and value.strip():
                ignore_start = int(float(value))
            value = root.findtext("video/ignorepercentatend")
            if value is not None and value.strip():
                ignore_end = int(float(value))
        except Exception as e:
            _log(f"Falha ao ler advancedsettings.xml: {e}", xbmc.LOGWARNING)
    return ignore_start, ignore_end


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

        self.ignore_seconds_at_start, self.ignore_percent_at_end = _read_advanced_settings()
        _log(f"ignoresecondsatstart={self.ignore_seconds_at_start} "
             f"ignorepercentatend={self.ignore_percent_at_end}")

        self._lock = threading.Lock()
        self._items_cache = None       # (playlistid, [files])
        self._items_dirty = True
        self._restoring = False
        self._last_state = self._read_state()

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

    # ------------------------------------------ ponto de retomada no Kodi (vídeo)
    @staticmethod
    def _is_video(state):
        return bool(state) and state.get("type") == "video" and not state.get("live")

    def _set_kodi_resume_point(self, state, position):
        """Grava o "Retomar de ..." no banco do Kodi, como o PlaybackResumer."""
        if not self._is_video(state):
            return
        file_path = state.get("file") or ""
        if file_path.startswith("pvr://"):
            return  # Kodi não aceita SetFileDetails para pvr://
        resume = {"position": max(0, int(position)), "total": int(state.get("totaltime") or 0)}
        media_type = state.get("media_type")
        dbid = state.get("dbid")
        if dbid and media_type == "episode":
            _jsonrpc("VideoLibrary.SetEpisodeDetails", {"episodeid": dbid, "resume": resume})
        elif dbid and media_type == "movie":
            _jsonrpc("VideoLibrary.SetMovieDetails", {"movieid": dbid, "resume": resume})
        elif dbid and media_type == "musicvideo":
            _jsonrpc("VideoLibrary.SetMusicVideoDetails", {"musicvideoid": dbid, "resume": resume})
        elif file_path:
            _jsonrpc("Files.SetFileDetails", {"file": file_path, "media": "video", "resume": resume})

    # ---------------------------------------------------------------- snapshot
    @staticmethod
    def _active_player():
        players = _jsonrpc("Player.GetActivePlayers") or []
        for wanted in ("video", "audio"):
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
        if file_path.startswith("udp://") or "video_pipe" in file_path:
            return True
        if ignored and file_path == ignored:
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

        item = (_jsonrpc("Player.GetItem", {
            "playerid": playerid,
            "properties": ["title", "showtitle", "season", "episode"],
        }) or {}).get("item", {})

        playlistid = props.get("playlistid", -1)
        position = props.get("position", -1)
        items = self._playlist_items(playlistid) if playlistid is not None and playlistid >= 0 else []
        if position is None or position < 0 or position >= len(items) or items[position] != current_file:
            # Reprodução avulsa (sem playlist ou playlist inconsistente).
            items, position = [], -1
        if player.get("type") == "video" and len(items) <= 1:
            items, position = [], -1  # vídeo avulso: retoma só o arquivo (como o PlaybackResumer)

        return {
            "version": 2,
            "saved_at": time.time(),
            "type": player.get("type"),
            "file": current_file,
            "title": item.get("title") or item.get("label") or "",
            "media_type": item.get("type"),
            "dbid": item.get("id"),
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

        if self._is_video(state):
            seconds = state["time"]
            total = state["totaltime"]
            # Mesmas regras do Kodi/PlaybackResumer: ignora o começo e o fim.
            if 0 < seconds < self.ignore_seconds_at_start:
                return
            if total > 0 and (seconds / total) * 100 > 100 - self.ignore_percent_at_end:
                return

        with self._lock:
            self._last_state = state
            self._write_state(state)
        self._set_kodi_resume_point(state, state["time"])

    # ------------------------------------------------------------ eventos Kodi
    def onAVStarted(self):
        self._items_dirty = True
        # Pequena espera para o player estabilizar antes do primeiro snapshot.
        # (callbacks rodam dentro do loop do serviço: usar time.sleep, não waitForAbort)
        time.sleep(1.5)
        if self.monitor.abortRequested() or self._restoring or self.is_suspended():
            return
        try:
            current_file = self.getPlayingFile()
        except RuntimeError:
            return
        if self._should_ignore(current_file):
            return
        last = self._last_state
        if last and last.get("file") != current_file and self.isPlayingVideo() \
                and current_file not in (last.get("items") or []):
            # Outro vídeo começou: o ponto antigo deixa de valer (como o PlaybackResumer).
            self.clear_state("outro vídeo iniciado")
        self.save_now()

    def onPlayBackSeek(self, time_ms, seek_offset_ms):
        self.save_now()

    def onPlayBackSeekChapter(self, chapter):
        self.save_now()

    def onPlayBackPaused(self):
        self.save_now()

    def onPlayBackStopped(self):
        # Como o PlaybackResumer: parar NÃO apaga o ponto; retoma no próximo boot.
        _log("Reprodução parada: ponto de retomada mantido")

    def onPlayBackEnded(self):
        if self._restoring or self.is_suspended():
            return
        # Espera para distinguir fim real de troca de mídia / Kodi encerrando.
        for _ in range(30):
            if self.monitor.abortRequested():
                _log("Kodi encerrando: estado preservado para o próximo boot")
                return
            if self.isPlaying() or self.is_suspended():
                return
            time.sleep(0.1)
        last = self._last_state
        if last:
            self._set_kodi_resume_point(last, 0)
        self.clear_state("reprodução terminou")

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
                    if self.getTime() >= seconds - 2:
                        return True
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

        resume_at = 0.0 if state.get("live") else float(state.get("time") or 0)
        if self._is_video(state) and resume_at < self.ignore_seconds_at_start:
            _log(f"Posição salva ({resume_at:.0f}s) abaixo de ignoresecondsatstart: não retoma")
            return False

        self._wait_for_home()
        delay = self._int_skin_string("ResumeStartupDelay", 0)
        if delay > 0 and self.monitor.waitForAbort(delay):
            return False

        if self.isPlaying() or self.is_suspended():
            _log("Já há algo tocando (ou ré engatada): resume ignorado")
            return False

        self._restoring = True
        try:
            started = False
            items = state.get("items") or []
            playlistid = state.get("playlistid", -1)
            position = state.get("position", -1)

            if items and playlistid is not None and playlistid >= 0 and 0 <= position < len(items):
                _log(f"Retomando playlist {playlistid}: {len(items)} itens, "
                     f"faixa {position + 1}, {_fmt(resume_at)}")
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
                if started:
                    self._seek(resume_at)
            else:
                _log(f"Retomando {state['file']} em {_fmt(resume_at)}")
                list_item = xbmcgui.ListItem(path=state["file"])
                if state.get("title"):
                    list_item.setLabel(state["title"])
                if resume_at > 0:
                    # Abre já na posição salva, como o PlaybackResumer.
                    list_item.setProperty("StartOffset", str(resume_at))
                self.play(state["file"], list_item)
                started = self._wait_until_playing(10)
                if started and resume_at > 0:
                    self._seek(resume_at)  # garante a posição se o StartOffset for ignorado

            if not started:
                _log("Kodi não iniciou a reprodução salva", xbmc.LOGERROR)
                return False

            label = state.get("title") or xbmc.getInfoLabel("Player.Title") \
                or os.path.basename(state["file"])
            message = f"{label} em {_fmt(resume_at)}" if resume_at > 0 else label
            xbmcgui.Dialog().notification("Retomando", message, xbmcgui.NOTIFICATION_INFO, 5000, False)
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
