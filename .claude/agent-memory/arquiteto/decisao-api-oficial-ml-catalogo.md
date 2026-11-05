---
name: decisao-api-oficial-ml-catalogo
description: Revisão pós-G1 (2026-11-05) do plano da API do ML: preço pelo catálogo (/products/*), vínculo anúncio→produto provado por pertença, cache ml_catalogo.json, portões G2/G3, fatos da doc de catálogo
metadata:
  type: project
---
O plano fica em `docs/produto/planos/api-oficial-ml-catalogo.md` e revisa as etapas 4 e 5 de `api-oficial-ml.md`.

**Resultado do G1:**
- `/sites/MLB/search` deu 403.
- `/items/{id}` deu 403 `access_denied`.
- No `/items/bulk`, cada elemento foi recusado.
- `/reviews/item` deu 403 PolicyAgent.
- `/products/search?q=` deu 200.
- `/products/{id}/items` deu 404 no primeiro id.

**Decisões e por quê:**
- **Vínculo provado por pertença.** O título só gera candidatos. O vínculo só vale se o `item_id` do banco for o `buy_box_winner.item_id` ou aparecer em `/products/{id}/items`.
  - Por quê: o preço de outro vendedor no link do nosso anúncio seria mentira na mensagem.
- **O preço é sempre o do próprio anúncio.** O preço do vencedor nunca vale para outro anúncio. Item vinculado que sumiu do produto conta como `indisponivel` e envelhece pela trava do `preco_em`.
- **O cache fica em `ml_catalogo.json`, não numa migração.** Assim o servidor não muda, e perder o arquivo só custa vincular de novo.
- **Portão G2** (`sondar --catalogo`, F7–F15): as etapas 2 e 3 entram com F8 = 200, F10 ≥ 25% de provados e F11 ≥ 80% de preço igual ao do banco.
- **A coleta pelo catálogo fica como entrega 2 (G3).** O piso P1(a) precisa do `/reviews`, que deu 403, e o produto não traz nota.
  - Opções: (1) "Vendas e envios" em leitura, sem garantia; (2) `/highlights`, que exige "Métricas do negócio"; (3) console.

**Fatos da doc (curl com UA, 29/12/2025):**
- **`/products/search`:** aceita `site_id` (obrigatório), `status`, `q`, `product_identifier` (GTIN), `domain_id`, `offset` e `limit`, e também um POST por atributos (pelo menos 3).
- **`/products/{id}`:** traz `buy_box_winner` (`item_id`, `price`, `original_price`, `currency_id`, `condition`, `shipping`; `null` sem competidor), `pickers`, `pictures`, `children_ids` e `parent_id`. Não traz nota nem vendas.
  - O produto pai nunca é `active`.
  - O `permalink` é `/p/<pid>`, sem o item.
- **`/products/{id}/items`:** não está na doc oficial. O PR de terceiro (Maxwbh) diz que dá 200 com o preço por anúncio e que `/items/{id}/description` também dá 200.
- **Sem token:**
  - `/products/{id}` dá 401, não PolicyAgent.
  - `/products/{id}/items` e `/products/search` dão 403 PolicyAgent.
  - `/highlights` dá 401.
  - `/sites/MLB/search?product_id=` dá 403 forbidden.
- **Slugs que existem:**
  - `pt_br/buscador-de-produtos`.
  - `pt_br/mais-vendidos-no-mercado-livre` (`/highlights`, até 20 de ITEM, PRODUCT ou USER_PRODUCT MLBU).
  - `pt_br/concorrencia-em-catalogo` (`price_to_win`, só para o dono do anúncio).
  - `pt_br/permissoes-funcionais` ("Pedidos e opiniões" está em "Vendas e envios").
- **Banco:** 14 abas com ML. O polycard tem `metadata.id`. Se ele traz `product_id`, não verifiquei: é a ideia P6 para um vínculo sem busca.

**How to apply:** quando o lead trouxer a saída do `sondar --catalogo`, confira o critério do G2. Se F10 vier baixo e F11 bom, proponha a P6. Para a coleta, espere a P5. Veja [[decisao-api-oficial-ml]].
