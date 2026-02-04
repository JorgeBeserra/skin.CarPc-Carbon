import sys
import os
import platform
import tempfile
import socket
import xbmc
import xbmcaddon
import xbmcgui
import subprocess
import time
import threading
import json
import shutil
import signal

from xbmc import Monitor, Player

from lib.ReverseGearManager import ReverseGearManager
from lib.can_parser import CANParser

serial_conn = None
serial_lock = threading.Lock()

addon = None
try:
    addon = xbmcaddon.Addon("skin.CarPc-Carbon")
except Exception:
    try:
        addon = xbmcaddon.Addon()
    except Exception:
        addon = None

# Adiciona o diretório do addon e a pasta lib ao sys.path
addon_path = addon.getAddonInfo('path') if addon else ''
if not addon_path:
    addon_path = os.path.dirname(os.path.abspath(__file__))
lib_path = os.path.join(addon_path, 'lib')

if lib_path not in sys.path:
    sys.path.append(lib_path)

try:
    import serial
    xbmc.log("PySerial importado com sucesso!", xbmc.LOGINFO)
except ImportError:
    xbmc.log("Falha ao importar PySerial", xbmc.LOGERROR)
    sys.exit()
# Configuração do Addon
monitor = Monitor()

# Configuração global com lock de thread
door_status = {
    "driver": "Fechada",
    "passenger": "Fechada",
    "rear_left": "Fechada",
    "rear_right": "Fechada",
    "trunk": "Fechado",
    "reverse_gear": "Não Engatada"
}
status_lock = threading.Lock()


def adjust_volume(direction):
    current_volume = xbmc.getInfoLabel("Player.Volume")  # Retorna volume em dB (ex.: "-12.0 dB")
    current_volume = float(current_volume.replace(" dB", ""))  # Converte para float
    step = 2  # Ajuste em 2 dB por vez (pode mudar)
    new_volume = current_volume - step if direction == "down" else current_volume + step
    new_volume = max(-60, min(0, new_volume))  # Limita entre -60 dB e 0 dB
    xbmc.executebuiltin(f"SetVolume({int(new_volume * 100 / 60 + 100)})")

def get_serial_config():
    system = platform.system()
    default_port = "COM3" if system == "Windows" else "/dev/ttyUSB0"

    port = addon.getSetting("serial_port") if addon else ""
    if not port:
        port = default_port

    baud = addon.getSetting("baud_rate") if addon else ""
    try:
        baudrate = int(baud) if baud else 115200
    except ValueError:
        baudrate = 115200

    return {
        'port': port,
        'baudrate': baudrate,
        'timeout': 0.1
    }

# Função para mostrar a caixa de diálogo
def mostrar_dialogo_desligamento():
    xbmc.log("Kodi: Gerando Dialogo com contador", xbmc.LOGINFO)
    # Criação da caixa de diálogo
    pDialog = xbmcgui.DialogProgress()
    mensagem_base = "O desligamento está próximo. Deseja cancelar ou re-agendar?"
    botoes = ["Cancelar", "Re-agendar"]
    tempo_total = 30  # Tempo em segundos para o contador
    tempo_restante = tempo_total

    # Variável para controlar a escolha do usuário
    escolha = None
    dialog_closed = False

    pDialog.create("Desligamento Próximo", f"{mensagem_base}\nDesligando em {tempo_restante} segundos...")
    for i in range(tempo_total, -1, -1):
        tempo_restante = i
        if monitor.abortRequested() or pDialog.iscanceled():
            pDialog.close()
            xbmc.log("Diálogo cancelado pelo usuário ou Kodi", xbmc.LOGINFO)
            return
        percent = int((i / tempo_total) * 100)
        pDialog.update(percent, f"{mensagem_base}\nDesligando em {i} segundos...")
        time.sleep(1)
        
    pDialog.close()

    # Após o contador, verifica se o tempo esgotou
    if tempo_restante == 0:
        xbmc.log("Tempo esgotado, encerrando Kodi", xbmc.LOGINFO)
        xbmc.executebuiltin("Quit")
    else:
        # Mostra o diálogo de escolha
        xbmc.log("Tempo nao acabou", xbmc.LOGINFO)


