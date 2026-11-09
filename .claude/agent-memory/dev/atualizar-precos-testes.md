---
name: atualizar-precos-testes
description: Armadilhas da migração v3 (items.preco_em), do upsert(inserir=), do so_existentes e da trava de preço velho no disparo; testes que fixam versão e chaves; falhas do test_genero_qa que dependem dos dados reais; fonte da Shopee por item (limites pelo ler_argumentos, _pedir real)
metadata:
  type: project
---

Vistas na etapa 1 do plano atualizar-precos (2026-11-04):

- **Banco "de antes da v3" nos testes:** o `criar_banco` de agora já cria `items` com `preco_em`. Para simular o banco antigo, rode `S.criar_banco()` com `D.migrar` mockado e depois `ALTER TABLE items DROP COLUMN preco_em`. Grave os itens com o INSERT antigo (`COLUNAS_ITEM_V2` em `test_disparo.py`): o `S.upsert` novo quebra nesse esquema.
- **Campo novo no `GET /api/items`:** `testes/test_genero_servidor.py:28` (`CHAVES_ITEM`) fixa as chaves exatas do item. Com `preco_em` ficaram 24 falhas, e o arquivo não estava na etapa. O conserto é uma palavra.
- `test_genero_qa.py`: o `estado()` faz hash das colunas de `items` sem `preco_em`, e o `rebaixar_para_v1` também derruba `preco_em` (o banco real vai virar v3).
- **4 falhas do `test_genero_qa.py` que dependem dos dados** (já aparecem no HEAD f8e762a sobre um retrato do banco atual): `test_outras_abas_sao_todas_sem`, `test_aba_com_marcacao_mista...`, `test_distribuicao_da_perfumaria_pelo_get_items...` e `test_correcao_guardada_de_outra_aba...`. A base real passou para as 17 abas: "Casa e Decoração" ficou vazia e "Beleza e Cuidados" tem 661 itens com gênero.
- Mutante equivalente: `\d` no lugar de `[0-9]` no `_RX_PRECO_EM`, porque o `datetime.fromisoformat` já recusa dígitos fora do ASCII.
- A coluna `valor` de `config` tem afinidade TEXT: gravar o int 48 vira `'48'` e é lido como 48. Para testar um tipo estranho, use BLOB ou NULL.

Vistas na etapa 2 (trava no disparo, 2026-11-04):

- Com a trava, item sem `preco_em` é velho e some do `elegiveis`. Desde a S2 (preço mais de 5 min no futuro é velho), o `Base.item()` do `test_disparo.py` (herdado pelo `test_disparo_qa.py` e pelo `test_shopee_qa.py`) grava o marcador `PRECO_EM_RECENTE` (não é data) e o `Base.setUp` troca `D.preco_recente` por `preco_recente_do_teste`, que lê o marcador como `agora - 1 min` de cada chamada. Data fixa não serve: um teste usa relógios com mais de 168 h de distância. Item inserido por outro caminho num teste do disparo precisa de `preco_em` real, senão o teste falha "do nada".
- **Relógio fixo antes dos dados quebra com a S2:** teste que grava `preco_em` pelo `S.upsert` (relógio real) e chama `elegiveis`/`previa` com `T.SEGUNDA` (2026-11-02), ou que roda a trava sobre a cópia do banco real com `datetime(2026, 11, 3, ...)`, dependia de "futuro = fresco". Casos vistos: 2 no `test_shopee_qa`, 1 no `test_api_ofertas` (CA8 borda), 1 no `test_atualizar_precos_qa` (TravaNosDadosReais) e 3 no `test_genero_qa`. Para provar a causa em processo: `D.FOLGA_FUTURO_PRECO = timedelta(days=36500)` e rodar de novo.
- Não importe `test_disparo` e `test_atualizar_precos` no mesmo processo (cada um fixa o `ACHADINHOS_DB` antes do import; o segundo dá AssertionError "dados reais"). E o TMP do `test_atualizar_precos` some depois da primeira execução num runner improvisado: o 2º run dá FileNotFoundError no setUp (ruído do runner, não do código).
- `TS.pedir` manda `str`/`None` cru, sem `Content-Type` (415). Para `PUT /api/config/<chave>` com `"48"`, `null` ou `true`, passe `json.dumps(v).encode()` e o cabeçalho à mão.
- A prévia pela rota exige `numero_id` existente (400 "número deve ser um número inteiro" sem ele).
- `D.previa(..., info=)` devolve `{'recusados', 'preco_velho'}`: teste que compara o dict inteiro muda junto.
- O `config` do `TestRotas` do `test_disparo_servidor.py` não é limpo no `setUp`: chave nova gravada em teste precisa de `addCleanup`.

