---
name: decisao-shopee-por-item
description: Plano atualizar-precos-shopee-por-item (2026-11-06) — productOfferV2(shopId,itemId) por item, portão G1 conferir --por-item, RELER na Shopee, teto --max-chamadas, rótulo item|<id>; fatos da doc de terceiros
metadata:
  type: project
---
O plano está em `docs/produto/planos/atualizar-precos-shopee-por-item.md` (2026-11-06).

**O que motivou:** na 1ª rodada real (06/11), a busca por termo (página 1 de 30) achou 29 de 540 itens e deixou 457 não vistos.

**Decisões e por quê:**
- **Uma chamada por item, `productOfferV2(shopId, itemId)`.** Paginar a busca não garante achar o item. A vitrine da loja (`listType 5`) quase não economiza: são 307 lojas para 540 itens.
- **Portão G1, `coletar_shopee.py conferir --por-item`.** É uma flag nova porque os testes do `conferir` contam exatamente 1 chamada à API.
- **Um único `OPENER_API.open(`** (o `test_shopee_qa.py:649` confere). Por isso o `buscar` vira um `_pedir` compartilhado.
- **A Shopee passa a gravar só o preço (`RELER`), como o ML.** A fonte antiga regravava título, nota e foto com o que vinha da API.
- **`--cat` continua obrigatório,** para não mexer no `index.html`, que estava com mudanças da black-friday.

**Fatos de terceiros (bcat95/shopee-aff, affiliateshopee.com.br, NuGet Shopee.Affiliate):**
- O `productOfferV2` aceita `shopId`, `itemId` e `matchId` como Int64, além de `listType`, `keyword`, `sortType`, `page`, `limit`, `isAMSOffer` e `isKeySeller`.
- `priceMin` vem como String. A resposta não traz o preço cheio.
- Códigos de erro: 10030 limite, 10010 parse, 11001 parâmetro, 10020 assinatura, 10035 sem acesso.
- A cota por hora é desconhecida.
- A doc oficial só abre no painel logado.

**Armadilha medida:** `test_atualizar_precos.py` falha em 3 testes antes das 06:55, porque grava `preco_em` com `T07:00` fixo e cai na folga do futuro.

**How to apply:**
- Se o G1 voltar com "não devolveu o produto pedido", a abordagem A cai. Reabra pela vitrine da loja ou pela busca paginada.
- Se voltar 10010 ou 11001, ajuste só o tipo dos ids.

Veja [[decisao-atualizar-precos]] e [[decisao-shopee-perfumaria]].