def parse_can_message(raw_data):
    """Processa os dados brutos do CAN bus e determina o status das portas."""
    global door_status

    try:
        xbmc.log(f"Debug CAN: {str(raw_data)}", xbmc.LOGINFO)
        
        # Bugs
        #if raw_data == "ShutdownForInactivity":
        #    xbmc.log("Kodi: Desligando o sistema após inatividade", xbmc.LOGINFO)
        #    mostrar_dialogo_desligamento()

        # Verifica se é uma mensagem de ADC
        if "ADC Click:" in raw_data:
            adc_value = int(raw_data.split("ADC Click: ")[1].strip())
            with status_lock:
                # Mapeamento dos valores do ADC para ações
                if 3300 <= adc_value <= 3400:  # Música Anterior 
                    door_status["volume_action"] = "Música Anterior"
                    xbmc.executebuiltin("PlayerControl(Previous)")
                    xbmc.log(f"ADC {adc_value}: Música anterior", xbmc.LOGINFO)
                elif 3600 <= adc_value <= 3700:  # Próxima Música
                    door_status["volume_action"] = "Próxima Música"
                    xbmc.executebuiltin("PlayerControl(Next)")
                    xbmc.log(f"ADC {adc_value}: Próxima música", xbmc.LOGINFO)
                elif 4090 <= adc_value <= 4095:  # Mute (inclui margem para estabilidade)
                    door_status["volume_action"] = "Pause"
                    xbmc.executebuiltin("PlayerControl(Play)")
                    xbmc.log(f"ADC {adc_value}:  Música Pausa (Pausa)", xbmc.LOGINFO)
                elif 3880 <= adc_value <= 3930:  # Exemplo: Volume -
                    door_status["volume_action"] = "Volume +"
                    xbmc.log(f"ADC {adc_value}: Volume aumentar", xbmc.LOGINFO)
                    adjust_volume("up")
                    xbmc.log(f"ADC {adc_value}: Volume aumentado", xbmc.LOGINFO)
                elif 4040 <= adc_value <= 4080:  # Exemplo: Volume +
                    door_status["volume_action"] = "Volume -"
                    adjust_volume("down")
                    xbmc.log(f"ADC {adc_value}: Volume diminuído", xbmc.LOGINFO)
                elif 2300 <= adc_value <= 2450:  # Estado neutro
                    door_status["volume_action"] = "Neutro"

            return  # Sai após processar ADC

        # Verifica se é uma mensagem de ADC
        if "ADC Hold:" in raw_data:
            adc_value = int(raw_data.split("ADC Hold: ")[1].strip())
            with status_lock:
                # Mapeamento dos valores do ADC para ações
                if 3300 <= adc_value <= 3400:  # Música Anterior 
                    door_status["volume_action"] = "Música Anterior"
                    xbmc.executebuiltin("PlayerControl(rewind)")
                    xbmc.log(f"ADC {adc_value}: Música anterior", xbmc.LOGINFO)
                elif 3600 <= adc_value <= 3700:  # Próxima Música
                    door_status["volume_action"] = "Próxima Música"
                    xbmc.executebuiltin("PlayerControl(forward)")
                    xbmc.log(f"ADC {adc_value}: Próxima música", xbmc.LOGINFO)
                elif 4090 <= adc_value <= 4095:  # Mute (inclui margem para estabilidade)
                    door_status["volume_action"] = "Pause"
                    xbmc.executebuiltin("PlayerControl(Play)")
                    xbmc.log(f"ADC {adc_value}: Música Pausa (Pausa)", xbmc.LOGINFO)
                elif 3880 <= adc_value <= 3930:  # Exemplo: Volume +
                    door_status["volume_action"] = "Volume +"
                    adjust_volume("up")
                    xbmc.log(f"ADC {adc_value}: Volume aumentado", xbmc.LOGINFO)
                elif 4040 <= adc_value <= 4080:  # Exemplo: Volume -
                    door_status["volume_action"] = "Volume -"
                    adjust_volume("down")
                    xbmc.log(f"ADC {adc_value}: Volume diminuído", xbmc.LOGINFO)
                elif 2300 <= adc_value <= 2450:  # Estado neutro
                    door_status["volume_action"] = "Neutro"

            return  # Sai após processar ADC

        parts = raw_data.split(" : ")

        if len(parts) < 2:
            return  # Ignora mensagens inválidas

        parts = raw_data.split(" : ")
        timestamp = int(parts[0])  # Exemplo: 227760806
        frame_parts = parts[1].split(" ")
        can_id = frame_parts[0]    # Exemplo: 3aa
        can_data = frame_parts[4:]     # Exemplo: ['0', '22', '20', '0', '0', '0', '0', '0']

        # 581 S 0 8 81 0 ff ff ff ff ff ff > CAN ID: Para quando desarma o Alarme

        if can_id == "581":
            with status_lock:
                door_status["alarm"] = "Desarmado"
                xbmc.log("Alarme desarmado (ID 581 detectado)", xbmc.LOGINFO)

        # Verifica mensagem de marcha ré (CAN ID 0x3AA)
        elif can_id == "3aa":
            # Exemplo de dados: 00 22 20 (não engatada) ou 00 22 21 (engatada)
            gear_byte = can_data[2]  # Último byte

            new_status = "Engatada" if gear_byte == "21" else "Não Engatada"

            with status_lock:
                if door_status["reverse_gear"] != new_status:
                    door_status["reverse_gear"] = new_status
                    xbmc.log(f"Marcha ré: {new_status}", xbmc.LOGINFO)

        elif can_id == "3b3":

            if len(parts) < 6:
                return
            
            byte1 = can_data[1]  # Segundo byte
            if byte1 == "48":
                with status_lock:
                    door_status["lighting"] = "Claro"
                    xbmc.log("Ambiente claro detectado (Byte 1 = 0x48)", xbmc.LOGINFO)
            elif byte1 == "88":
                with status_lock:
                    door_status["lighting"] = "Escuro"
                    xbmc.log("Ambiente escuro detectado (Byte 1 = 0x88)", xbmc.LOGINFO)

            last_bytes = ' '.join(can_data[-2:]).upper()

            xbmc.log(f"Debug last_bytes: {str(last_bytes)}", xbmc.LOGINFO)

            # Mapeamento dos status das portas baseado na mensagem CAN
            status_map = {
                "80 0" : { "driver": "Fechada", "passenger": "Fechada", "rear_left": "Fechada", "rear_right": "Fechada", "trunk": "Fechado" },
                "80 30": { "driver": "Fechada", "passenger": "Fechada", "rear_left": "Aberta", "rear_right": "Aberta", "trunk": "Aberto" },
                "80 10": { "driver": "Fechada", "passenger": "Aberta", "rear_left": "Fechada", "rear_right": "Fechada", "trunk": "Fechado" },
                "80 20": { "driver": "Aberta", "passenger": "Fechada", "rear_left": "Fechada", "rear_right": "Fechada", "trunk": "Fechado" },
                "81 20": { "driver": "Aberta", "passenger": "Fechada", "rear_left": "Aberta", "rear_right": "Fechada", "trunk": "Fechado" },
                "82 10": { "driver": "Fechada", "passenger": "Aberta", "rear_left": "Fechada", "rear_right": "Aberta", "trunk": "Fechado" },
                "82 34": { "driver": "Aberta", "passenger": "Aberta", "rear_left": "Fechada", "rear_right": "Aberta", "trunk": "Aberto" },
                "81 34": { "driver": "Aberta", "passenger": "Aberta", "rear_left": "Aberta", "rear_right": "Fechada", "trunk": "Aberto" },
                "80 04": { "driver": "Fechada", "passenger": "Fechada", "rear_left": "Fechada", "rear_right": "Fechada", "trunk": "Aberto" },
                "81 0" : { "driver": "Fechada", "passenger": "Fechada", "rear_left": "Aberta", "rear_right": "Fechada", "trunk": "Fechado" },
                "82 0" : { "driver": "Fechada", "passenger": "Fechada", "rear_left": "Fechada", "rear_right": "Aberta", "trunk": "Fechado" },
                "83 34": { "driver": "Aberta", "passenger": "Aberta", "rear_left": "Aberta", "rear_right": "Aberta", "trunk": "Aberto" },
                "83 14": { "driver": "Fechada", "passenger": "Aberta", "rear_left": "Aberta", "rear_right": "Aberta", "trunk": "Aberto" },
                "83 24": { "driver": "Aberta", "passenger": "Fechada", "rear_left": "Aberta", "rear_right": "Aberta", "trunk": "Aberto" },
                "83 30": { "driver": "Aberta", "passenger": "Aberta", "rear_left": "Aberta", "rear_right": "Aberta", "trunk": "Fechado" },
            }

            with status_lock:
                if last_bytes in status_map:
                    door_status.update(status_map[last_bytes])
                    xbmc.log("Status atualizado", xbmc.LOGINFO)

    except Exception as e:
        xbmc.log(f"Erro ao processar CAN: {str(e)}", xbmc.LOGERROR)

