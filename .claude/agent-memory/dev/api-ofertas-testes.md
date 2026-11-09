---
name: api-ofertas-testes
description: Armadilhas do api_ofertas.py, da v1 no servidor.py e dos testes deles (paridade com disparo.ordenar, afinidade TEXT do sqlite, mutantes equivalentes, medição no banco real)
metadata:
  type: project
---

Vistas em 2026-11-03, na etapa 1 do plano api-achadinho-turbo:

- **`disparo.elegiveis` não tem ORDER BY:** com `cat IN (...)` no WHERE o sqlite lê pelo `ix_items_cat` (EXPLAIN: `SEARCH items USING INDEX ix_items_cat`), então a entrada do `ordenar` sai por categoria e os empates de `posicao` mudam de lugar. A API passa a entrada por id (`ORDER BY id`); o oráculo de paridade tem de fazer `sorted(elegiveis(...), key=id)` antes do `D.ordenar`. O mutante "sem ORDER BY id" só morre com teste de duas categorias e `posicao` empatada.
- **Afinidade TEXT:** inserir `titulo=12345` numa coluna TEXT grava `'12345'` (str). Para testar "tipo estranho no banco", use BLOB (`b'...'`).
- `float('9'*400)` é `inf` e `json.dumps` grava `Infinity` (JSON inválido): `preco_num`/`nota` com dígitos demais precisam de `math.isfinite`. Teste com `json.dumps(r, allow_nan=False)`.
- **Conversões que levantam (R1 da rodada 2):** `D.contagem('9'*400+' mil')` dá OverflowError (inf*1000) e `D.pct`/`contagem` com mais de ~4.300 dígitos dão ValueError (limite do int). Uma linha assim derrubava toda a v1, porque as rotas varrem a tabela. `oferta()` captura as duas exceções e devolve None. O `coletar_amazon.py` não aplica o teto de 200 caracteres, então o banco pode ter isso.
- Mutantes equivalentes conhecidos: `tem_dados != 1` em `oferta()` (o SQL já filtra; prove chamando `A.oferta` direto) e o teto `MAX_PARES` (pedido acima dele já cai em outra regra; prove pela mensagem "demais").
- Medição sem risco: `sqlite3.connect('file:achadinhos.db?mode=ro', uri=True)` + `A.rota(...)` direto; em 2026-11-03 saem 7.998 de 8.380 itens em cerca de 0,5 s, com `total_changes == 0`.
- O `parse_qsl` padrão descarta `q=` vazio (`keep_blank_values=False`): os testes usam `keep_blank_values=True`, e a etapa 2 do servidor precisa fazer o mesmo.

Vistas na etapa 5 do plano genero-nas-categorias (2026-11-03):

- **Campo novo na v1 quebra asserts de chave exata em 3 arquivos:** `CAMPOS_OFERTA`, o dict do `filtros()` e o de categorias em `test_api_ofertas.py`; a lista de chaves da oferta (`test_ca1_ofertas_com_token_da_200_no_formato`) e o dict de categorias em `test_api_ofertas_servidor.py`; o `deepEqual` de categorias em `api_ofertas.test.mjs`. O `test_api_ofertas_qa.py` não fixa nada disso. Também a lista branca de imports (`test_ca9_modulo_nao_importa_servidor`).
- **Módulo novo importado pelo `api_ofertas.py`:** o `TestAmbienteDeTesteIgnoraTokenReal` (`test_api_ofertas_servidor.py`) copia os `.py` para um diretório temporário; sem o módulo novo na tupla, o servidor da cópia derruba a conexão (`RemoteDisconnected`).
- `MAX_PARES` com `genero` é 32; o banco real estava em `user_version` 1 (sem `generos_manuais`) e a v1 continuou em ~0,5 s.

**How to apply:** ao mexer no `api_ofertas.py`, no `disparo.ordenar`/`elegiveis` ou nos testes deles. Relacionado: [[disparo-testes]], [[servidor-testes]], [[atualizar-precos-testes]].

Vistas na etapa 3 de atualizar-precos (`preco_em` na v1, 2026-11-04):

- **`test_api_ofertas_qa.py::DadosReais` lê um retrato do banco real direto, sem `criar_banco`:** se o banco real ainda não migrou, coluna nova de `items` dá `IndexError` no `row['coluna']` e derruba o `setUpClass`. Por isso o `api_ofertas` tolera banco sem `preco_em` (`try/except IndexError` e `PRAGMA table_info` antes de pôr a coluna no SQL).
- **O `D.elegiveis` tira preço velho desde a etapa 2:** oráculo de paridade com itens sem `preco_em` volta vazio. Em `test_api_ofertas.py`, o `OrdensDoDisparo.gravar` põe `preco_em=hora(AGORA)`. O `ParidadeComODisparo` do qa quebra pelo mesmo motivo (arquivo do qa).
- **`ServidorDadosReais` falha com coleta real rodando** (`ps` mostra `coletar_amazon.py`): itens gravados há menos de 60 s ficam na folga da ordem `atualizacao` e faltam de 1 a 18 contra o `/categorias`. Não é regressão.
- **`curl` respeita `http_proxy`:** com os proxies mortos exportados, o `curl` para `localhost` dá `000`. Exporte `no_proxy=localhost,127.0.0.1` antes.
- Mutante equivalente para os testes de saída: tirar o `AND preco_em >= ?` do SQL (o `_casa` decide). Só morre com espião em `A.oferta` contando as chamadas.

