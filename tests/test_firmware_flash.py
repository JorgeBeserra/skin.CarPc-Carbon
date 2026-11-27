import hashlib
import os
import tempfile
import unittest

from lib import firmware_flash as ff


def make_images(folder):
    sums = {}
    for _, name in ff.IMAGES:
        data = (name * 100).encode()
        with open(os.path.join(folder, name), "wb") as f:
            f.write(data)
        sums[name] = hashlib.sha256(data).hexdigest()
    return sums


OK_OUTPUT = []
for _, name in ff.IMAGES:
    OK_OUTPUT += ["Compressed 100 bytes to 50...", "Writing at 0x00001000... (50 %)",
                  "Writing at 0x00001000... (100 %)", "Wrote 100 bytes", "Hash of data verified."]


class FirmwareFlashTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.sums = make_images(self.dir)

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_and_verify(self):
        text = "\n".join(f"{h}  {n}" for n, h in self.sums.items())
        self.assertEqual(ff.parse_sha256sums(text), self.sums)
        ff.verify_files(self.dir, self.sums)

    def test_verify_detects_corruption(self):
        with open(os.path.join(self.dir, "firmware.bin"), "ab") as f:
            f.write(b"x")
        with self.assertRaises(ff.FlashError):
            ff.verify_files(self.dir, self.sums)

    def test_command_has_no_erase_and_all_offsets(self):
        cmd = ff.build_command("python3", "/t", "/dev/ttyUSB0", 115200, self.dir)
        self.assertNotIn("erase_flash", cmd)
        self.assertIn("write_flash", cmd)
        for offset, _ in ff.IMAGES:
            self.assertIn(offset, cmd)

    def test_retries_then_succeeds(self):
        calls = []

        def runner(cmd, env, cwd, on_line):
            calls.append(cmd[cmd.index("--baud") + 1])
            if len(calls) == 1:
                on_line("Writing at 0x00010000... (30 %)")
                on_line("A fatal error occurred: Packet content transfer stopped")
                return 2
            for line in OK_OUTPUT:
                on_line(line)
            return 0

        progress = []
        ff.flash(self.dir, "/dev/ttyUSB0", "/t", "/l", on_progress=lambda p, t: progress.append(p), runner=runner)
        self.assertEqual(calls, ["115200", "115200"])
        self.assertEqual(max(progress), 100)

    def test_all_attempts_fail(self):
        def runner(cmd, env, cwd, on_line):
            on_line("A fatal error occurred: Failed to connect to ESP32: No serial data received.")
            return 2

        with self.assertRaises(ff.FlashError) as ctx:
            ff.flash(self.dir, "/dev/ttyUSB0", "/t", "/l", runner=runner)
        self.assertIn("Failed to connect", str(ctx.exception))

    def test_previous_attempt_hashes_do_not_count(self):
        n = {"i": 0}

        def runner(cmd, env, cwd, on_line):
            n["i"] += 1
            if n["i"] == 1:
                for line in OK_OUTPUT[:-5]:
                    on_line(line)
                return 2
            on_line("Hash of data verified.")
            return 0  # exit 0 mas so 1 hash: nao pode contar como sucesso

        with self.assertRaises(ff.FlashError):
            ff.flash(self.dir, "/dev/ttyUSB0", "/t", "/l", runner=runner)


if __name__ == "__main__":
    unittest.main()
