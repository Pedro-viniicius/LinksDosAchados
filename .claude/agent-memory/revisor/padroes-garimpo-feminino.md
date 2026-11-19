---
name: padroes-garimpo-feminino
description: Garimpo feminino (tools/garimpo_feminino): como provar sem rede, achados da rodada 1 das etapas 1-7 e o que reconferir nas etapas seguintes
metadata:
  type: feedback
---

Rodada 1 das etapas 1 a 7 (2026-11-06): veredito MUDANÇAS NECESSÁRIAS, com 5 ATENÇÃO (R1-R5) e 4 SUGESTÃO. Os testes são fortes: 54 de 55 mutantes mortos, e o vivo era equivalente. Os problemas ficaram no que os autores dos testes assumiram como desejado (erro vira medição, erro trava a categoria), então pense em cenário, não em cobertura.

Achados para conferir na rodada 2:
- **R1:** falha transitória ou credencial errada vira medição (`ok: false`) no `reconhecer`. Sai com 0 e a retomada pula tudo: 0 pedidos com a rede de volta. Só o `--refazer` recupera, e ele repete a rajada.
- **R2:** `ErroApi` permanente numa consulta trava a categoria em toda rodada, sem `parada` em `categories` (CA3).
- **R3:** um nó ruim recusa a página inteira, para sempre. Vale para nó sem `itemId` e para título com surrogate solto (`UnicodeEncodeError` é `ValueError`).
- **R4:** SIGTERM e SIGHUP deixam o log sem `SAIDA=`. O plano manda usar `kill` e promete a linha.
- **R5:** `infantis` não casa no `foco` (o plural só soma `s`).

Armadilha para a etapa 9: a chave do checkpoint não tem fase nem teto. Um `paginar(teto_pagina=2)` do `mapa` com `{productCatId, sortType}` fecha a mesma consulta do `sort` do motor, que depois não pede nada (provado). Confira como o `fase_mapa` evita isso.

**Why:** o R1 e os R2-R6 do plano dependem de `SAIDA=` e de `requisicoes`, e o dono roda uma vez, com a cota real. Falso positivo aqui custa cota.

**How to apply:**
- Prova sem rede: script no scratchpad com `sys.path` em `tools/garimpo_feminino/testes`, `import comum` primeiro (isola ambiente, proxies e banco), `comum.isolado(api)`, `test_reconhecer.rodar` e `ApiRoteada`.
- Sinal real: subprocesso que troca `CS.OPENER_API.open` e injeta um módulo de fase em `sys.modules` e em `G.SUBCOMANDOS`; `ACHADINHOS_GARIMPO_DIR` e `ACHADINHOS_DB` temporários.
- Mutante: copie `tools/garimpo_feminino` e os módulos `coletar_shopee.py`, `servidor.py`, `disparo.py` e `genero.py` para uma pasta do scratchpad, sem banco nem segredo.
- `test_reconhecer.Resultado.log` junta os logs em ordem de nome (`-2.log` antes do outro): a última linha pode não ser da última rodada. Use `r.codigo`.
- Nas etapas 8 a 15, confira: as chaves novas do `achados.json`, o nome das estratégias (o `garimpo` só valida o regex; o `motor` recusa no fim) e o formato dos subIds (`[a-z0-9]{1,20}` só chega na etapa 10).

Ver [[padroes-shopee-tres-lojas]].
