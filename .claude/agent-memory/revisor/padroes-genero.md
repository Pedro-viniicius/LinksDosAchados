---
name: padroes-genero
description: Como revisar o público (rodadas 1 e 2 e etapa 4 feitas) (genero.py, generos_manuais, PUT /api/items/<id>/genero, genero na API v1): medir gatilhos no banco copiado, código antigo sobre o banco v2, folga x categorias, mutantes
metadata:
  type: feedback
---

Revisão do plano genero-nas-categorias, etapas 1, 2, 3 e 5, rodada 1 (2026-11-03):
1. **Classificador:** meça no banco copiado, em `mode=ro`, quais palavras disparam cada gênero (`G._RE_M/_RE_F/_RE_U.finditer` sobre `G._norm(titulo)`) e quais linhas de produto (`_RE_LINHA_*`) e a guarda `_RE_NAO_PERFUME` pegam. Em 2026-11-03 o resultado foi F 696, M 972, U 178 e sem 1.205, sem falso positivo relevante. A lacuna: `hombre` sem plural (o teste fixa "Hombres" como `sem`).
2. **CA7 (código antigo sobre o banco v2):** rode `git show HEAD:<arq>` no scratchpad e suba esse servidor sobre a cópia já migrada. Faça GET, POST e DELETE de item e GET de regras. Passou.
3. **Contrato v1:** o `categorias` não aplica a folga de 60 s, mas o `ofertas` na ordem `atualizacao` aplica. Frase do tipo "bate com o total de ofertas?cat&genero" é falsa logo depois de uma coleta ou correção (medido: 161 x 160). Confira essa promessa em toda contagem nova.
4. **Mutantes:** script `mutar.py` (troca de string única e roda o teste-alvo) numa pasta própria do scratchpad. Os 16 mutantes morreram, exceto o filtro redundante `if g in GENEROS` do `manuais()` (a coluna tem CHECK).
5. **Rodada 2 e etapa 4 (2026-11-03):** R1 (folga x categorias) e R2 (`hombres?`/`mujer(?:es)?`) corrigidos; `null` no PUT vale em qualquer aba; ids com até 19 dígitos (`ROTA_ITEM`/`ROTA_GENERO`). No disparo, `elegiveis` filtra só as abas com gênero; na cópia, Perf+Casa dá `[]` 2.777+1.091 e `['feminino']` 629+1.091 (cerca de 60 ms). Os 11 mutantes morreram. Ponto aberto (SUGESTÃO): PUT `null` sem correção ainda grava `atualizado_em`.
6. **Front (etapas 6, 7 e 9, 2026-11-03):** as 8 páginas passaram e as medidas de 320/375/1280 px bateram com a spec. O front usa `ABAS_COM_GENERO` fixa, espelhada do `genero.py` e conferida por `test_front_constantes.py`, embora a spec peça cálculo por 2 valores. As ressalvas R5 ("·" com busca vazia) e R6 (`max-height` do cabeçalho no celular) foram corrigidas na rodada 2, que ficou APROVADO. Páginas novas do qa: `genero-qa` e `genero-integracao`; esta grava e exige uma cópia nova, sem número nem regra.
7. **Estado intermediário:** o `disparo.py` é editado em paralelo pela etapa 4. Revise só o bloco de esquema e espere que o `test_disparo` mude de contagem.

**Why:** a regra é heurística sobre dado real, e a API tem consumidor externo que lê o contrato ao pé da letra.
**How to apply:** na etapa 4 (disparo) e na rodada 2, repita os itens 1 e 3 e confira se o filtro do disparo usa `do_item` com `manuais` lidos uma vez por tick. Ver [[padroes-api-v1]], [[padroes-disparo]] e [[revisao-ambiente]].
