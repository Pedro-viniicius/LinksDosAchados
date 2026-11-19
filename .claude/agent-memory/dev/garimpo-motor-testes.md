---
name: garimpo-motor-testes
description: Armadilhas do tools/garimpo_feminino/motor.py e do test_motor.py (retomada, saturação, fatiamento, API dinâmica, mutantes que travam)
metadata:
  type: project
---

Vistas na etapa 7 do plano garimpo-feminino-shopee (2026-11-06):

- `paginar` recebe as variáveis SEM `page` e SEM `limit` (ValueError se vierem): o `limit` entra na chave do checkpoint porque trocar o tamanho muda a numeração. A contagem de "páginas seguidas sem novo" é refeita da tabela `requisicoes` (`novos IS NOT NULL`, por página desc), senão a retomada zera.
- Pedido que não gerou página (10030/429, falha) vai por `banco.registrar_requisicao`; o último registro do `registrar` do cliente é o da página (`gravar_pagina`). Erro da API / FormatoInvalido fecham a consulta como `erro` (nó sem id agora é pulado, e a recusa de vez não se repete: [[garimpo-correcoes-rodada1]]); `Teto`, `LimiteAtingido` e Ctrl+C deixam `pendente`.
- Com `max_rodada=N` e `teto_pagina=N` a consulta fecha como `teto` SEM levantar `Teto` (a parada vem antes do pedido N+1). Para simular "caiu antes de fechar", use `teto_pagina` maior na 1ª rodada e menor na retomada.
- `Cliente._esperar_ritmo` também chama `dormir`: `esperas` guarda pausas de ritmo além do backoff; teste o backoff por `max(esperas) >= 24`.
- Teste de fluxo sem fila fixa: `ApiDinamica(ApiFalsa)` no test_motor responde por `variables` do pedido e dá itemId único; para borda de 1,9%/2% use 1000 itens conhecidos (gravados antes por `gravar_pagina`) e N inéditos por pedido.
- Saturação só conta consultas do motor (`estrategia IN ESTRATEGIAS`) da categoria, `status` final, ordem `concluida_em DESC, id DESC`; consulta vazia (vistos 0) conta como 0%.
- Mutante que tira `usadas.add` no fatiamento entra em laço infinito (a fatia encerrada é pulada sem contar): o script de mutantes precisa de `timeout` e tratar `TimeoutExpired` como morto. Mutante "tirar `b not in fila`" é equivalente (o `usadas` cobre).
- Estático do test_cli reprova `socket` etc. até em comentário nos .py da pasta; o motor só usa `CS.ErroApi` e `CS.RespostaInvalida`.
- Script de mutantes: scratchpad (some com a sessão), copia `coletar_shopee.py`, `servidor.py`, `disparo.py`, `genero.py` e `tools/` para `<scratch>/e7/mN/`; roda `testes/test_motor.py` com cwd na pasta do garimpo da cópia.

**How to apply:** ao escrever `fase_garimpar`/piloto, que chamam `motor.garimpar_categoria(..., **motor.parametros(achados))` e `motor.sementes_do_nicho`. Relacionado: [[garimpo-banco-testes]], [[garimpo-cliente-testes]], [[garimpo-consultas-testes]].
