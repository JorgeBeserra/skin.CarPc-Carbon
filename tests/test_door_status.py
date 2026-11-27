import unittest
from lib.door_status import DoorDebouncer, decode_doors


def frame(b6, b7):
    return [0x10, 0x40, 0, 0, 0xE6, 0x05, b6, b7]


def opened(b6, b7):
    d = decode_doors(frame(b6, b7))
    return {k for k, v in d.items() if v.startswith("Abert")}


class DecodeDoorsTest(unittest.TestCase):
    # Valores anotados no carro (Ford Ka 2019)
    def test_notes(self):
        self.assertEqual(opened(0x80, 0x00), set())
        self.assertEqual(opened(0x83, 0x34), {"driver", "passenger", "rear_left", "rear_right", "trunk"})
        self.assertEqual(opened(0x83, 0x30), {"driver", "passenger", "rear_left", "rear_right"})
        self.assertEqual(opened(0x83, 0x14), {"passenger", "rear_left", "rear_right", "trunk"})
        self.assertEqual(opened(0x83, 0x24), {"driver", "rear_left", "rear_right", "trunk"})
        self.assertEqual(opened(0x82, 0x34), {"driver", "passenger", "rear_right", "trunk"})
        self.assertEqual(opened(0x81, 0x34), {"driver", "passenger", "rear_left", "trunk"})
        self.assertEqual(opened(0x80, 0x30), {"driver", "passenger"})
        self.assertEqual(opened(0x83, 0x00), {"rear_left", "rear_right"})
        self.assertEqual(opened(0x80, 0x10), {"passenger"})
        self.assertEqual(opened(0x81, 0x00), {"rear_left"})
        self.assertEqual(opened(0x82, 0x00), {"rear_right"})
        self.assertEqual(opened(0x80, 0x04), {"trunk"})
        self.assertEqual(opened(0x82, 0x10), {"passenger", "rear_right"})
        self.assertEqual(opened(0x81, 0x20), {"driver", "rear_left"})

    def test_words(self):
        d = decode_doors(frame(0x80, 0x04))
        self.assertEqual(d["trunk"], "Aberto")
        self.assertEqual(d["driver"], "Fechada")

    def test_short_frame(self):
        self.assertIsNone(decode_doors([0x10, 0x40]))


class DoorDebouncerTest(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.deb = DoorDebouncer(delay=2.0, clock=lambda: self.now)

    def test_blip_ignored(self):
        self.deb.update({"rear_left": "Aberta"})
        for t, v in [(1, "Fechada"), (2, "Aberta"), (3, "Aberta"), (4, "Fechada"), (5, "Aberta")]:
            self.now = t
            self.assertEqual(self.deb.update({"rear_left": v})["rear_left"], "Aberta")

    def test_real_change_after_delay(self):
        self.deb.update({"driver": "Fechada"})
        self.now = 1
        self.assertEqual(self.deb.update({"driver": "Aberta"})["driver"], "Fechada")
        self.now = 2.5
        self.assertEqual(self.deb.update({"driver": "Aberta"})["driver"], "Fechada")
        self.now = 3.0
        self.assertEqual(self.deb.update({"driver": "Aberta"})["driver"], "Aberta")


if __name__ == "__main__":
    unittest.main()
