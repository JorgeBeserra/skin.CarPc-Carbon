import xbmc
import xbmcgui
from xbmc import Monitor, Player

class ReverseGearManager:
    def __init__(self, addon):
        self.monitor = Monitor()
        self.addon = addon
        self.player = None
        self.last_state = None
        self.retry_count = 0
        self.max_retries = 3
        self.load_config()
        
        # Configuração inicial
        self.video_window = xbmcgui.Window(xbmcgui.getCurrentWindowId())
        self.default_coords = {
            'x': 0,
            'y': 0,
            'width': 1920,
            'height': 1080
        }

    def load_config(self):
        """Carrega configurações do addon"""
        self.video_source = self.addon.getSetting("video_source") or self.get_default_video_source()
        self.activation_delay = int(self.addon.getSetting("activation_delay") or 0)
        self.enable_overlay = self.addon.getSettingBool("enable_overlay")
        self.debug_mode = self.addon.getSettingBool("debug_mode")

    def get_default_video_source(self):
        """Determina fonte de vídeo padrão baseada no SO"""
        system = platform.system()
        return "v4l2:///dev/video0" if system == "Linux" else "dshow://video=USB Video Device"

    def handle_gear_state(self, new_state):
        """Gerencia transições de estado da marcha ré"""
        if new_state == self.last_state:
            return

        if new_state == "Engatada":
            self.start_video_feed()
        else:
            self.stop_video_feed()

        self.last_state = new_state
        self.log(f"Estado da marcha ré alterado para: {new_state}")

    def start_video_feed(self):
        """Inicia a transmissão de vídeo com tratamento de erros"""
        if self.player and self.player.isPlaying():
            return

        try:
            if self.activation_delay > 0:
                xbmc.sleep(self.activation_delay * 1000)

            self.player = Player()
            self.player.play(self.video_source)
            
            if self.enable_overlay:
                self.setup_video_overlay()
            
            self.retry_count = 0
            self.log("Transmissão de vídeo iniciada com sucesso")

        except Exception as e:
            self.log(f"Erro ao iniciar vídeo: {str(e)}", xbmc.LOGERROR)
            self.handle_playback_error()

    def stop_video_feed(self):
        """Para a transmissão de vídeo de forma segura"""
        if self.player and self.player.isPlaying():
            try:
                self.player.stop()
                if self.enable_overlay:
                    self.restore_ui_state()
                self.log("Transmissão de vídeo encerrada")
            except Exception as e:
                self.log(f"Erro ao parar vídeo: {str(e)}", xbmc.LOGERROR)

    def handle_playback_error(self):
        """Lida com erros de reprodução e tentativas"""
        if self.retry_count < self.max_retries:
            self.retry_count += 1
            xbmc.sleep(2000)
            self.start_video_feed()
        else:
            self.log("Número máximo de tentativas atingido", xbmc.LOGERROR)
            self.retry_count = 0

    def setup_video_overlay(self):
        """Configura a interface do vídeo sobreposta"""
        self.backup_ui_state()
        self.video_window.setProperty("ReverseGearActive", "true")
        xbmc.executebuiltin("SetGUISetting(interface;fullscreen;true)")
        self.video_window.setCoordinateResolution(*self.default_coords.values())

    def backup_ui_state(self):
        """Salva o estado atual da interface"""
        self.saved_ui_state = {
            'fullscreen': xbmc.getCondVisibility("Window.IsFullscreen"),
            'active_window': xbmcgui.getCurrentWindowId()
        }

    def restore_ui_state(self):
        """Restaura a interface para o estado anterior"""
        self.video_window.clearProperty("ReverseGearActive")
        if not self.saved_ui_state['fullscreen']:
            xbmc.executebuiltin("SetGUISetting(interface;fullscreen;false)")
        xbmc.executebuiltin(f"ActivateWindow({self.saved_ui_state['active_window']})")

    def log(self, message, level=xbmc.LOGINFO):
        """Registro de logs com controle de debug"""
        if self.debug_mode or level != xbmc.LOGINFO:
            xbmc.log(f"[Reverse Gear] {message}", level)

    def cleanup(self):
        """Liberação de recursos"""
        self.stop_video_feed()
        self.restore_ui_state()
        del self.player
        self.log("Recursos liberados")