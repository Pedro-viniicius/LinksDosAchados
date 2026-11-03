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

**How to apply:** ao mexer no `api_ofertas.py`, no `disparo.ordenar`/`elegiveis` ou nos testes deles. Relacionado: [[disparo-testes]], [[servidor-testes]].

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
