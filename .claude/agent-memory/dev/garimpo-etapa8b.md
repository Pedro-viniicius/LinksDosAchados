---
name: garimpo-etapa8b
description: Etapa 8 parte B do garimpo (achados.json real, consulta sem pageInfo, parada pelos nós, sonda com texto antigo, mutantes)
metadata:
  type: project
---

Etapa 8, parte B (2026-11-06):

- `CONSULTA_PRODUTOS`/`CONSULTA_LOJAS` sem `pageInfo`; o motor usa `C.ler_nos` e `_parada(pagina, cheia=len(nos) >= limit, ...)`. Página cheia na do teto = `teto`; retomada assume cheia. `ler_pagina` (exige pageInfo) ficou só para a sonda e campanhas.
- Sonda `produtos.consulta`/`lojas` do `reconhecer` usam constantes próprias COM pageInfo (`P_PRODUTOS_COM_PAGINA`, `P_LOJAS_COM_PAGINA`, texto idêntico ao antigo) e `VERSOES` NÃO sobe: falha com código vale como medida, então a rodada seguinte com tudo medido faz 0 pedido. Mutante "VERSOES 3" só morre com assert explícito do número 2.
- `comum.resposta()` agora omite `pageInfo` sem `tem_proxima=`. Em test_motor, `LIM=2` nas páginas e `ApiDinamica` devolve (n, titulo) (cheia = n == limit). `paginar` limita `limit` a 500: o teste de saturação de 1000 itens virou 2 páginas (500 + 499) por consulta, com 20/999 > 2%.
- Os tipos `Int64` do ids continuam na tabela `TIPOS`; "texto" é o valor (`int64: texto`), não o tipo GraphQL. `banco` já gravava os tipos reais (só teste novo).
- Teste que lê o `achados.json` REAL usa `G.ACHADOS` fora do `rodar` (que o troca).
- Mutantes: `<scratch>/dev-8b/mut.py` (28 mutantes, ~1 min), todos mortos.
- `rm -rf /tmp/teste-garimpo-*` é negado pelo classificador (varrer /tmp compartilhado): não tente.
