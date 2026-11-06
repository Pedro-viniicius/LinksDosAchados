# Interpretação dos achados da Open API de afiliados da Shopee (R1)

Escrito à mão, na etapa 8 do garimpo feminino. O `api_findings.md` é gerado pelo `garimpo.py reconhecer` e sobrescrito a cada rodada: ele guarda só o que foi medido. Este arquivo diz o que a ferramenta faz com cada medida e o que ficou em aberto. A decisão de produto está no brief (`docs/produto/briefs/garimpo-feminino-mvp.md`, seção "Decisões a partir do R1").

Convenção: `(medicoes #N)` é a linha `N` da tabela `medicoes` do `garimpo.db`. O que não vem de lá diz de onde vem: a tabela `requisicoes` (colunas `codigo`, `ms` e `bytes`), ou uma conta feita a partir de números medidos, marcada como "conta". Nenhum texto de produto, link ou mensagem da API é reproduzido aqui.

## Limites de paginação

- **`limit`:** 20 e 50 devolvem a página cheia (medicoes #1, #5). 100 e 500 são recusados com o código 11001, parâmetro acima do máximo (medicoes #6, #7). O máximo do `productOfferV2` é 50.
- **Profundidade com `limit` 20:** a página 100 ainda traz 20 itens (medicoes #48) e da 101 em diante vem vazia (medicoes #55, #54, #53, #52, #51, #50, #49). Última página com itens: 100; sem páginas repetidas; teto exato (medicoes #56).
- **Profundidade com `limit` 50:** a página 40 traz 50 itens (medicoes #77) e a 41 vem vazia (medicoes #78, #79, #80). Última página com itens: 40, 2.000 itens até ela, sem repetidas e sem erro (medicoes #81).
- **Leitura:** o teto não é de páginas, é de itens: 2.000 por consulta (100 × 20 = 40 × 50 = 2.000; medicoes #56 e #81). Usar `limit` 50 gasta 40 pedidos por consulta em vez de 100 para o mesmo total.
- **`achados.json`:** `limit` 50 e `teto_pagina` 40. A parada do motor fica nos nós da página (ver a seção sobre `pageInfo`).

## Tipos dos argumentos

- **`productCatId`:** `Int`. Vai como número (medicoes #2 e #27).
- **`shopId`, `itemId` e `matchId`:** `Int64` no schema (medicoes #2). Como número JSON a API recusa com o código 10010 (medicoes #37); como texto aceita e devolve o item pedido (medicoes #38). O `achados.json` fica com `int64: "texto"`.
- **O que volta nos nós:** `itemId`, `shopId`, `periodStartTime`, `periodEndTime`, `sales` e `priceDiscountRate` voltam como número; preços, taxas de comissão e `ratingStar`, como texto decimal; `productCatIds` e `shopType`, como lista (medicoes #72). O `banco` grava os dois formatos (teste com nós desses tipos).
- **Campos que podem vir nulos:** nenhum dos 11 campos testados veio nulo em 50 nós (medicoes #60 a #70).

## A recusa com `pageInfo`

- **O que aconteceu:** a consulta completa, com os 20 campos e o `pageInfo`, foi recusada com o código 10010 duas vezes (medicoes #3, #47). Os mesmos 20 campos, sem o `pageInfo`, passaram nas páginas 1 e 10 (medicoes #72, #73, resumo em #74), sem campo ausente e com 50 nós em cada.
- **A causa exata não foi isolada.** O `pageInfo { page limit hasNextPage }` passou junto de 9 campos em `limit` 50 (medicoes #71). Ficaram sem medir a combinação dos 20 campos com `pageInfo` em `limit` 50 e o efeito de cada campo do `pageInfo` sozinho. Não há como afirmar, com o que foi medido, se o problema é o `pageInfo` em si, o conjunto de campos, o `limit` de 20 ou a combinação deles.
- **O mesmo padrão em outras duas consultas:** `shopOfferV2` foi recusada com `pageInfo` (medicoes #85) e aceita sem ele, com 20 itens (medicoes #86); a de campanhas passou sem ele, com 20 itens (medicoes #87).
- **O que a ferramenta faz:** a `CONSULTA_PRODUTOS` e a `CONSULTA_LOJAS` não pedem o `pageInfo`. O motor encerra a consulta quando a página vem vazia, vem com menos itens que o `limit` ou é a página do teto (40). Se o último lote vier exatamente cheio, sai um pedido a mais, que volta vazio: custa no máximo 1 pedido por consulta. Isso não depende de nenhuma medição nova.
- **A sonda `produtos.consulta`** do `reconhecer` continua medindo o texto com `pageInfo` (a medição de hoje vale e não é refeita). A de campanhas (`CONSULTA_CAMPANHAS`) ainda pede o `pageInfo`, porque nenhuma fase a usa no MVP.

## Ordenações, filtros e `listType`

- **`sortType` 1 a 5:** cada um devolve 20 itens (medicoes #57, #22, #23, #24, #25) e, na página 1, nenhum par tem item em comum: os 10 pares dão 0 (medicoes #58). Os 5 ficam no motor.
- **`isAMSOffer` e `isKeySeller`:** 20 itens cada (medicoes #34, #35). Em comum com o `sortType` 1 há 3 e 0 itens (medicoes #59): trazem conjuntos diferentes, então ficam.
- **`listType` 0 a 4 com `matchId` igual à categoria:** devolveram 20, 0, 20, 0 e 20 itens (medicoes #28 a #32). Em comum com o `productCatId`: 0 para o 0 e o 2 e 20 de 20 para o 4 (medicoes #33). O 1 e o 3 vêm vazios.
- **Decisão:** o `listType` sai do motor (`list_types: []`). O 4 só repete o `productCatId`. A estratégia `listtype` continua na ordem padrão, mas com a lista vazia ela é pulada sem nenhum pedido.

## Datafeed

- **Feeds:** o `listItemFeeds` FULL devolve 2 feeds, somando 110.000 linhas (medicoes #82). O DELTA devolve 2 feeds, somando 193.056 (medicoes #83).
- **Uma página de dados do FULL:** `limit` 500 aceito, 500 linhas, formato de objeto JSON com 16 campos, e ainda havia mais (medicoes #84). Colunas de categoria presentes: `global_category1`, `global_category2`, `global_catid1` e `global_catid2` (medicoes #84).
- **Tamanho:** a resposta dessa página teve 1.581.341 bytes (tabela `requisicoes`, coluna `bytes`), perto do teto de 2 MB do cliente. Se uma página passar do teto, baixar o `limit` do feed; o teto não sobe.
- **Uso no MVP (RF10):** o mapa de categorias sai do datafeed. Conta: 110.000 linhas ÷ 500 por página = 220 pedidos, contra 1.400 a 2.400 estimados por sementes.
- **Limites:** as colunas medidas (medicoes #84) não incluem comissão, vendas nem link de afiliado. O datafeed não substitui o garimpo, e nenhuma linha dele vira link de teste.

## Taxa e erros transitórios

- **Rajada:** 96 pedidos seguidos, em degraus de 1, 2 e 4 por segundo, sem nenhum 10030; a rajada parou por um 10000, não por limite (medicoes #39). A taxa medida foi 0,389, 0,385 e 0,343 pedidos por segundo (medicoes #39): a latência da API já limita o ritmo bem abaixo do alvo, então o limite de taxa não foi alcançado.
- **Erro 10000:** é transitório. Dos 180 pedidos do R1, 7 voltaram com 10000 (tabela `requisicoes`, coluna `codigo`). As sondas `pagina.100` e `sort.1` falharam assim (medicoes #14, #21) e passaram quando repetidas (medicoes #48, #57).
- **Custo:** contas do brief, não medições: perto de 4,7 s por pedido em `limit` 50, até 200 pedidos por categoria (5 ordenações × 40 páginas) e uns 16 minutos por categoria. As 20.000 requisições levariam perto de 26 horas. Por isso a seleção de categorias e o piloto decidem o orçamento. Na tabela `requisicoes`, os 153 pedidos de produto aceitos levaram em média 2,9 s (coluna `ms`, limit 20 e 50 misturados).

## subIds

- **Aceito:** `fem` e `sonda` geraram um link curto da Shopee, do afiliado do dono (medicoes #40).
- **Recusados:** o hífen e o sublinhado voltaram com o código 11001, subId inválido (medicoes #41, #42). Os subIds do garimpo usam só letras e números.
- **Ficou sem medir:** maiúsculas, dígitos e subIds mais longos. O separador entre subIds no relatório de conversões só aparece depois de cliques (Fase 7), e `separador_subids` fica nulo no `achados.json`.

## O que foi descartado

- `limit` 100 e 500 (medicoes #6, #7), e qualquer página acima do teto de 2.000 itens (medicoes #56, #81).
- Id `Int64` enviado como número (medicoes #37).
- `listType` 0, 1, 2 e 3 (medicoes #33); o 4 repete o `productCatId`.
- A consulta de produtos com `pageInfo` (medicoes #3, #47).
- O datafeed como fonte de links ou de comissão (medicoes #84).

## O que ficou sem medir

- **Relatório de conversões (`conversionReport`):** recusado com o código 10010 duas vezes (medicoes #46, #88). A causa não foi investigada. É da etapa 11, fora do MVP.
- **`validatedReport`:** nenhuma sonda o chamou (precisa de um `validationId` que ainda não existe). Também da etapa 11.
- **Separador de subIds no relatório:** depende de cliques reais.
- **`shopOfferV2` com filtros:** a sonda sem `pageInfo` usou só `keyword`, `page` e `limit` (medicoes #86). `shopId`, `shopType`, `isKeySeller`, `sortType` e `sellerCommCoveRatio` não foram exercidos.
- **Datafeed DELTA:** só foi listado (medicoes #83); nenhuma página de dados foi lida.
- **Limite de taxa (10030):** nunca apareceu (medicoes #39). O limite real continua desconhecido; o backoff do cliente cobre o caso.
- **A causa da recusa com `pageInfo`:** ver a seção própria.