Vistas na etapa 4 (`atualizar_precos.py`, 2026-11-04):

- O `upsert` sem título devolve `'atualizado'` SEM gravar nada (só faz UPDATE `if tem`). Quem conta atualizações tem de barrar `ok` sem título antes (o lote conta como indisponível).
- "Nunca insere" tem duas guardas no lote: só grava id selecionado E `inserir=False`. O mutante `inserir=True` só morre com uma fonte falsa que exclui a linha entre a seleção e a gravação.
- Seleção do lote = itens cujo `preco_em` não é de hoje. Por isso um subTest que atualiza um item hoje tira esse item do próximo subTest: zere o `preco_em` entre eles.
- Ordem alfabética do unittest: um teste de subprocesso que cria `script.db` quebra o "não criou o banco" de outro. Use um banco por método (`self._testMethodName`).
- `urllib.error.HTTPError(url, código, msg, {}, io.BytesIO())` em teste: feche-o (`e.close()`) no código, senão aparece ResourceWarning do tempfile.

Etapa 2 de atualizar-precos-shopee-por-item (`fonte_shopee_item`, 2026-11-08):

- Teste de limite de argumento da `shopee` pelo `main()` engana: sem credencial no `env`, a saída 2 vem do `credenciais()` e não do argparse (o mutante "MAX_CHAMADAS_SHOPEE = 9999" sobreviveu). Teste os limites com `A.ler_argumentos(...)` + `assertRaises(SystemExit)`.
- Para exercitar o `_pedir` de verdade dentro do `TestShopee`: guarde `BUSCAR_ITEM = CS.buscar_item` no topo do módulo (antes de qualquer mock) e troque `CS.OPENER_API.open` por função que devolve `io.BytesIO(json)` (já serve de context manager); 429 é `HTTPError(CS.URL_API, 429, 'x', {}, io.BytesIO(b'{}'))`.
- O `destino` falso que lê a linha do item para provar "conferido antes de gravar" quebra (TypeError → saída 1) no teste do item excluído no meio da rodada: trate `linha is None`.
- Mutantes: copie também `coletar_amazon.py`, `buscas.json` e `testes/fixtures/amazon-busca.html` para a cópia; 19 mutantes da fonte rodam em ~1 min.

**How to apply:** nas etapas 2 a 6 desse plano e em qualquer migração nova. Relacionado: [[disparo-testes]], [[genero-testes]], [[cota-tmp]].

Rodada 1 de correção da Shopee por item (R1/S1, 2026-11-08):

- Marcar antes de parar, dentro da fonte: `yield 'tentado|<iid>', []` no `except` e depois `raise` puro (o gerador guarda a exceção entre o yield e a volta). O `atualizar()` grava o rótulo antes de pedir o próximo item.
- O "tentado" só funciona com o histórico de dias anteriores no `atualizar_precos_feitos.txt`. A prova do revisor (`prova_divergentes.py`) simula o "outro dia" com `open(A.FEITOS, 'w')`, que apaga esse histórico: lá a rodada 3 continua dando 1, e isso é esperado. Para simular a virada do dia, use `mock.patch.object(A, 'hoje', ...)`.
- `_rodar_ml` chama `M.sessao_do_ambiente()` fora do `try`: a exceção levantada ali vira "ERRO: <tipo>" com saída 1. Para parar com 2 sem tocar arquivo, devolva uma sessão falsa cujo `token()` levante `M.RefazerAutorizacao()`.
- Prova do /proc para vários comandos com um script só: `SCRIPT_PARADO` recebe módulo e função que viram a pausa (o leitor do Secret, depois do pop) e o módulo cujo `proteger_processo` vira False (controle). 12 subprocessos em ~1 s.
- Mutantes que rodam `test_shopee_por_item_qa.py` precisam de `README.md`, `CLAUDE.md` e `migrar_categorias.py` na cópia (TestDocumentacao). Sem eles, a cópia sem mutação já falha e os mutantes parecem mortos.
- Para o "antes" sem git (etapas sem commit), troque na cópia o trecho novo da fonte pelo antigo, guardado no relatório, e rode as suítes.
