---
name: garimpo-consultas-testes
description: Armadilhas do tools/garimpo_feminino/consultas.py e do test_consultas.py (consultas montadas por _montar, RE_OPERACAO do cliente, literais proibidos, leitores com motivo fixo, mutantes)
metadata:
  type: project
---

Vistas na etapa 5 do plano garimpo-feminino-shopee (2026-11-06):

- As consultas são montadas no import por `_montar` (tipo, nome, operação, argumentos, seleção) a partir da tabela `TIPOS`; trocar o tipo de um id é uma linha (`TIPO_ID`, `TIPO_CATEGORIA`). O teste "tipo vem da tabela" recalcula `$x: T` de cada consulta contra `TIPOS`.
- O `cliente.operacao_de` pega o primeiro `{` seguido de identificador: serve para `query Nome($a: T) {`, `mutation` e `query Introspeccao { __schema`. Não ponha `{` antes (valor padrão de variável, por exemplo).
- Teste "sem valor embutido" proíbe aspas, número solto e `true/false/null` na consulta: a introspecção NÃO pode usar `includeDeprecated: true` (foi removido). Variável opcional fora do dict `variables`, nunca `null`.
- `RE_TIPO` precisa de colchetes balanceados (`[Int]`, `[Int!]!`); a primeira versão aceitava `[Int` e só o teste de nome ruim pegou.
- Helper de teste com `None` como valor padrão esconde o caso `None`: use sentinela (`PADRAO = object()`).
- `FormatoInvalido(CS.RespostaInvalida)` leva `.motivo` fixo (constantes `M_*`); o `garimpo.py` já captura `CS.RespostaInvalida` e imprime texto fixo. Teste: str, repr, args, `__cause__` e `__context__` sem o marcador.
- Estático do test_cli reprova `socket`, `http.client`, `conectar(`, `criar_banco`, `upsert(` até em comentário nos .py da pasta; `CS.<nome>` novo tem de entrar em `NOMES_CS` (usei só RespostaInvalida e MAX_URL).
- Fontes dos nomes: só brief + página não oficial affiliateshopee.com.br/documentacao. `listItemFeeds`/`getItemFeedData` (argumentos e campos de retorno) são palpite; `validatedReport` pode não ter `limit`.
- Mutantes: script no scratchpad copia `coletar_shopee.py`, `servidor.py`, `disparo.py`, `genero.py` e `tools/` para `<scratch>/m/`; 18 mutantes de `consultas.py`, todos mortos.

**How to apply:** ao ajustar `consultas.py` na etapa 8 ou escrever as fases que usam `ler_pagina`/`ler_relatorio`. Relacionado: [[garimpo-cliente-testes]], [[garimpo-cli-testes]].