# Adicione esta classe de player
class ReverseVideoPlayer(xbmc.Player):
    def __init__(self):
        super().__init__()
        self.playing = False
        self.ffmpeg_process = None
        self.stream_mode = None
        self.pipe_path = None
        self.play_url = None
        self.ffmpeg_output = None
        self.ffmpeg_input = None
        self.ffmpeg_error_log = None
        self.ffmpeg_start_error = None
        self.previous_item = None  # Armazena o item anterior (arquivo ou playlist)
        self.previous_position = 0  # Armazena a posição de reprodução
        self.previous_media = None
        self.previous_playlist_items = None
        self.previous_playlist_index = 0
        self.previous_playlist_id = None
        self._configure_stream()

    def _get_setting_value(self, key, default=""):
        value = ""
        if addon:
            try:
                value = addon.getSetting(key)
            except Exception:
                value = ""
        if not value:
            try:
                value = xbmc.getInfoLabel(f"Skin.String({key})")
            except Exception:
                value = ""
        return value or default

    def _resolve_ffmpeg_path(self):
        candidates = []

        setting_path = self._get_setting_value("ffmpeg_path", "").strip().strip('"')
        if setting_path:
            which_setting = shutil.which(setting_path)
            if which_setting:
                candidates.append(which_setting)
            candidates.append(setting_path)
            if not os.path.isabs(setting_path):
                candidates.append(os.path.join(addon_path, setting_path))

        env_path = os.environ.get("FFMPEG_PATH", "").strip().strip('"')
        if env_path:
            which_env = shutil.which(env_path)
            if which_env:
                candidates.append(which_env)
            candidates.append(env_path)
            if not os.path.isabs(env_path):
                candidates.append(os.path.join(addon_path, env_path))

        which_path = shutil.which("ffmpeg")
        if which_path:
            candidates.append(which_path)

        if platform.system() == "Windows":
            candidates.extend([
                r"C:\ffmpeg\bin\ffmpeg.exe",
                r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
                r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
            ])
        else:
            candidates.extend([
                "/usr/bin/ffmpeg",
                "/usr/local/bin/ffmpeg",
                "/storage/downloads/ffmpeg",
            ])

        for path in candidates:
            if path and os.path.isfile(path):
                return path

        return None

    def _state_file_path(self):
        return os.path.join(tempfile.gettempdir(), "reverse_playback_state.json")

    def _pid_file_path(self):
        return os.path.join(tempfile.gettempdir(), "reverse_ffmpeg.pid")

    def _persist_playback_state(self):
        state_path = self._state_file_path()
        has_state = bool(self.previous_media or self.previous_playlist_items)
        if not has_state:
            if os.path.exists(state_path):
                try:
                    os.remove(state_path)
                except Exception as e:
                    xbmc.log(f"Falha ao remover estado antigo: {str(e)}", xbmc.LOGERROR)
            return

        state = {
            "previous_media": self.previous_media,
            "previous_position": self.previous_position,
            "previous_playlist_items": self.previous_playlist_items,
            "previous_playlist_index": self.previous_playlist_index,
            "previous_playlist_id": self.previous_playlist_id,
        }
        try:
            with open(state_path, "w") as f:
                json.dump(state, f)
        except Exception as e:
            xbmc.log(f"Falha ao salvar estado de reproducao: {str(e)}", xbmc.LOGERROR)

    def _load_persisted_state(self):
        state_path = self._state_file_path()
        if not os.path.exists(state_path):
            return False
        try:
            with open(state_path, "r") as f:
                state = json.load(f)
            self.previous_media = state.get("previous_media")
            self.previous_position = state.get("previous_position", 0)
            self.previous_playlist_items = state.get("previous_playlist_items")
            self.previous_playlist_index = state.get("previous_playlist_index", 0)
            self.previous_playlist_id = state.get("previous_playlist_id")
            return True
        except Exception as e:
            xbmc.log(f"Falha ao carregar estado de reproducao: {str(e)}", xbmc.LOGERROR)
            return False

    def _clear_persisted_state(self):
        for path in (self._state_file_path(), self._pid_file_path()):
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception as e:
                    xbmc.log(f"Falha ao limpar estado: {str(e)}", xbmc.LOGERROR)

    def _write_ffmpeg_pid(self, pid):
        pid_path = self._pid_file_path()
        try:
            with open(pid_path, "w") as f:
                f.write(str(pid))
        except Exception as e:
            xbmc.log(f"Falha ao salvar PID do FFmpeg: {str(e)}", xbmc.LOGERROR)

    def _terminate_ffmpeg_by_pid(self):
        pid_path = self._pid_file_path()
        if not os.path.exists(pid_path):
            return
        try:
            with open(pid_path, "r") as f:
                raw = f.read().strip()
            pid = int(raw) if raw else None
        except Exception as e:
            xbmc.log(f"Falha ao ler PID do FFmpeg: {str(e)}", xbmc.LOGERROR)
            pid = None

        if pid:
            try:
                if platform.system() == "Windows":
                    subprocess.call(
                        ["taskkill", "/PID", str(pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                else:
                    os.kill(pid, signal.SIGTERM)
            except Exception as e:
                xbmc.log(f"Falha ao terminar FFmpeg por PID: {str(e)}", xbmc.LOGERROR)

        if os.path.exists(pid_path):
            try:
                os.remove(pid_path)
            except Exception as e:
                xbmc.log(f"Falha ao remover PID do FFmpeg: {str(e)}", xbmc.LOGERROR)

    def _pick_udp_port(self):
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]
        except Exception:
            return 12345
        finally:
            if sock:
                sock.close()

    def _configure_stream(self):
        system = platform.system()
        tmp_dir = tempfile.gettempdir()
        self.ffmpeg_error_log = os.path.join(tmp_dir, "ffmpeg_error.log")

        if system == "Windows":
            self.stream_mode = "udp"
            self.udp_host = "127.0.0.1"
            port_setting = self._get_setting_value("udp_port", "")
            try:
                self.udp_port = int(port_setting) if port_setting else 0
            except Exception:
                self.udp_port = 0
            if not self.udp_port:
                self.udp_port = self._pick_udp_port()
            self.play_url = f"udp://{self.udp_host}:{self.udp_port}"
            self.ffmpeg_output = f"udp://{self.udp_host}:{self.udp_port}?pkt_size=1316"

            device = self._get_setting_value("video_device", "USB Video Device")
            self.ffmpeg_input = ["-f", "dshow", "-i", f"video={device}"]
        else:
            self.stream_mode = "fifo"
            self.pipe_path = os.path.join(tmp_dir, "video_pipe")
            self.play_url = "file:///" + self.pipe_path
            self.ffmpeg_output = self.pipe_path

            device = self._get_setting_value("video_device", "/dev/video0")
            self.ffmpeg_input = ["-f", "v4l2", "-input_format", "mjpeg", "-i", device]

    def _jsonrpc(self, payload):
        response = xbmc.executeJSONRPC(json.dumps(payload))
        xbmc.log(f"JSONRPC request: {json.dumps(payload)}", xbmc.LOGDEBUG)
        xbmc.log(f"JSONRPC response: {response}", xbmc.LOGDEBUG)
        try:
            return json.loads(response)
        except Exception:
            xbmc.log(f"JSONRPC inválido: {response}", xbmc.LOGERROR)
            return {}

    def _wait_for_playback(self, timeout=3.0):
        start = time.time()
        while time.time() - start < timeout:
            if self.isPlaying():
                return True
            time.sleep(0.1)
        return False

    def _restore_playlist_via_jsonrpc(self, playlist_id):
        try:
            self._jsonrpc({
                "jsonrpc": "2.0",
                "method": "Playlist.Clear",
                "params": {"playlistid": playlist_id},
                "id": 1
            })
            for item in self.previous_playlist_items:
                self._jsonrpc({
                    "jsonrpc": "2.0",
                    "method": "Playlist.Add",
                    "params": {"playlistid": playlist_id, "item": {"file": item}},
                    "id": 1
                })
            self._jsonrpc({
                "jsonrpc": "2.0",
                "method": "Player.Open",
                "params": {
                    "item": {
                        "playlistid": playlist_id,
                        "position": self.previous_playlist_index
                    }
                },
                "id": 1
            })
            return True
        except Exception as e:
            xbmc.log(f"Falha ao restaurar playlist via JSONRPC: {str(e)}", xbmc.LOGERROR)
            return False

    def _seek_to_position(self, seconds, timeout=6.0):
        if not seconds or seconds <= 0:
            return True

        end = time.time() + timeout
        last_error = None

        while time.time() < end:
            if not self.isPlaying():
                time.sleep(0.1)
                continue

            try:
                self.seekTime(seconds)
                time.sleep(0.2)
                if self.getTime() >= max(0.0, seconds - 1.0):
                    return True
            except Exception as e:
                last_error = str(e)

            try:
                playerid = self._get_active_audio_player()
                if playerid is not None:
                    h = int(seconds // 3600)
                    m = int((seconds % 3600) // 60)
                    s = int(seconds % 60)
                    ms = int((seconds - int(seconds)) * 1000)
                    self._jsonrpc({
                        "jsonrpc": "2.0",
                        "method": "Player.Seek",
                        "params": {
                            "playerid": playerid,
                            "value": {
                                "time": {
                                    "hours": h,
                                    "minutes": m,
                                    "seconds": s,
                                    "milliseconds": ms
                                }
                            }
                        },
                        "id": 1
                    })
                    time.sleep(0.2)
                    if self.getTime() >= max(0.0, seconds - 1.0):
                        return True
            except Exception as e:
                last_error = str(e)

            time.sleep(0.2)

        if last_error:
            xbmc.log(f"Falha ao restaurar posicao: {last_error}", xbmc.LOGERROR)
        return False

    def _get_active_audio_player(self):
        data = self._jsonrpc({"jsonrpc": "2.0", "method": "Player.GetActivePlayers", "id": 1})
        for player in data.get("result", []):
            if player.get("type") == "audio":
                return player.get("playerid")
            if player.get("type") == "video":
                return player.get("playerid")
        return None

    def _get_playlist_snapshot(self):
        playerid = self._get_active_audio_player()

        xbmc.log(f"Player ID: {playerid}", xbmc.LOGINFO)

        if playerid is None:
            return None

        props = self._jsonrpc({
            "jsonrpc": "2.0",
            "method": "Player.GetProperties",
            "params": {"playerid": playerid, "properties": ["playlistid", "position"]},
            "id": 1
        })
        playlistid = props.get("result", {}).get("playlistid")
        position = props.get("result", {}).get("position", 0)

        # if playlistid != xbmc.PLAYLIST_MUSIC:
        #     return None

        items = self._jsonrpc({
            "jsonrpc": "2.0",
            "method": "Playlist.GetItems",
            "params": {"playlistid": playlistid, "properties": ["file"]},
            "id": 1
        })

        file_items = [it.get("file") for it in items.get("result", {}).get("items", []) if it.get("file")]

        xbmc.log(f"File Items: {file_items}", xbmc.LOGINFO)

        if not file_items:
            return None

        return {"items": file_items, "position": position, "playlistid": playlistid}

    def save_current_playback(self):
        """Salva o estado da reprodução atual antes de exibir a câmera."""
        if self.isPlaying():
            self.previous_position = self.getTime()  # Posição atual em segundos
            self.previous_media = None
            self.previous_playlist_items = None
            self.previous_playlist_index = 0
            self.previous_playlist_id = None

            snapshot = self._get_playlist_snapshot()

            xbmc.log(f"Salvando Snapshot: {snapshot}.", xbmc.LOGINFO)

            if snapshot:
                self.previous_playlist_items = snapshot["items"]
                self.previous_playlist_index = snapshot["position"]
                self.previous_playlist_id = snapshot.get("playlistid")
                xbmc.log(f"Salvando playlist com {len(self.previous_playlist_items)} itens na posição {self.previous_playlist_index} e tempo {self.previous_position}", xbmc.LOGINFO)
                xbmc.log("ReverseVideoPlayer: playlist salva para restauração", xbmc.LOGINFO)
            else:
                self.previous_media = self.getPlayingFile()  # Arquivo ou URL atual
                xbmc.log(f"Salvando mídia anterior: {self.previous_media} na posição {self.previous_position}", xbmc.LOGINFO)

            self.pause()  # Pausa a reprodução
        else:
            self.previous_media = None
            self.previous_position = 0
            self.previous_playlist_items = None
            self.previous_playlist_index = 0
            self.previous_playlist_id = None

        self._persist_playback_state()

    def restore_previous_playback(self):
        """Restaura a reprodução anterior, se existia."""
        if not self.previous_playlist_items and not self.previous_media:
            self._load_persisted_state()
        if self.previous_playlist_items:
            playlist_ids = []
            if self.previous_playlist_id is not None:
                playlist_ids = [self.previous_playlist_id]
            else:
                playlist_ids = [xbmc.PLAYLIST_VIDEO, xbmc.PLAYLIST_MUSIC]

            xbmc.log(f"Restaurando playlist com {len(self.previous_playlist_items)} itens na posição {self.previous_playlist_index}", xbmc.LOGINFO)
            started = False

            for playlist_id in playlist_ids:
                playlist = xbmc.PlayList(playlist_id)
                playlist.clear()
                for item in self.previous_playlist_items:
                    playlist.add(item)
                try:
                    self.play(playlist, None, False, self.previous_playlist_index)
                    started = self._wait_for_playback(2.0)
                except Exception as e:
                    xbmc.log(f"Falha ao iniciar playlist com posicao: {str(e)}", xbmc.LOGERROR)

                if not started:
                    if self._restore_playlist_via_jsonrpc(playlist_id):
                        started = self._wait_for_playback(3.0)

                if started:
                    break

            if started:
                if self.previous_position > 0:
                    self._seek_to_position(self.previous_position)
            else:
                xbmc.log("Erro: Kodi não iniciou a reprodução da playlist.", xbmc.LOGERROR)

            xbmc.log("ReverseVideoPlayer: playlist restaurada", xbmc.LOGINFO)
        elif self.previous_media:
            xbmc.log(f"Restaurando mídia: {self.previous_media} na posição {self.previous_position}", xbmc.LOGINFO)
            self.play(self.previous_media)  # Retoma a mídia anterior
            self._seek_to_position(self.previous_position)  # Volta para a posição salva

        self.previous_media = None
        self.previous_playlist_items = None
        self.previous_playlist_index = 0
        self.previous_position = 0
        self.previous_playlist_id = None
        self._clear_persisted_state()

    def start_ffmpeg_stream(self):
        xbmc.log("Iniciando start_ffmpeg_stream", xbmc.LOGINFO)
        self.ffmpeg_start_error = None

        if self.stream_mode == "fifo":
            if self.pipe_path and os.path.exists(self.pipe_path):
                os.remove(self.pipe_path)
                xbmc.log(f"Pipe antigo removido: {self.pipe_path}", xbmc.LOGINFO)
                
            # Cria o pipe se não existir
            if not os.path.exists(self.pipe_path):
                if hasattr(os, "mkfifo"):
                    os.mkfifo(self.pipe_path)
                    xbmc.log(f"Pipe criado em {self.pipe_path}", xbmc.LOGINFO)
                else:
                    xbmc.log("os.mkfifo não suportado neste sistema", xbmc.LOGERROR)
                    return

        if not self.ffmpeg_input or not self.ffmpeg_output:
            xbmc.log("Configuração de stream inválida", xbmc.LOGERROR)
            return

        ffmpeg_exe = self._resolve_ffmpeg_path()
        if not ffmpeg_exe:
            self.ffmpeg_start_error = "ffmpeg_not_found"
            xbmc.log("FFmpeg nao encontrado. Configure 'ffmpeg_path' ou defina FFMPEG_PATH no sistema.", xbmc.LOGERROR)
            return

        # Comando FFmpeg ajustado por sistema
        ffmpeg_cmd = [
            ffmpeg_exe,
            "-y",
        ] + self.ffmpeg_input + [
            "-c:v", "mpeg2video",
            "-b:v", "5000k",
            "-f", "mpegts",
            self.ffmpeg_output
        ]

        # Executa o FFmpeg em um subprocesso
        error_log_path = self.ffmpeg_error_log or os.path.join(tempfile.gettempdir(), "ffmpeg_error.log")
        with open(error_log_path, "w") as error_log:
            try:
                self.ffmpeg_process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=error_log)
                xbmc.log("FFmpeg iniciado para stream em " + self.ffmpeg_output, xbmc.LOGINFO)
                self._write_ffmpeg_pid(self.ffmpeg_process.pid)
            except FileNotFoundError:
                self.ffmpeg_start_error = "ffmpeg_not_found"
                xbmc.log(f"FFmpeg nao encontrado em: {ffmpeg_exe}", xbmc.LOGERROR)
                return
            except Exception as e:
                self.ffmpeg_start_error = "ffmpeg_start_failed"
                xbmc.log(f"Erro ao iniciar FFmpeg: {str(e)}", xbmc.LOGERROR)
                return

        # Verifica se o FFmpeg está rodando
        time.sleep(0.5)
        if self.ffmpeg_process.poll() is None:
            xbmc.log("FFmpeg está ativo", xbmc.LOGINFO)
        else:
            xbmc.log(f"FFmpeg terminou inesperadamente com código {self.ffmpeg_process.returncode}", xbmc.LOGERROR)

        if os.path.exists(error_log_path):
            with open(error_log_path, "r") as error_log:
                stderr_output = error_log.read()
                if stderr_output:
                    xbmc.log(f"FFmpeg stderr: {stderr_output}", xbmc.LOGERROR)

    def play_reverse_video(self):
        if not self.playing:
            if not self.ffmpeg_input or not self.ffmpeg_output:
                xbmc.log("Configuracao de stream invalida", xbmc.LOGERROR)
                return
            if not self._resolve_ffmpeg_path():
                xbmc.log("FFmpeg nao encontrado. Configure 'ffmpeg_path' ou defina FFMPEG_PATH no sistema.", xbmc.LOGERROR)
                return
            # Salva o estado da reprodução atual
            self.save_current_playback()
            # Inicia o FFmpeg em uma thread separada
            threading.Thread(target=self.start_ffmpeg_stream, daemon=True).start()

            # Aguarda o FFmpeg iniciar (ou falhar) antes de tentar reproduzir
            startup_timeout = 4.0
            waited = 0.0
            while waited < startup_timeout:
                if self.ffmpeg_start_error:
                    xbmc.log("FFmpeg falhou ao iniciar o stream", xbmc.LOGERROR)
                    self.restore_previous_playback()
                    return
                if self.ffmpeg_process:
                    if self.ffmpeg_process.poll() is None:
                        break
                    xbmc.log("FFmpeg terminou antes de iniciar o stream", xbmc.LOGERROR)
                    self.restore_previous_playback()
                    return
                time.sleep(0.2)
                waited += 0.2

            if self.ffmpeg_start_error:
                xbmc.log("FFmpeg falhou ao iniciar o stream", xbmc.LOGERROR)
                self.restore_previous_playback()
                return

            if not self.ffmpeg_process or self.ffmpeg_process.poll() is not None:
                xbmc.log("FFmpeg nao iniciou o stream", xbmc.LOGERROR)
                self.restore_previous_playback()
                return

            if self.stream_mode == "fifo":
                if self.pipe_path and os.path.exists(self.pipe_path):
                    has_data = False
                    for _ in range(10):
                        if os.path.getsize(self.pipe_path) > 0:
                            has_data = True
                            break
                        time.sleep(0.2)
                    if not has_data:
                        xbmc.log("Pipe vazio, possível erro no FFmpeg", xbmc.LOGERROR)
                        self.restore_previous_playback()
                        return
                    xbmc.log("Pipe contém dados, iniciando reprodução", xbmc.LOGINFO)
                else:
                    xbmc.log("Pipe não foi criado", xbmc.LOGERROR)
                    self.restore_previous_playback()
                    return
            else:
                xbmc.log(f"Stream ativo em {self.play_url}", xbmc.LOGINFO)

            # Reproduz o stream do pipe
            play_path = self.play_url
            xbmc.log(f"Tentando reproduzir: {play_path}", xbmc.LOGINFO)
            self.play(play_path)
            self.playing = True
            xbmc.executebuiltin("ActivateWindow(fullscreenvideo)")

    def stop_reverse_video(self):
        state_path = self._state_file_path()
        pid_path = self._pid_file_path()
        if not self.playing and not (os.path.exists(state_path) or os.path.exists(pid_path)):
            return

        xbmc.log("Parando play_reverse_video", xbmc.LOGINFO)
        try:
            self.stop()
        except Exception as e:
            xbmc.log(f"Falha ao parar player: {str(e)}", xbmc.LOGERROR)

        if self.ffmpeg_process:
            try:
                self.ffmpeg_process.terminate()
                self.ffmpeg_process.wait()
            except Exception as e:
                xbmc.log(f"Falha ao terminar FFmpeg: {str(e)}", xbmc.LOGERROR)
            self.ffmpeg_process = None
        else:
            self._terminate_ffmpeg_by_pid()

        self.playing = False
        xbmc.executebuiltin("Dialog.Close(all,true)")
        if self.pipe_path and os.path.exists(self.pipe_path):
            os.remove(self.pipe_path)

        self.restore_previous_playback()

def serial_worker():
    """Thread para comunicação serial com otimizações"""
    global serial_conn
    config = get_serial_config()
    ser = None

    while not monitor.abortRequested():
        try:
            if not ser:
                ser = serial.Serial(**config)
                xbmc.log(f"Conexão serial iniciada em {config['port']}", xbmc.LOGINFO)

            if ser.in_waiting > 0:
                raw = ser.readline().decode('utf-8', errors='ignore').strip()
                if raw:
                    parse_can_message(raw)

            monitor.waitForAbort(0.01)

        except serial.SerialException as e:
            xbmc.log(f"Erro serial: {str(e)}", xbmc.LOGERROR)
            if ser:
                ser.close()
                ser = None
            monitor.waitForAbort(5)

        except Exception as e:
            xbmc.log(f"Erro geral: {str(e)}", xbmc.LOGERROR)
            monitor.waitForAbort(1)

    if ser and ser.is_open:
        ser.close()

def enviar_serial(cmd):
    global serial_conn
    if serial_conn and serial_conn.is_open:
        with serial_lock:
            serial_conn.write((cmd + "\n").encode())
            xbmc.log(f"Enviado para serial: {cmd}", xbmc.LOGINFO)
    else:
        xbmc.log("Serial não conectada para envio", xbmc.LOGERROR)

def ui_worker():
    """Atualização otimizada da interface"""
    window = xbmcgui.Window(10000)  # Acessa a Home do Kodi
    last_state = {}
    video_player = ReverseVideoPlayer()

    while not monitor.abortRequested():
        try:
            with status_lock:
                current_state = door_status.copy()
            
            # Controle do vídeo de marcha ré
            if current_state.get("reverse_gear") != last_state.get("reverse_gear"):
                if current_state["reverse_gear"] == "Engatada":
                    video_player.play_reverse_video()
                else:
                    video_player.stop_reverse_video()

            if current_state != last_state:
                # Atualiza as propriedades no Kodi com o status das portas
                window.setProperty("driver_door", door_status["driver"])
                window.setProperty("passenger_door", door_status["passenger"])
                window.setProperty("rear_left_door", door_status["rear_left"])
                window.setProperty("rear_right_door", door_status["rear_right"])
                window.setProperty("trunk", door_status["trunk"])
                window.setProperty("reverse_gear", current_state["reverse_gear"])
                last_state = current_state.copy()
                xbmc.log("UI atualizada", xbmc.LOGINFO)
                # Adicione rótulos descritivos nos logs
                xbmc.log(f"Porta Motorista: {door_status['driver']}", xbmc.LOGINFO)
                xbmc.log(f"Porta Passageiro: {door_status['passenger']}", xbmc.LOGINFO)
                xbmc.log(f"Porta Traseira Esquerda: {door_status['rear_left']}", xbmc.LOGINFO)
                xbmc.log(f"Porta Traseira Direita: {door_status['rear_right']}", xbmc.LOGINFO)
                xbmc.log(f"Porta-malas: {door_status['trunk']}", xbmc.LOGINFO)
                xbmc.log(f"Marcha Ré: {current_state['reverse_gear']}", xbmc.LOGINFO)
            
            monitor.waitForAbort(0.5)  # Espera 0.5s de forma não-bloqueante

        except Exception as e:
            xbmc.log(f"Erro UI: {str(e)}", xbmc.LOGERROR)
            monitor.waitForAbort(1)

if __name__ == "__main__":
    xbmc.log("Serviço iniciado", xbmc.LOGINFO)
    # mostrar_dialogo_desligamento() # Só Desativar para testar o Dialog

    # Inicia threads
    serial_thread = threading.Thread(target=serial_worker, daemon=True)
    ui_thread = threading.Thread(target=ui_worker, daemon=True)

    serial_thread.start()
    ui_thread.start()

    # Mantém o serviço ativo
    while not monitor.abortRequested():
        monitor.waitForAbort(1)

    xbmc.log("CarPc-Carbon Encerrado", xbmc.LOGINFO)
