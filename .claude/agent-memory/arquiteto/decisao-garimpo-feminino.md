---
name: decisao-garimpo-feminino
description: Plano garimpo-feminino-shopee (2026-11-06) — tools/garimpo_feminino isolado, 2º ponto de rede usando CS.OPENER_API sem mudar coletar_shopee, achados.json/categorias.json entre fases, fatos de terceiros sobre relatórios/feeds
metadata:
  type: project
---
O plano está em `docs/produto/planos/garimpo-feminino-shopee.md` (2026-11-06), com 16 etapas e as rodadas do dono R1 a R6.

**Decisões e por quê:**
- **O garimpo importa o `coletar_shopee` sem mudá-lo.** Ele tem um único `OPENER_API.open(` próprio, em `tools/garimpo_feminino/cliente.py`, que usa o mesmo `CS.OPENER_API`, `CS.URL_API`, `CS._ler_json` e `CS.credenciais`.
  - Não depende do `_pedir` do plano pendente: aquele `_pedir` devolve os nós cortados em `POR_BUSCA` = 30, sem `pageInfo`.
  - O `test_shopee_qa.py:649` só conta dentro do `coletar_shopee.py`. O garimpo tem um teste estático equivalente no próprio módulo.
- **O que foi medido vira configuração versionada,** revisada pelo dev entre as fases: `achados.json` (limit, teto de página, Int64, orçamento aprovado) e `categorias.json` (classe e nicho).
- **CLI com despacho sob demanda.** Cada `fase_<nome>.py` tem `configurar`/`rodar`, e o esquema completo do `garimpo.db` nasce na fundação, para que as etapas paralelas não compartilhem arquivo.
- **Faixas de foco são premissa minha (P5):** ≥ 5 alto, 2 a 4 médio, 0 a 1 neutro, < 0 ou `fora` descartado.

**Fatos de terceiros (MCP `shopee-br-affiliate-mcp`, Apify `viralanalyzer`; não oficiais):**
- O relatório tem até 500 por página.
- O cursor (`scrollId`) vale 30 s e serve uma vez. A 1ª consulta de cada relatório precisa de mais de 30 s de intervalo.
- O `generateShortLink` aceita até 5 subIds.
- `listItemFeeds` aceita FULL/DELTA, e `getItemFeedData` pagina por `datafeedId` + `offset` + `limit`.
- O MCP chama a categoria de `category_id`. A existência de `productCatId`, `listType` e `matchId` não foi confirmada.

**Ponto de segurança levantado:** o Secret fica em `/proc/<pid>/environ` enquanto um processo longo em segundo plano estiver vivo (o `pop` não apaga ali).

**How to apply:**
- Se o R1 mostrar que não existe filtro por categoria, o plano volta ao arquiteto (alternativas: keyword, loja e datafeed).
- Quando o plano `atualizar-precos-shopee-por-item` fechar, proponha um `_post_assinado` comum aos dois.

Veja [[decisao-shopee-por-item]] e [[decisao-shopee-perfumaria]].
