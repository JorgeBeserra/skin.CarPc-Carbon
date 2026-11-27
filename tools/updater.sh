#!/bin/bash

# Listar portas disponíveis
PORTS=$(ls /dev/ttyUSB* 2>/dev/null)

# Verifica se encontrou alguma porta
if [ -z "$PORTS" ]; then
    echo "Nenhuma porta serial encontrada! Conecte o ESP32 e tente novamente."
    exit 1
fi

# Configurações do ESP32
CHIP="esp32"
BAUDRATE="115200"
FLASH_MODE="keep"
FLASH_FREQ="keep"
FLASH_SIZE="keep"

# Arquivos de firmware
BOOT_APP="boot_app0.bin"
BOOTLOADER="bootloader_qio_80m.bin"
FIRMWARE="firmware.bin"
PARTITIONS="partitions.bin"

# Loop pelas portas USB disponíveis
for FILE in $PORTS
do
    echo "Gravando firmware no ESP32 na porta $FILE..."

    # Sem erase_flash: grava tudo de uma vez (se falhar, o ESP32 continua
    # podendo ser gravado) e preserva as configuracoes (NVS).
    # Prefira o botao "Update ESP32 firmware" do skin, que libera a porta serial.
    # Gravar o firmware
    ./esptool.py --chip $CHIP --port $FILE --baud $BAUDRATE \
        --before default_reset --after hard_reset write_flash -z \
        --flash_mode $FLASH_MODE --flash_freq $FLASH_FREQ --flash_size $FLASH_SIZE \
        0xe000 $BOOT_APP \
        0x1000 $BOOTLOADER \
        0x10000 $FIRMWARE \
        0x8000 $PARTITIONS

    echo "Gravação concluída para a porta $FILE!"
done

sleep 1
exit 0
