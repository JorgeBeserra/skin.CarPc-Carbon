# Modo noturno automatico (2.1.1)

O service.py interpreta o segundo byte do CAN 0x3B3: 0x48 = claro,
0x88 = escuro. O estado precisa permanecer por dois segundos antes da troca.
A confirmacao usa relogio monotonico na thread de interface e nao adiciona
esperas a thread serial. Sem mensagem valida no inicio, permanece diurno;
se a comunicacao parar depois, mantem o ultimo modo confirmado.

A propriedade Home `carpc_night_mode` controla um dialogo modeless sem botoes,
com preto a 70% sobre a imagem. Toques e comandos continuam indo para a janela
inferior. Nao altera o backlight HDMI nem as configuracoes do protetor de tela;
o protetor existente ainda pode escurecer mais durante inatividade.
A camada tambem cobre videos e camera de re: conferir legibilidade no carro.

## Instalar e verificar

Atualizar a skin completa para 2.1.1 e reiniciar o Kodi. Atualizar apenas
service.py nao basta: lib/night_mode.py e xml/custom_NightMode_1153.xml sao novos.
Com o carro parado, conferir nos logs os estados do sensor e `Modo noturno`.
Cobrir o sensor por mais de dois segundos deve escurecer; tocar na tela,
alterar o volume e trocar de janela devem manter o efeito. Iluminar por mais
de dois segundos deve voltar ao normal. Uma sombra com menos de dois segundos
nao deve alternar. Conferir camera de re e dialogos com o efeito ativo.

O percentual inicial nao foi calibrado no painel do carro. Ajustar o alpha
B3 em `colordiffuse` no XML para mudar a intensidade (00 transparente,
FF preto total). Nao ha controle fisico de brilho nesta implementacao.

## Reverter

Reinstalar a versao anterior da skin e reiniciar o Kodi, ou reverter o commit.

## Validacao local

`python -m unittest discover -s tests -p 'test_night_mode.py'`

Testes cobrem as transicoes e sombras rapidas; renderizacao e CAN reais
precisam do teste no Raspberry.
