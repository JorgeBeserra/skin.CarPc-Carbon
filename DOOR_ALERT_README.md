
# Alerta de Porta para Kodi-Car

## Arquivos Modificados:

1. **service.py** - Adicionado sistema de alertas de porta:
   - Função `show_door_alert()` - Exibe alerta visual quando portas são abertas/fechadas
   - Função `door_alert_timer_worker()` - Contador automático para fechar alerta
   - Função `check_door_alerts()` - Monitora mudanças nas portas
   - Integração com o `ui_worker()` existente

2. **xml/DialogDoorAlert.xml** - Novo diálogo de alerta:
   - Alerta visual com posicionamento estratégico
   - Timer automático de 5 segundos
   - Fechamento manual ou automático
   - Ícone e mensagem personalizáveis

## Como Instalar:

1. Copie os arquivos modificados para o diretório do addon:
   - `DialogDoorAlert.xml` → `skin.CarPc-Carbon/xml/`
   - `service.py` → `skin.CarPc-Carbon/`

2. Reinicie o Kodi

## Funcionalidade:

- O sistema monitora todas as portas (motorista, passageiro, traseiras, porta-malas)
- Exibe alerta visual quando uma porta é aberta
- Alerta desaparece automaticamente após 5 segundos
- Possibilidade de fechar manualmente com botão "Fechar"
- Logs detalhados no sistema para depuração

## Personalização:

- Modifique o tempo do contador alterando `door_alert_timer = 5` na função `show_door_alert()`
- Altere a posição do diálogo modificando as coordenadas no XML
- Mude o ícone alterando o nome do arquivo na tag `<texture>`

## Observações:

- O alerta só é exibido quando uma porta mudar de "Fechada" para "Aberta"
- Não mostra alertas consecutivos para evitar spam
- O sistema é compatível com o monitoramento CAN existente
