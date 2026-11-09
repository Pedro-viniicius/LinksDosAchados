---
name: testes-shopee-por-item
description: atualizar_precos.py shopee por item (productOfferV2 shopId+itemId) e conferir --por-item (G1): arquivo de QA (108 testes), rodadas 1 e 2, como rodar, mutantes, riscos abertos
metadata:
  type: project
---

Rodada 1 em 2026-11-08. Arquivo do QA: `testes/test_shopee_por_item_qa.py` (76 testes, ~0,4 s, sem rede). Importa `test_atualizar_precos as T` (ambiente temporário, `T.Base`, `T.no`, `T.BUSCAR_ITEM`) e define `tearDownModule` que apaga `T.TMP`. Rodar: `http_proxy=https_proxy=ftp_proxy=http://127.0.0.1:9 python3 testes/test_shopee_por_item_qa.py`.

**Como testei:** `BaseItem(T.Base)` troca `CS.buscar_item`, `CS.destino` e `CS.buscar` (reprova) por falsos com `respostas`/`efeitos` por id (efeito = o "site" mexe no banco no meio da rodada). `TestConferirPorItem` usa `CS.main(['conferir', ...])` com `CS.OPENER_API.open` falso e uma fila de respostas (registra eventos api/dono/pausa para provar a ordem). Testes de documentação leem README/CLAUDE.md por regex e confrontam com argparse e strings do código.

**Mutantes (37, todos mortos pelo meu arquivo):** espelho no scratchpad com `rsync` EXCLUINDO segredos (cuidado: o rsync levou `api_token.txt`, `ml_tokens.json` e `ml_catalogo.json` para o espelho; apague na hora e acrescente `--exclude` desses nomes). Só o meu arquivo mata: m21/m25/m26/m28/m29 (parte do `conferir`), m32 (pausa 1-3), m35/m36 (README).

**Riscos que ficaram abertos (não são bug do plano):** (Q2) com 0 nós casados e só respostas vazias nada interrompe a rodada: queima o teto inteiro e marca o dia como `indisponivel`; (Q3) um item que faz a API devolver erro/resposta inválida trava a fila (o mesmo item é sempre o primeiro, não é marcado); G1 só prova um item vivo; `priceMin` sem checagem de unidade/plausibilidade; id `0` e id com zero à esquerda não casam.

**Armadilhas:** a docstring do `atualizar_precos.py` quebra linha no meio de "padrão 1000, máximo 5000": normalize espaços antes de comparar; `'12 '` com espaço no fim é preço legível (`_numero` faz strip).

## Rodada 2 (2026-11-08): tentados, parada do filtro, G1 com preço, README/backup
Arquivo agora com 108 testes. Novas classes: `TestTentadosTresRodadas`, `TestParadaDoFiltro`, `TestTentadosENaFila`, `TestErrosDaApiPelaRequisicaoDeVerdade` (usa `T.BUSCAR_ITEM` e o `_pedir` real com opener falso), mais métodos dentro de `TestConferirPorItem` (G1 "preço lido") e `TestDocumentacao` (dois blocos, backup do README rodado de verdade em bash + restauração com `migrar_categorias.py --restaurar` em banco temporário).
- Relógio coerente de um dia: `BaseR2.dia(d)` troca `A.hoje` e `S.agora`. Só mockar `A.hoje` deixa o `preco_em` com a data real e distorce o `_tentado_sem_sucesso` (tentado >= preco_em).
- Para testar `--restaurar` em banco temporário: `ACHADINHOS_PORTA` numa porta livre (há servidor real na 8765, mas só o banco real testa a 8765).
- Parada do filtro conta respostas NOVAS sem casado na rodada, **não precisam ser seguidas** (o texto de stderr ainda diz "seguidas"; o README foi corrigido). Casado em qualquer ponto desliga a parada até o fim da rodada.
- Mutantes (32, rodada 2, espelho com rsync excluindo segredos): todos mortos pelo meu arquivo, exceto os de `proteger_processo` (ml_api e shopee), que só o `test_atualizar_precos.py` do dev mata (ordem e processo protegido em subprocesso, ótimos).
- Riscos baixos abertos: falso "não filtrou" se as 20 primeiras da fila forem produtos que sumiram (rodar de novo no mesmo dia segue); queda da API com 10000 em tudo gasta 20 chamadas por rodada; item `usado`/`fora_do_piso` responde, mas nunca atualiza o `preco_em` e fica sempre à frente da fila (gasta cota todo dia).
- Os arquivos (README, atualizar_precos.py) foram editados durante a rodada: rode a suíte inteira de novo no fim.
