---
name: decisao-atualizar-precos
description: Plano atualizar-precos (2026-11-04), com items.preco_em em user_version 3, validade global em config, atualizar_precos.py com FONTES por loja, ColetaML.atualizar, trava e aviso no disparo e preco_em/preco_max_horas na v1
metadata:
  type: project
---
O plano está em `docs/produto/planos/atualizar-precos.md` (2026-11-04). Ele aguarda as respostas do dono de P1 a P6 e a spec `docs/produto/specs/atualizar-precos.md`. Não há brief.

**Decisões e por quê:**
- **`atualizado_em` não serve como idade do preço.** A migração, o `classificar_lista` e o PUT do gênero regravam a coluna, e ela é o cursor da v1. Por isso entra a coluna `items.preco_em`, gravada só no `upsert` e no PATCH quando o `ler_preco` dá valor.
- **Migração v3 em `disparo.migrar`.** O `ALTER` só roda se `items` existe e não tem a coluna: os testes chamam `migrar` em banco sem `items`. O backfill usa `criado_em`, que é limite inferior, o lado seguro.
- **Validade global:** `config.preco_validade_horas`, de 1 a 168, padrão 24. O valor é validado na leitura (`disparo.validade_horas`) porque o PUT da config aceita qualquer JSON. Não ficou por regra: o dono pediu "um prazo", e ele serve ao cartão também.
- **O lote só atualiza:** `upsert(inserir=False)` e, no POST, `so_existentes: true`. Assim não há rota nova nem mudança de CORS para o ML.
- **Ponto de troca:** o `atualizar_precos.py` concentra a seleção, a gravação e o resumo. A rede fica em `FONTES` por loja. As APIs oficiais (PA-API, multiget do ML, Shopee por `itemId`) entram como fonte por id.
- **Amazon pela busca:** 282 pares (termo, ordem), cerca de 40 min. A página do produto, item a item, levaria cerca de 14 h. Fica um fallback opcional com `--produtos N`.
- **Item que sumiu, ficou indisponível ou caiu do piso** não é gravado nem apagado. Envelhece, e a trava o tira do disparo.

**Fatos medidos em modo ro (2026-11-04):**
- Só 10 das 17 abas têm itens.
- A `config` está vazia e não há regra cadastrada.
- O `criado_em` bate com as datas de preço que o lead informou.
- 353 itens da Amazon não têm preço.
- Não existe `coleta_shopee_feitos.txt`.

**Why:** as armadilhas (testes de `migrar` sem `items`, o cursor da v1) e as medições não aparecem no código.

**How to apply:** se o dono responder P1 a P6, ajuste só o plano. Se a premissa P1 ("API" = APIs das lojas) cair, revise o peso da etapa 3. Veja [[decisao-disparo-automatico]], [[decisao-api-achadinho-turbo]] e [[decisao-abas-nichadas]].
