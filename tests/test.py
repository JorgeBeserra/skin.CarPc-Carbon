import unittest

class CANProcessor:
    """Classe que interpreta mensagens recebidas da rede CAN."""
    
    def parse_can_message(self, message):
        """Processa a string recebida e retorna um dicionário com os dados"""
        try:
            parts = message.split(" - ")
            timestamp = int(parts[0])  # Exemplo: 227760806
            frame_parts = parts[1].split(" ")
            can_id = frame_parts[0]    # Exemplo: 3aa
            data = frame_parts[4:]     # Exemplo: ['0', '8', '0', '22', '20', '0', '0', '0', '0', '0']

            return {
                "timestamp": timestamp,
                "can_id": can_id,
                "data": data 
            }
        except Exception as e:
            return {"error": str(e)}

# Testes unitários
class TestCANProcessor(unittest.TestCase):
    """Classe de teste para CANProcessor."""
    def setUp(self):
        """Configura um objeto da classe CANProcessor antes dos testes"""
        self.processor = CANProcessor()

    def test_parse_valid_message(self):
        """Testa se a mensagem CAN é corretamente interpretada"""
        message = "227760806 - 3aa S 0 8 0 22 20 0 0 0 0 0"
        result = self.processor.parse_can_message(message)

        self.assertEqual(result["timestamp"], 227760806)
        self.assertEqual(result["can_id"], "3aa")
        self.assertEqual(result["data"], ['0', '22', '20', '0', '0', '0', '0', '0'])
        self.assertEqual(result["data"][2], '20')

    def test_parse_another_message(self):
        """Testa outra mensagem para verificar a consistência"""
        message = "226379428 - 3aa S 0 8 0 20 20 0 0 0 0 0"
        result = self.processor.parse_can_message(message)

        self.assertEqual(result["timestamp"], 226379428)
        self.assertEqual(result["can_id"], "3aa")
        self.assertEqual(result["data"], ['0', '20', '20', '0', '0', '0', '0', '0'])

    def test_invalid_message(self):
        """Testa o comportamento ao receber uma mensagem inválida"""
        message = "invalid message format"
        result = self.processor.parse_can_message(message)

        self.assertIn("error", result)

# Executa os testes
if __name__ == '__main__':
    unittest.main()