Vistas na etapa 2 (v1 no servidor.py, 2026-11-03):

- **`test_servidor.py::test_ca6_antigo_rotas_do_fonte_sem_proxy_de_imagem`** lista TODO literal `'/api/...'` do `servidor.py` e exige só as 5 rotas antigas. Rota nova de módulo mora no módulo (`disparo.PREFIXO`, `api_ofertas.PREFIXO`), importado sob demanda; no servidor ficam só sufixos sem `/api/`.
- O `fetch` do Node 22 (undici) manda `sec-fetch-mode: cors`, `accept-language: *`, `user-agent: node`, e NÃO manda `Origin` nem `Sec-Fetch-Site` (nem no POST). Barrar `Sec-Fetch-Mode` derrubaria o Turbo.
- Linha de requisição malformada: o `send_error` loga com `HTTPStatus` em `args[0]` (o filtro descarta), mas o `log_request` seguinte loga a `requestline` crua. Redação do log tem de olhar a linha crua, não o `self.path`.
- O `http.server` já tira os espaços das pontas do valor de cabeçalho: `.strip()` no valor inteiro é mutante equivalente; o que importa é o `strip` depois do `partition(' ')` (`Bearer   tok`, RFC 7235 `1*SP`).
- Mutantes numa cópia fora do git: o teste `git check-ignore` falha sempre; filtre essa falha antes de dizer "MORTO" (três mutantes pareciam mortos só por ela).
- Token nos testes: `secrets.token_urlsafe(32)` e asserções com `assertFalse(token in x, 'msg fixa')`; `subTest` com o token trocado por `<token>`, senão a falha imprime o segredo.

Vistas na etapa 3 (docs, 2026-11-03):

- **Conferir os `curl` da doc de verdade:** extraia as linhas `curl -s` do README e do contrato com um script (junte as continuações `\`), troque a porta por uma de teste e rode contra cópia do banco com token temporário no scratchpad. Com `-w` e `-o out.json` o token nunca aparece. Compare as chaves de uma oferta real com a tabela de campos do contrato (script de 5 linhas; `keys == docs`).
- O `curl -G -d limite=2 --data-urlencode cursor=...` gera a query certa; `urllib.request` do Python quebra com acento na URL (`UnicodeEncodeError`), use `quote`.
- `proximo` na ordem `atualizacao` só é `null` na página vazia: em `loja=shopee&limite=200` (536 ofertas) são 4 chamadas, a última com 0.
- Linha de requisição malformada (`HTTP/9`, 4 palavras): o `http.server` responde no estilo HTTP/0.9, SÓ o corpo, sem linha de status. Teste por `b'Error code: 400' in resposta`, não por `startswith(b'HTTP/1.0 400')`.
- Rodada 2 (R4): o `ambiente()` de `test_servidor.py` aponta `ACHADINHOS_API_TOKEN_ARQUIVO` para `SEM_TOKEN_API` (nunca existe); os `.mjs` que sobem o servidor põem `path.join(s.dir, 'sem-api-token.txt')`. Teste novo que sobe `servidor.py` precisa disso (há guarda estática em `test_api_ofertas_servidor.py`).
- Com o `qa` rodando a suíte dele em paralelo, `test_api_ofertas_qa.py` deu 4 erros transitórios; isolado passou. Rode de novo antes de relatar.

Vistas na correção Q1 (validade padrão na v1, 2026-11-08):

- **Desde Q1 a v1 sem `preco_max_horas` aplica `D.validade_horas(con)` no `listar`** (o `filtros()` continua devolvendo `None`). Todo teste que grava item precisa de `preco_em` recente: `Base.gravar` e `TS2.inserir` já trazem o padrão (AGORA / relógio real). Teste com relógio injetado diferente do `AGORA` (ModeloDoCursor, DEPOIS=2030) tem de passar `preco_em` relativo a esse relógio; senão a lista vem vazia sem erro.
- O fixture do `ServidorApi` mantém o ML com `preco_em` de 2020 porque o `PeloHttp` do `test_api_ofertas_validade_qa.py` conta com isso; `TestApiLigada.ml_recente()` troca o preço no banco só dentro do bloco.
- Cópia do banco real: pôr `preco_em` relativo ao relógio do teste e `config.preco_validade_horas='168'` na cópia (a config real pode ter prazo curto). `test_genero_qa.V1NadaQueExistiaMuda` e `test_atualizar_precos_qa.V1PrecoMaxHorasNosDadosReais` têm falhas anteriores e sem relação: foto grande (`_AC_SL1000_` x `_AC_UL320_`, o "código antigo" não a tem) e folga de 60 s com dados reais depois do `agora` fixo.
