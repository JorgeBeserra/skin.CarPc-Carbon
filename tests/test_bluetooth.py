# -*- coding: utf-8 -*-
"""Testes do controle de Bluetooth (lib/carpc_bluetooth.py) com um bluetoothctl
de mentira. Rode com:  python3 -m unittest discover -s tests"""
import json
import os
import stat
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

import carpc_bluetooth as bt  # noqa: E402

PHONE = "AA:BB:CC:DD:EE:01"
SPEAKER = "AA:BB:CC:DD:EE:02"


@unittest.skipIf(os.name == "nt", "o bluetoothctl de teste precisa de um sistema POSIX")
class BluetoothTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_path = os.path.join(self.tmp.name, "state.json")
        self.write_state({
            "adapter": True, "powered": True, "discoverable": False,
            "devices": {
                PHONE: {"name": "Celular do Jorge", "paired": False, "trusted": False, "connected": False},
                SPEAKER: {"name": "Caixa de Som", "paired": True, "trusted": True, "connected": True},
            },
        })
        fake = os.path.join(self.tmp.name, "bluetoothctl")
        with open(fake, "w") as f:
            f.write("#!/bin/sh\nexec %s %s \"$@\"\n" % (sys.executable, os.path.join(HERE, "fake_bluetoothctl.py")))
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
        os.environ["FAKE_BT_STATE"] = self.state_path
        self.old_cmd = bt.BLUETOOTHCTL
        bt.BLUETOOTHCTL = fake

    def tearDown(self):
        bt.BLUETOOTHCTL = self.old_cmd
        self.tmp.cleanup()

    def write_state(self, state):
        with open(self.state_path, "w") as f:
            json.dump(state, f)

    def read_state(self):
        with open(self.state_path) as f:
            return json.load(f)

    def test_adapter_info(self):
        info = bt.adapter_info()
        self.assertEqual(info["name"], "CarPC")
        self.assertTrue(info["powered"])
        self.assertFalse(info["discoverable"])

    def test_adapter_missing(self):
        state = self.read_state()
        state["adapter"] = False
        self.write_state(state)
        self.assertIsNone(bt.adapter_info())

    def test_power_and_visibility(self):
        bt.set_power(False)
        self.assertFalse(bt.adapter_info()["powered"])
        bt.set_power(True)
        bt.set_discoverable(True)
        self.assertTrue(bt.adapter_info()["discoverable"])

    def test_list_devices_sorted(self):
        devices = bt.list_devices()
        self.assertEqual([d["mac"] for d in devices], [SPEAKER, PHONE])
        self.assertTrue(devices[0]["connected"])
        self.assertEqual(devices[1]["name"], "Celular do Jorge")
        self.assertFalse(devices[1]["paired"])

    def test_scan_finds_new_device(self):
        self.assertTrue(bt.scan(1))
        self.assertIn("11:22:33:44:55:66", [d["mac"] for d in bt.list_devices()])

    def test_connect_disconnect_remove(self):
        bt.disconnect(SPEAKER)
        self.assertFalse(bt.device_info(SPEAKER)["connected"])
        bt.connect(SPEAKER)
        self.assertTrue(bt.device_info(SPEAKER)["connected"])
        bt.remove(SPEAKER)
        self.assertIsNone(bt.device_info(SPEAKER))

    def test_connect_failure_reports_reason(self):
        state = self.read_state()
        state["devices"][PHONE]["refuse"] = True
        self.write_state(state)
        with self.assertRaises(bt.BluetoothError) as ctx:
            bt.connect(PHONE)
        self.assertIn("Failed to connect", str(ctx.exception))

    def test_pair_with_session(self):
        session = bt.BluetoothSession()
        try:
            self.assertTrue(session.pair(PHONE, timeout=10))
        finally:
            session.close()
        info = bt.device_info(PHONE)
        self.assertTrue(info["paired"] and info["trusted"] and info["connected"])
        self.assertEqual(self.read_state()["agent"], "--agent=NoInputNoOutput")
        self.assertFalse(session.is_open())

    def test_pair_timeout(self):
        state = self.read_state()
        state["devices"][PHONE]["refuse_pair"] = True
        self.write_state(state)
        session = bt.BluetoothSession()
        try:
            with self.assertRaises(bt.BluetoothError):
                session.pair(PHONE, timeout=2)
        finally:
            session.close()

    def test_rejects_invalid_address(self):
        for bad in ("", "nope", "AA:BB:CC:DD:EE", "AA:BB:CC:DD:EE:01; reboot"):
            with self.assertRaises(bt.BluetoothError):
                bt.normalize_mac(bad)
        self.assertEqual(bt.normalize_mac(" aa:bb:cc:dd:ee:01 "), PHONE)

    def test_parsers_ignore_colors_and_noise(self):
        text = "\x1b[0;94m[bluetooth]\x1b[0m# \r\nDevice aa:bb:cc:dd:ee:01 Meu Fone\nAgent registered\n"
        self.assertEqual(bt.parse_devices(text), [(PHONE, "Meu Fone")])
        props = bt.parse_properties("Device X (public)\n\tPaired: yes\n\tUUID: a (1)\n\tUUID: b (2)\n")
        self.assertEqual(props["Paired"], "yes")
        self.assertEqual(props["UUID"], "a (1)")


if __name__ == "__main__":
    unittest.main()
