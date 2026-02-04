import sys
import os
import platform
import xbmc
import xbmcaddon
import xbmcgui
import subprocess
import time
import threading
from xbmc import Monitor, Player

from lib.ReverseGearManager import ReverseGearManager
from lib.can_parser import CANParser

# Adiciona o diretório do addon e a pasta lib ao sys.path
addon_path = xbmcaddon.Addon().getAddonInfo('path')
lib_path = os.path.join(addon_path, 'lib')

if lib_path not in sys.path:
    sys.path.append(lib_path)

try:
    import serial
    xbmc.log("PySerial importado com sucesso!", xbmc.LOGINFO)
except ImportError:
    xbmc.log("Falha ao importar PySerial", xbmc.LOGERROR)
    sys.exit()

import time
import threading


# Configuração do Addon
addon = xbmcaddon.Addon()
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

    return {
        'port': addon.getSetting("serial_port") or default_port,
        'baudrate': int(addon.getSetting("baud_rate") or 115200),
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

        if raw_data == "ShutdownForInactivity":
            xbmc.log("Kodi: Desligando o sistema após inatividade", xbmc.LOGINFO)
            mostrar_dialogo_desligamento()

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
                    door_status["volume_action"] = "Mute"
                    xbmc.executebuiltin("Mute")
                    xbmc.log(f"ADC {adc_value}: Volume silenciado (Mute)", xbmc.LOGINFO)
                elif 3880 <= adc_value <= 3900:  # Exemplo: Volume -
                    door_status["volume_action"] = "Volume +"
                    xbmc.log(f"ADC {adc_value}: Volume aumentar", xbmc.LOGINFO)
                    adjust_volume("up")
                    xbmc.log(f"ADC {adc_value}: Volume aumentado", xbmc.LOGINFO)
                elif 4040 <= adc_value <= 4060:  # Exemplo: Volume +
                    door_status["volume_action"] = "Volume -"
                    xbmc.log(f"ADC {adc_value}: Volume baixar", xbmc.LOGINFO)
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
                    door_status["volume_action"] = "Mute"
                    xbmc.executebuiltin("Mute")
                    xbmc.log(f"ADC {adc_value}: Volume silenciado (Mute)", xbmc.LOGINFO)
                elif 3880 <= adc_value <= 3900:  # Exemplo: Volume +
                    door_status["volume_action"] = "Volume +"
                    adjust_volume("up")
                    xbmc.log(f"ADC {adc_value}: Volume aumentado", xbmc.LOGINFO)
                elif 4040 <= adc_value <= 4060:  # Exemplo: Volume -
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
        self.pipe_path = "/tmp/video_pipe"
        self.previous_item = None  # Armazena o item anterior (arquivo ou playlist)
        self.previous_position = 0  # Armazena a posição de reprodução

    def save_current_playback(self):
        """Salva o estado da reprodução atual antes de exibir a câmera."""
        if self.isPlaying():
            self.previous_media = self.getPlayingFile()  # Arquivo ou URL atual
            self.previous_position = self.getTime()      # Posição atual em segundos
            self.pause()                                 # Pausa a reprodução
            xbmc.log(f"Salvando mídia anterior: {self.previous_media} na posição {self.previous_position}", xbmc.LOGINFO)
        else:
            self.previous_media = None
            self.previous_position = 0

    def restore_previous_playback(self):
        """Restaura a reprodução anterior, se existia."""
        if self.previous_media:
            xbmc.log(f"Restaurando mídia: {self.previous_media} na posição {self.previous_position}", xbmc.LOGINFO)
            self.play(self.previous_media)  # Retoma a mídia anterior
            self.seekTime(self.previous_position)  # Volta para a posição salva
            self.previous_media = None  # Limpa o estado após restaurar

    def start_ffmpeg_stream(self):
        xbmc.log("Iniciando start_ffmpeg_stream", xbmc.LOGINFO)
        # Cria o pipe se não existir
        if not os.path.exists(self.pipe_path):
            os.mkfifo(self.pipe_path)
            xbmc.log(f"Pipe criado em {self.pipe_path}", xbmc.LOGINFO)

        # Comando FFmpeg ajustado para o LibreELEC
        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-f", "v4l2",
            "-input_format", "mjpeg",
            "-i", "/dev/video0",
            "-c:v", "mpeg2video",
            "-b:v", "5000k",
            "-f", "mpegts",
            self.pipe_path
        ]

        # Executa o FFmpeg em um subprocesso
        with open("/tmp/ffmpeg_error.log", "w") as error_log:
            self.ffmpeg_process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=error_log)
            xbmc.log("FFmpeg iniciado para stream em " + self.pipe_path, xbmc.LOGINFO)

        # Verifica se o FFmpeg está rodando
        time.sleep(5)
        if self.ffmpeg_process.poll() is None:
            xbmc.log("FFmpeg está ativo", xbmc.LOGINFO)
        else:
            xbmc.log(f"FFmpeg terminou inesperadamente com código {self.ffmpeg_process.returncode}", xbmc.LOGERROR)

        if os.path.exists("/tmp/ffmpeg_error.log"):
            with open("/tmp/ffmpeg_error.log", "r") as error_log:
                stderr_output = error_log.read()
                if stderr_output:
                    xbmc.log(f"FFmpeg stderr: {stderr_output}", xbmc.LOGERROR)

    def play_reverse_video(self):
        if not self.playing:
            # Salva o estado da reprodução atual
            self.save_current_playback()
            # Inicia o FFmpeg em uma thread separada
            threading.Thread(target=self.start_ffmpeg_stream, daemon=True).start()
            # Aguarda um momento para garantir que o FFmpeg comece a escrever no pipe
            time.sleep(5)
            if os.path.exists(self.pipe_path):
                pipe_size = os.path.getsize(self.pipe_path) if os.path.getsize(self.pipe_path) > 0 else 0
                xbmc.log(f"Pipe existe, tamanho: {pipe_size} bytes", xbmc.LOGINFO)
                if pipe_size > 0:
                    xbmc.log("Pipe contém dados, iniciando reprodução", xbmc.LOGINFO)
                else:
                    xbmc.log("Pipe vazio, possível erro no FFmpeg", xbmc.LOGERROR)
            else:
                xbmc.log("Pipe não foi criado", xbmc.LOGERROR)

            # Reproduz o stream do pipe
            play_path = "file:///" + self.pipe_path
            xbmc.log(f"Tentando reproduzir: {play_path}", xbmc.LOGINFO)
            self.play(play_path)
            self.playing = True
            xbmc.executebuiltin("ActivateWindow(fullscreenvideo)")

    def stop_reverse_video(self):
        if self.playing:
            xbmc.log("Parando play_reverse_video", xbmc.LOGINFO)
            self.stop()
            if self.ffmpeg_process:
                self.ffmpeg_process.terminate()
                self.ffmpeg_process.wait()
                self.ffmpeg_process = None
            self.playing = False
            xbmc.executebuiltin("Dialog.Close(all,true)")
            if os.path.exists(self.pipe_path):
                os.remove(self.pipe_path)

            self.restore_previous_playback()

def serial_worker():
    """Thread para comunicação serial com otimizações"""
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
