"""Grava o firmware do ESP32 com o esptool que vem no skin (tools/esptool).

Sem dependencias do Kodi, para poder ser testado fora dele.

Cuidados:
- Nunca roda erase_flash: grava tudo em um unico write_flash. Se a gravacao falhar
  no meio, o bootloader da ROM do ESP32 continua la e basta gravar de novo.
- Nao apaga a NVS (configuracoes do ESP32 em 0x9000).
- O esptool confere o hash de cada regiao gravada ("Hash of data verified").
- Tenta de novo em velocidades menores se der erro.
"""
import hashlib
import os
import re
import subprocess
import sys

# Mesmos offsets que .github/scripts/package_firmware.sh do firmware usa
IMAGES = (
    ("0x1000", "bootloader.bin"),
    ("0x8000", "partitions.bin"),
    ("0xe000", "boot_app0.bin"),
    ("0x10000", "firmware.bin"),
)

BAUDS = (115200, 115200, 57600)

PROGRESS = re.compile(r"Writing at 0x([0-9a-fA-F]+)\.*\s*\((\d+)\s*%\)")
FILE_START = re.compile(r"Compressed \d+ bytes to \d+|Wrote \d+ bytes")


class FlashError(Exception):
    pass


def parse_sha256sums(text):
    sums = {}
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and len(parts[0]) == 64:
            sums[parts[1].lstrip("*")] = parts[0].lower()
    return sums


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_files(folder, sums):
    """Confere tamanho e SHA256 de todas as imagens. Levanta FlashError."""
    for _, name in IMAGES:
        path = os.path.join(folder, name)
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            raise FlashError(f"Arquivo ausente ou vazio: {name}")
        expected = sums.get(name)
        if not expected:
            raise FlashError(f"{name} nao esta no SHA256SUMS")
        if sha256_file(path) != expected:
            raise FlashError(f"Checksum errado em {name} (download corrompido)")


def build_command(python, tools_dir, port, baud, folder):
    cmd = [python, "-u", "-m", "esptool",
           "--chip", "esp32", "--port", port, "--baud", str(baud),
           "--before", "default_reset", "--after", "hard_reset",
           "--connect-attempts", "10",
           "write_flash", "-z",
           "--flash_mode", "keep", "--flash_freq", "keep", "--flash_size", "keep"]
    for offset, name in IMAGES:
        cmd += [offset, os.path.join(folder, name)]
    return cmd


def find_python():
    if os.path.exists("/usr/bin/python3"):
        return "/usr/bin/python3"
    if os.path.basename(sys.executable or "").startswith("python"):
        return sys.executable
    return "python3"


def run_esptool(cmd, env, cwd, on_line):
    """Roda o esptool e repassa cada linha (inclusive as de progresso com \\r)."""
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, bufsize=0)
    buf = b""
    while True:
        ch = proc.stdout.read(1)
        if not ch:
            break
        if ch in (b"\n", b"\r"):
            if buf:
                on_line(buf.decode("utf-8", "ignore"))
            buf = b""
        else:
            buf += ch
    if buf:
        on_line(buf.decode("utf-8", "ignore"))
    return proc.wait()


def flash(folder, port, tools_dir, lib_dir, on_progress=None, on_log=None,
          runner=run_esptool, bauds=BAUDS):
    """Grava as imagens de `folder`. on_progress(percent_total, texto).
    Retorna o log completo. Levanta FlashError se todas as tentativas falharem."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in (tools_dir, lib_dir, env.get("PYTHONPATH")) if p)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    python = find_python()
    log = []
    total_images = len(IMAGES)
    sizes = [max(os.path.getsize(os.path.join(folder, n)), 1) for _, n in IMAGES]
    weights = [x / float(sum(sizes)) for x in sizes]

    for attempt, baud in enumerate(bauds, 1):
        state = {"image": 0, "last": -1}
        start = len(log)

        def on_line(line):
            log.append(line)
            if on_log:
                on_log(line)
            m = PROGRESS.search(line)
            if m:
                pct = int(m.group(2))
                if pct < state["last"]:
                    state["image"] += 1  # comecou a proxima imagem
                state["last"] = pct
                image = min(state["image"], total_images - 1)
                overall = int(100 * (sum(weights[:image]) + weights[image] * pct / 100.0))
                if on_progress:
                    on_progress(min(overall, 100), f"Gravando ({baud} baud, tentativa {attempt})... {pct}%")
            elif on_progress and ("Connecting" in line or "Chip is" in line):
                on_progress(0, f"Conectando ao ESP32 (tentativa {attempt})...")

        if on_progress:
            on_progress(0, f"Conectando ao ESP32 (tentativa {attempt}, {baud} baud)...")
        cmd = build_command(python, tools_dir, port, baud, folder)
        try:
            code = runner(cmd, env, tools_dir, on_line)
        except OSError as e:
            log.append(f"Falha ao iniciar o esptool: {e}")
            code = -1
        text = "\n".join(log[start:])
        if code == 0 and text.count("Hash of data verified") >= total_images:
            return text
        log.append(f"--- tentativa {attempt} falhou (codigo {code}) ---")

    raise FlashError(last_error("\n".join(log)))


def last_error(text):
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith(("A fatal error", "A serial exception", "Failed", "Falha")) or "error" in line.lower():
            return line
    return "O esptool nao conseguiu gravar o ESP32"
