---
name: padroes-coletas-piso
description: Revisão de regra de dado espalhada (piso de qualidade, recusa de usado, saneamento de preço antigo, abas novas): procurar todo caminho de gravação e toda coleta que a regra devia cobrir; medir no banco copiado
metadata:
  type: feedback
---

Rodada 1 do plano abas-nichadas-e-coleta (2026-11-04). O que pegou e como medir:
1. **Saneamento posto só no `upsert`**: o `preco_antigo_plausivel` ficou no `upsert` (POST e coletas), mas o `PATCH /api/items/<id>` com `data` (botão "Atualizar preço" do card Amazon, via `/api/fetch`) grava os CAMPOS crus. O README prometia "em toda gravação". Provado num PATCH contra servidor próprio na cópia. Toda regra de normalização nova: `grep -n "UPDATE items SET" servidor.py` e confira cada caminho.
2. **Regra que o ADR manda para "cada coleta"**: a recusa de usado entrou na Amazon e no ML, e a Shopee (`no_para_item`, usado também pelo `importar`) ficou sem ela. O README do dev declarou a lacuna como fato. Compare a lista de coletas do ADR com o código, uma por uma.
3. **Medições que valem repetir** (banco em `mode=ro`, scripts no scratchpad): quantos itens atuais passam no piso (Amazon 2.435 de 5.643; ML 1.177 de 2.705, com 1.331 sem `vendas`), quantos títulos a regex de usado pega (19, todos verdadeiros), dry-run da migração na cópia (bate com a Decisão 2: 5.837 movidos e 33 preços), comparação coluna a coluna com a segunda cópia (só `cat`, `atualizado_em`, `preco_antigo` e `desconto` mudam; url 0) e F/M/U/sem da perfumaria (696/972/178/1.205, igual antes e depois).
4. Os 17 nomes de aba estão em `buscas.json`, `ORDEM_ABAS` do `index.html` e no bloco BUSCAS do `coletar_ml.js`, amarrados por `test_front_constantes.py` e pelos testes do `coletar_ml`.

5. **Rodada 2 (2026-11-04):** itens 1 e 2 corrigidos (`sanear_precos` no `upsert` e no PATCH com `data`; `eh_usado` no `no_para_item` da Shopee, regex amarrada às outras duas por `TestUsado.test_mesma_lista_da_amazon_e_do_ml`). O `importar` agora confere o dono de cada link distinto. Prova dinâmica: `patch_teste.py` (PATCH com antigo 5x num item Amazon da cópia → `''`/`''`, url mantida). Na rodada 1 não guardei cópia dos arquivos: para isolar as linhas da rodada 2, salve `git diff HEAD` no scratchpad ao fim da rodada 1.

**Why:** o dev cumpre o texto do plano ("o upsert aplica") e a doc generaliza ("toda gravação"); a diferença só aparece seguindo os outros caminhos.
**How to apply:** em toda regra de dado nova, liste os caminhos de escrita e as coletas antes de ler os testes. Ver [[padroes-coleta-ml]], [[padroes-shopee-tres-lojas]] e [[revisao-ambiente]].
