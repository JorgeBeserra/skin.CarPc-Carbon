import unittest
from lib.night_mode import NightMode, lighting_from_byte


class NightModeTest(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.mode = NightMode(clock=lambda: self.now)

    def test_confirm_dark_and_clear(self):
        self.assertFalse(self.mode.update("Escuro"))
        self.now = 1.9
        self.assertFalse(self.mode.update("Escuro"))
        self.now = 2.0
        self.assertTrue(self.mode.update("Escuro"))
        self.assertTrue(self.mode.update("Claro"))
        self.now = 4.0
        self.assertFalse(self.mode.update("Claro"))

    def test_short_shadow_does_not_activate(self):
        self.mode.update("Escuro")
        self.now = 1.0
        self.assertFalse(self.mode.update("Claro"))
        self.now = 3.0
        self.assertFalse(self.mode.update("Escuro"))
        self.now = 5.0
        self.assertTrue(self.mode.update("Escuro"))

    def test_unknown_keeps_confirmed_mode_and_resets_pending(self):
        self.assertFalse(self.mode.update(None))
        self.mode.update("Escuro")
        self.now = 2.0
        self.assertTrue(self.mode.update("Escuro"))
        self.mode.update("Claro")
        self.now = 3.0
        self.assertTrue(self.mode.update(None))
        self.now = 6.0
        self.assertTrue(self.mode.update("Claro"))
        self.now = 8.0
        self.assertFalse(self.mode.update("Claro"))


class LightingFromByteTest(unittest.TestCase):
    def test_known_values(self):
        self.assertEqual(lighting_from_byte(0x48), "Claro")
        self.assertEqual(lighting_from_byte(0x88), "Escuro")

    def test_hazard_does_not_hide_ambient_state(self):
        self.assertEqual(lighting_from_byte(0x4A), "Claro")
        self.assertEqual(lighting_from_byte(0x8A), "Escuro")

    def test_unknown(self):
        self.assertIsNone(lighting_from_byte(0x08))
        self.assertIsNone(lighting_from_byte(0x00))

if __name__ == "__main__":
    unittest.main()
