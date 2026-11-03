---
name: testes-abas-migracao
description: Como provar a reorganização das abas (migrar_categorias.py, buscas.json, coletar_amazon.py progresso, testes/abas.test.html) sem tocar o banco real
metadata:
  type: project
---

Verificado em 2026-11-03 (Parte A do plano eletronicos-e-coleta-ml, rodada 1).

**Comandos**
- `python3 testes/test_migrar_categorias.py -v` (dev, 16) e `test_migrar_categorias_qa.py` (QA, 9: SQL injection, busca NULL/vazia, escritor concorrente, backup com item só no WAL, item novo depois da migração).
- `python3 testes/test_coletar_amazon.py -v` (dev, 12) e `test_coletar_amazon_qa.py` (QA, 13: buscas.json termo a termo, progresso antigo cobre 98 termos e sobram 28, captcha no meio, ACHADINHOS_FEITOS via subprocesso `-I`). Importa `test_coletar_amazon as T` (isso cria o TMP e define o ambiente), e precisa de `tearDownModule` próprio que chama `T.tearDownModule()`.
- Front: `abas.test.html` exige banco JÁ migrado (falha de propósito num banco não migrado). Fluxo: cópia com `sqlite3.backup` -> `ACHADINHOS_DB=<cópia> python3 migrar_categorias.py` (sem `--sim`: o caminho não é o real) -> `ACHADINHOS_DB=<cópia> ACHADINHOS_PORTA=8766 python3 servidor.py &` -> `PORTA=8766 node testes/rodar.mjs abas`. ~8 s. O PATCH do "Mover para" é interceptado na página (Response falso), nunca chega ao banco.

**Mutantes do front** (espelho no scratchpad com servidor e cópia do banco em porta livre, roda `rodar.mjs` por mutante): 13 mutados, 11 mortos. Sobreviventes são equivalentes: "aba não zera #fBusca" (o render já reconstrói o select e o termo não existe na outra aba) e "page>pages vira page=1" (clique em aba/filtro já zera a página).

**Armadilhas**
- `--dry-run` em banco WAL cria `-shm` e `-wal` vazios ao lado do banco (conexão ro); o arquivo principal não muda (md5 igual).
- Mutante que quebra o `assert` de import em `test_coletar_amazon.py` vaza `/tmp/teste-coletar-amazon-*` (vazio): apague.
- `rodar.mjs` mata o Chrome ao fim; `pgrep -f qa-chrome` casa com o próprio pgrep.
- Contagens do CA1 batem com o banco de 2026-11-03 (Eletrônicos 3036, Eletrodomésticos 1103, Casa 1116, WhatsApp 74); `coleta_amazon_feitos.txt` real tem 98 `busca|` + 80 `whatsapp|`, todos em NFC; só os 28 de perfumaria faltam.
