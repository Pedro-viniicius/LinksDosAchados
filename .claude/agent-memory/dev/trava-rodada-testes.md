---
name: trava-rodada-testes
description: Trava por loja (servidor.travar_rodada, saída 4) e testes que contam arquivos na pasta do banco; como provar a ordem sem rede; mutantes equivalentes
metadata:
  type: project
---

Vistas na etapa 3 de endurecer-engenharia-e-operacao (2026-11-09):

- **O `.lock` aparece ao lado do `ACHADINHOS_DB`** em toda rodada dos três CLIs (menos `coletar_shopee conferir`). Teste que confere `os.listdir(pasta) == []` depois de rodar um CLI quebra: três casos no `test_atualizar_precos_ml.py` e no `_ml_qa.py` passaram a esperar `['achadinhos.db.rodada-ml.lock']`. Teste novo que conta arquivos da pasta tem de contar a trava.
- Provar "a trava vem antes de tudo" sem rede: no processo, troque por `mock` `S.criar_banco`, os `marcar`, `CS.proteger_processo`/`credenciais`, `M.proteger_processo`/`sessao_do_ambiente`/`ler_vinculos` e `CS.ler_arquivo`, segure a trava com outro `os.open`+`flock` e confira que nenhum foi chamado. Rode também o caso de controle, sem a trava segura, em que os mesmos falsos são chamados.
- Argumentos que passam da trava e param antes da rede: `atualizar_precos shopee` sem credencial (2), `ml` sem tokens (2), `coletar_shopee importar /nao/existe` (2) e `coletar_amazon buscas --cat <aba inexistente>` (2, depois do `criar_banco` na pasta temporária). O `atualizar_precos amazon --cat` valida a aba no argparse, por isso não serve.
- Dono para o teste de `kill -9`: `python3 -c` que troca `A._rodar_ml` por um `sleep` e chama `A.main(['ml'])` (o main de verdade segura a trava).
- O `coletar_amazon.main` não trata exceção: com o `criar_banco` falso levantando, o teste precisa capturar a exceção.
- Mutantes equivalentes: tirar o `O_NONBLOCK` (no Linux, um FIFO com `O_RDWR` não prende o open) e tirar o `LOCK_UN` do fim (o `os.close` solta a trava). Para o mutante "sem conferir o inode" morrer, o teste troca o `fcntl.flock` por um falso que apaga e recria o arquivo antes do primeiro `LOCK_EX`. O runner de mutantes copia `servidor.py`, os três CLIs, `disparo.py`, `genero.py`, `ml_api.py`, `api_ofertas.py`, `buscas.json` e o teste.

**How to apply:** ao mexer nos `main` dos CLIs ou em testes que rodam esses comandos. Relacionado: [[atualizar-precos-testes]], [[garimpo-banco-testes]], [[ml-api-testes]].
