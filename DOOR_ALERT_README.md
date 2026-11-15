
# Alerta de Porta para Kodi-Car

## Arquivos Modificados:

1. **service.py** - Adicionado sistema de alertas de porta:
   - Função `show_door_alert()` - Exibe alerta visual quando portas são abertas/fechadas
   - Função `door_alert_timer_worker()` - Contador automático para fechar alerta
   - Função `check_door_alerts()` - Monitora mudanças nas portas
   - Integração com o `ui_worker()` existente

2. **xml/custom_DoorAlert_1152.xml** - Diálogo de alerta (janela 1152):
   - Alerta visual com posicionamento estratégico
   - Timer automático de 5 segundos
   - Fechamento manual ou automático
   - Ícone e mensagem personalizáveis

## Como Instalar:

1. Copie os arquivos modificados para o diretório do addon:
   - `custom_DoorAlert_1152.xml` → `skin.CarPc-Carbon/xml/`
   - `service.py` → `skin.CarPc-Carbon/`

2. Reinicie o Kodi

## Funcionalidade:

- O sistema monitora todas as portas (motorista, passageiro, traseiras, porta-malas)
- Exibe alerta visual quando uma porta é aberta
- Alerta desaparece automaticamente após 5 segundos
- Possibilidade de fechar manualmente com botão "Fechar"
- Logs detalhados no sistema para depuração

## Personalização:

- Modifique o tempo do contador alterando `DOOR_ALERT_SECONDS = 5` no `service.py`
- Altere a posição do diálogo modificando as coordenadas no XML
- Mude o ícone alterando o nome do arquivo na tag `<texture>`

## Observações:

- O alerta é exibido quando uma porta (ou o porta-malas) abre ou fecha
- Um alerta novo substitui o anterior e reinicia o contador
- O sistema é compatível com o monitoramento CAN existente
