import re
import xbmc
from collections import defaultdict
from threading import Lock

class CANParser:
    def __init__(self, addon, shared_state):
        self.addon = addon
        self.shared_state = shared_state
        self.lock = Lock()
        self.message_counters = defaultdict(int)
        self.debug_mode = addon.getSettingBool("debug_mode")
        
        # Configurações de mapeamento
        self.can_mappings = {
            '0x3b3': self._handle_door_status,
            '0x3aa': self._handle_reverse_gear,
            '0x123': self._handle_light_sensor  # Exemplo para sensor adicional
        }

        # Compila regex para eficiência
        self.can_regex = re.compile(
            r'(?P<timestamp>\d+\.\d+)\s+' +
            r'(?P<interface>\w+)\s+' +
            r'(?P<id>0x[0-9a-fA-F]+)\s+' +
            r'(?P<direction>[RxTx]+)\s+' +
            r'(?P<format>\[\d+\])\s+' +
            r'(?P<data>(?:[0-9A-F]{2}\s?)+)'
        )

    def parse(self, raw_message):
        """Processa uma mensagem CAN bruta"""
        try:
            match = self.can_regex.match(raw_message.strip())
            if not match:
                if self.debug_mode:
                    xbmc.log(f"Formato CAN inválido: {raw_message}", xbmc.LOGWARNING)
                return

            can_id = match.group('id').lower()
            data_bytes = match.group('data').split()

            # Chama o handler específico para o CAN ID
            handler = self.can_mappings.get(can_id, self._handle_unknown)
            handler(can_id, data_bytes)

            self.message_counters[can_id] += 1

        except Exception as e:
            xbmc.log(f"Erro parsing CAN: {str(e)}", xbmc.LOGERROR)

    def _handle_door_status(self, can_id, data):
        """Processa mensagens de status das portas (ID 0x3b3)"""
        with self.lock:
            # Últimos 2 bytes determinam o status
            status_byte = ''.join(data[-2:])
            
            # Mapeamento atualizado com XOR para detecção de mudanças
            new_status = {
                "driver":   'Aberta' if int(status_byte[0], 16) & 0x20 else 'Fechada',
                "passenger": 'Aberta' if int(status_byte[0], 16) & 0x10 else 'Fechada',
                "rear_left": 'Aberta' if int(status_byte[1], 16) & 0x80 else 'Fechada',
                "rear_right": 'Aberta' if int(status_byte[1], 16) & 0x40 else 'Fechada',
                "trunk":     'Aberto' if int(status_byte[1], 16) & 0x20 else 'Fechado'
            }

            # Atualiza apenas se houver mudanças
            if new_status != self.shared_state.get('doors'):
                self.shared_state['doors'] = new_status
                if self.debug_mode:
                    xbmc.log(f"Status portas atualizado: {new_status}", xbmc.LOGINFO)

    def _handle_reverse_gear(self, can_id, data):
        """Processa marcha ré (ID 0x3aa)"""
        with self.lock:
            gear_byte = data[-1]
            new_state = "Engatada" if gear_byte == '21' else "Não Engatada"
            
            if self.shared_state.get('reverse_gear') != new_state:
                self.shared_state['reverse_gear'] = new_state
                xbmc.log(f"Marcha ré: {new_state}", xbmc.LOGINFO)

    def _handle_light_sensor(self, can_id, data):
        """Processa sensor de luminosidade (ID 0x123 - exemplo)"""
        with self.lock:
            try:
                lux_value = int(''.join(data[2:4]), 16)
                self.shared_state['light_sensor'] = lux_value
                
                if self.debug_mode:
                    xbmc.log(f"Luminosidade: {lux_value} lux", xbmc.LOGINFO)
                    
            except ValueError:
                xbmc.log("Dados de luminosidade inválidos", xbmc.LOGWARNING)

    def _handle_unknown(self, can_id, data):
        """Handler para mensagens não mapeadas"""
        if self.debug_mode:
            xbmc.log(f"Mensagem não tratada - ID: {can_id} | Dados: {' '.join(data)}", xbmc.LOGDEBUG)

    def get_stats(self):
        """Retorna estatísticas de parsing"""
        with self.lock:
            return dict(self.message_counters)