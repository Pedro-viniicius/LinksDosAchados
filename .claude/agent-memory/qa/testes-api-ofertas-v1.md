---
name: testes-api-ofertas-v1
description: Como rodar e estender os testes da API v1 de ofertas (api_ofertas.py + rota /api/v1 do servidor.py), mutantes e fatos do banco real
metadata:
  type: project
---

Arquivos: dev `testes/test_api_ofertas.py` (unit, relógio injetado), `test_api_ofertas_servidor.py` (HTTP em subprocesso), `api_ofertas.test.mjs`; QA `testes/test_api_ofertas_qa.py` e `testes/api_ofertas_qa.test.mjs` (criados em 2026-11-03, rodada 1, sem bug achado).

**Rodar:** proxies mortos (`http_proxy=https_proxy=ftp_proxy=http://127.0.0.1:9`). `python3 testes/test_api_ofertas_qa.py` leva ~60 s (23 s só o `ServidorDadosReais`, que segue o cursor pelo HTTP na cópia do banco real; 8 mil itens custam ~0,5 s POR pedido porque cada pedido varre tudo). Um teste: `python3 testes/test_api_ofertas_qa.py -k escrita_concorrente`. `--durations 12` mostra os lentos. Node: `node --test testes/api_ofertas_qa.test.mjs` (semeia o banco por `python3 -c` com `servidor.criar_banco`, horários antigos para passar da folga).

**Como o QA reaproveita o dev:** importa `test_api_ofertas as T` (T.Base com `gravar`, `ofertas`, `percorrer`, banco temporário) e `test_api_ofertas_servidor as TS2` (ServidorApi, gravar_token). O import cria `TS2.TMP`; o QA remove no `tearDownModule`. `ServidorQa` do QA reimplementa o `setUpClass` com ganchos `antes_de_subir`/`depois_de_subir` (cópia do banco real ANTES de subir).

**Banco real:** `copiar_banco_real` usa `sqlite3.backup` com origem `file:...?mode=ro`; sem `achadinhos.db` as classes de dados reais dão SkipTest (sem cópia, os mutantes rodam no espelho sem elas). Fatos (2026-11-03): 8.380 itens, 7.998 ofertas, 354 sem preço e 28 com título tipo `i.Phone`/`Acid.Complex` ficam fora; 5 itens Amazon com preço_antigo ×1000 (R$ 19,00 vs R$ 19.000,00 -> desconto_pct 100) vêm da coleta, a API só repassa.

**Mutantes:** espelho no scratchpad (copie *.py, buscas.json, testes), troque trechos por string replace e rode as 3 suítes em paralelo; 6 espelhos em paralelo cabem nos 14 núcleos. Cuidado: mutante que quebra o servidor faz a suíte HTTP do QA levar ~220 s (timeouts de 10 s). Todos os ~50 mutantes foram mortos pela união; só o dev mata sozinho: desempate por id do `ordenar`, `tem_dados`, regex do cursor por deslocamento, `compare_digest`, `?token=`, query_only, log cru, esquema Bearer, limite padrão, ordem das categorias.

**Armadilhas:** (1) mutante que devolve `proximo` null com página cheia faz laço `while True` do teste recomeçar do zero e travar: todo laço de paginação do QA tem teto e `assertIsNotNone(proximo)`. (2) `pkill -f` por padrão de caminho mata o próprio shell (exit 144): mate por PID. (3) Em 2026-11-03 o dev editou `servidor.py` e `api_ofertas.py` (15:18) durante a revisão; rode a suíte final por último. (4) Alguém pode estar rodando os mesmos testes em paralelo no projeto; portas e bancos são aleatórios, então não colide. (5) Python 3.14 colapsa `//api/v1/ofertas` para `/api/v1/ofertas` no parse da requisição. (6) POST de MBs na v1 dá BrokenPipe no cliente (o servidor responde 405 sem ler o corpo); use ~100 KB nos testes.
