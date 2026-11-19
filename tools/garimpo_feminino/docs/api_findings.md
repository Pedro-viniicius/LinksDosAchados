# Achados da Open API de afiliados da Shopee (Fase 1, `reconhecer`)

Gerado pelo `garimpo.py reconhecer` em 2026-11-06T09:24:37. Só valores medidos: cada número aponta a linha da tabela `medicoes` do `garimpo.db` (`#id`). "não medido" quer dizer que a sonda não rodou ou falhou; a mensagem de erro da API fica só no banco. A interpretação fica para a etapa 8.

## Schema

- Introspecção completa: aceita, 78 tipos, 59783 bytes, salva em `docs/schema.json` (medicoes #2)
- Raiz das consultas: `Query`; das mutações: `Mutation` (medicoes #2)
- Operações do garimpo no schema: `conversionReport` sim, `generateShortLink` sim, `getItemFeedData` sim, `listItemFeeds` sim, `productOfferV2` sim, `shopOfferV2` sim, `shopeeOfferV2` sim, `validatedReport` sim (medicoes #2)
- Argumentos do productOfferV2: `isAMSOffer: Boolean`, `isKeySeller: Boolean`, `itemId: Int64`, `keyword: String`, `limit: Int`, `listType: Int`, `matchId: Int64`, `page: Int`, `productCatId: Int`, `shopId: Int64`, `sortType: Int` (medicoes #2)
- Argumento `productCatId` existe: sim (medicoes #2)
- Argumento `listType` existe: sim (medicoes #2)
- Argumento `matchId` existe: sim (medicoes #2)
- Argumento `isAMSOffer` existe: sim (medicoes #2)
- Argumento `isKeySeller` existe: sim (medicoes #2)
- Tipos dos argumentos: `Boolean` (SCALAR), `Int` (SCALAR), `Int64` (SCALAR), `String` (SCALAR) (medicoes #2)
- Campos do nó: `appExistRate`, `appNewRate`, `commission`, `commissionRate`, `imageUrl`, `itemId`, `offerLink`, `periodEndTime`, `periodStartTime`, `price`, `priceDiscountRate`, `priceMax`, `priceMin`, `productCatIds`, `productLink`, `productName`, `ratingStar`, `sales`, `sellerCommissionRate`, `shopId`, `shopName`, `shopType`, `shopeeCommissionRate`, `webExistRate`, `webNewRate` (medicoes #2)
- Campos do pageInfo: `hasNextPage`, `limit`, `page`, `scrollId` (medicoes #2)
- Argumentos do generateShortLink: `input: ShortLinkInput!` (medicoes #2)

## Consulta de produtos do garimpo (`productOfferV2`, todos os campos do brief)

- Aceita: não medido (a sonda falhou: código 10010) (medicoes #47)
- Só `itemId shopId productCatIds`: aceita, 20 itens (medicoes #4)

## `limit` por página

| limit pedido | itens devolvidos | medição |
|---|---|---|
| 20 | 20 | (medicoes #1) |
| 50 | 50 | (medicoes #5) |
| 100 | não medido (a sonda falhou: código 11001) (medicoes #6) | |
| 500 | não medido (a sonda falhou: código 11001) (medicoes #7) | |

## Profundidade de `page`

| page (limit 20) | itens devolvidos | medição |
|---|---|---|
| 1 | 20 | (medicoes #8) |
| 2 | 20 | (medicoes #9) |
| 5 | 20 | (medicoes #10) |
| 10 | 20 | (medicoes #11) |
| 20 | 20 | (medicoes #12) |
| 50 | 20 | (medicoes #13) |
| 75 | 20 | (medicoes #15) |
| 87 | 20 | (medicoes #16) |
| 93 | 20 | (medicoes #17) |
| 96 | 20 | (medicoes #18) |
| 98 | 20 | (medicoes #19) |
| 100 | 20 | (medicoes #48) |
| 101 | 0 | (medicoes #55) |
| 103 | 0 | (medicoes #54) |
| 106 | 0 | (medicoes #53) |
| 112 | 0 | (medicoes #52) |
| 125 | 0 | (medicoes #51) |
| 150 | 0 | (medicoes #50) |
| 200 | 0 | (medicoes #49) |

- Resultado: última página com itens novos: 100; primeira sem itens ou repetida: 101; exata: sim; páginas repetidas: nenhuma (medicoes #56)

## Sobreposição dos `sortType` (mesma palavra-chave, page 1)

| sortType | itens | medição |
|---|---|---|
| 1 | 20 | (medicoes #57) |
| 2 | 20 | (medicoes #22) |
| 3 | 20 | (medicoes #23) |
| 4 | 20 | (medicoes #24) |
| 5 | 20 | (medicoes #25) |

- Itens em comum por par: 1x2: 0, 1x3: 0, 1x4: 0, 1x5: 0, 2x3: 0, 2x4: 0, 2x5: 0, 3x4: 0, 3x5: 0, 4x5: 0 (medicoes #58)

## `listType` 0 a 4 com `matchId` da categoria × `productCatId`

- `productCatId` (referência): categoria `100104` (nível 2), 20 itens (medicoes #27)

| listType | itens | em comum com o productCatId | medição |
|---|---|---|---|
| 0 | 20 | 0 | (medicoes #28) |
| 1 | 0 | 0 | (medicoes #29) |
| 2 | 20 | 0 | (medicoes #30) |
| 3 | 0 | 0 | (medicoes #31) |
| 4 | 20 | 20 | (medicoes #32) |

## `isAMSOffer` e `isKeySeller` (comparados ao sortType 1)

- `isAMSOffer: true`: 20 itens (medicoes #34)
- `isKeySeller: true`: 20 itens (medicoes #35)
- Em comum com o sortType 1: isAMSOffer: 3; isKeySeller: 0 (medicoes #59)

## Int64 (`shopId` e `itemId`)

- Como número: não medido (a sonda falhou: código 10010) (medicoes #37)
- Como texto: aceito, 1 itens; o item pedido voltou: sim (medicoes #38)

## Campos do `productOfferV2` que podem vir nulos (9 de produção + 1 campo, limit 50)

| campo | resultado | nulos | medição |
|---|---|---|---|
| productLink | aceito | 0 de 50 | (medicoes #60) |
| priceMax | aceito | 0 de 50 | (medicoes #61) |
| commissionRate | aceito | 0 de 50 | (medicoes #62) |
| sellerCommissionRate | aceito | 0 de 50 | (medicoes #63) |
| shopeeCommissionRate | aceito | 0 de 50 | (medicoes #64) |
| commission | aceito | 0 de 50 | (medicoes #65) |
| productCatIds | aceito | 0 de 50 | (medicoes #66) |
| shopName | aceito | 0 de 50 | (medicoes #67) |
| shopType | aceito | 0 de 50 | (medicoes #68) |
| periodStartTime | aceito | 0 de 50 | (medicoes #69) |
| periodEndTime | aceito | 0 de 50 | (medicoes #70) |

- `pageInfo { page limit hasNextPage }` junto dos 9 campos: aceito (medicoes #71)
- Campos aceitos juntos: `productLink`, `priceMax`, `commissionRate`, `sellerCommissionRate`, `shopeeCommissionRate`, `commission`, `productCatIds`, `shopName`, `shopType`, `periodStartTime`, `periodEndTime`; recusados: (nenhum); confirmados nas páginas: 1 sim, 10 sim (medicoes #74)

## Profundidade de `page` com limit 50 (teto de páginas ou de itens)

| page (limit 50) | itens devolvidos | medição |
|---|---|---|
| 20 | 50 | (medicoes #75) |
| 39 | 50 | (medicoes #76) |
| 40 | 50 | (medicoes #77) |
| 41 | 0 | (medicoes #78) |
| 60 | 0 | (medicoes #79) |
| 99 | 0 | (medicoes #80) |

- Resultado: última página com itens: 40; primeira sem itens: 41; itens até a última: 2000; páginas repetidas: nenhuma; com erro: nenhuma (medicoes #81)

## Taxa (rajada em degraus, para no 1º 10030)

- Requisições: 96 de 120; parou por: erro_api; primeiro 10030/429 na requisição: nenhum (medicoes #39)
- Degrau de 1 req/s: 40 enviadas, taxa medida 0.389 req/s em 100.276 s (medicoes #39)
- Degrau de 2 req/s: 40 enviadas, taxa medida 0.385 req/s em 101.269 s (medicoes #39)
- Degrau de 4 req/s: 16 enviadas, taxa medida 0.343 req/s em 43.726 s (medicoes #39)

## subIds no `generateShortLink`

- subIds `fem` `sonda`: aceito; link curto da Shopee: sim; dono conferido: sim (medicoes #40)
- subIds `fem` `sonda-hifen`: não medido (a sonda falhou: código 11001) (medicoes #41)
- subIds `fem` `sonda_sub`: não medido (a sonda falhou: código 11001) (medicoes #42)
- Separador dos subIds no relatório de conversões: não medido (só aparece depois de cliques; Fase 7)

## Datafeeds

- `listItemFeeds` FULL: 2 feeds; soma de totalCount: 110000 (medicoes #82)
- `listItemFeeds` DELTA: 2 feeds; soma de totalCount: 193056 (medicoes #83)
- `getItemFeedData` (1 página, limit 500): feed FULL; total 10000; 500 linhas; tem mais: sim; formato da linha: json_objeto, 16 campos; colunas: `description`, `discount_percentage`, `global_category1`, `global_category2`, `global_catid1`, `global_catid2`, `global_item_attributes`, `image_link`, `image_link_3`, `item_rating`, `itemid`, `price`, `product_link`, `sale_price`, `title`; colunas de categoria: `global_category1`, `global_category2`, `global_catid1`, `global_catid2` (medicoes #84)

## Outras consultas (1 página cada)

- `shopOfferV2`: não medido (a sonda falhou: código 10010) (medicoes #85)
- `shopOfferV2` sem pageInfo: 20 itens; campos: `commissionRate`, `imageUrl`, `offerLink`, `periodEndTime`, `periodStartTime`, `ratingStar`, `remainingBudget`, `sellerCommCoveRatio`, `shopId`, `shopName`, `shopType`; não vieram: (nenhum) (medicoes #86)
- `shopeeOfferV2`: 20 itens; campos: `categoryId`, `collectionId`, `commissionRate`, `imageUrl`, `offerLink`, `offerName`, `offerType`, `originalLink`, `periodEndTime`, `periodStartTime`; não vieram: (nenhum) (medicoes #87)
- `conversionReport`: não medido (a sonda falhou: código 10010) (medicoes #88)
