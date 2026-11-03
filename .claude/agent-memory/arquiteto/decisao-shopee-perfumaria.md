---
name: decisao-shopee-perfumaria
description: Plano perfumaria-tres-lojas (2026-11-03) — Shopee via Open API de afiliados (não console), chave de ordem na coleta, 42 termos, fatos da pesquisa sobre links da Shopee
metadata:
  type: project
---
O plano está em `docs/produto/planos/perfumaria-tres-lojas.md` (2026-11-03). Ele aguarda as respostas do dono: Open API, ID de afiliado e um link de exemplo.

**Decisões e por quê:**
- **A Shopee entra pela Open API oficial, num `coletar_shopee.py` só com stdlib.** O link curto da Shopee não prova quem é o dono, e o `offerLink` gerado com as credenciais dele resolve isso. O script de console seria frágil (antibot) e exigiria abrir CORS para duas origens novas.
- **Sem a Open API, a Shopee vai para uma entrega 2, pelo navegador.**
- **Não há migração:** `loja` é TEXT.
- **O nome da loja só pode mudar junto nos dois lados.** O `test_disparo_qa` roda o `buildMsg` do `index.html` real, então mudar o nome de uma loja só no `disparo.py` quebra a paridade.
- **Chave das ordens na Amazon.** Uma linha `busca|termo|ordem` seria lida errado, porque `feitos()` pega o último segmento das linhas `busca|`. Por isso as ordens usam o prefixo `ordem|<ordem>|<termo>`, e a relevância mantém a URL e a chave antigas.

**Fatos da pesquisa (fontes de terceiros, sem confirmação oficial):**
- O link de afiliado é curto, `s.shopee.com.br/<código>` ou `shope.ee/<código>`. O dono se confere por `utm_source=an_<ID>` na URL final.
- A Open API fica em `open-api.affiliate.shopee.com.br/graphql` e assina com `sha256(AppID+ts+corpo+Secret)`.
- `productOfferV2` tem `sortType`: 1 relevância, 2 vendas, 3 maior preço, 4 menor preço, 5 comissão. Não há ordem por nota.
- O ML, pelo que se sabe, só ordena por relevância, menor preço e maior preço. O sufixo de maior preço é `_OrderId_PRICE*DESC` (não verificado).

**Why:** nada disso aparece no código.

**How to apply:** se o dono responder que não tem a Open API, escreva só a entrega 2 (B). Não reabra E1 a E4. Veja [[decisao-eletronicos-coleta-ml]] e [[decisao-disparo-automatico]].
