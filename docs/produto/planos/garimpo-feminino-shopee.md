# Plano técnico: garimpo feminino na Open API da Shopee (`tools/garimpo_feminino/`)
- Brief: docs/produto/briefs/garimpo-feminino-shopee.md (a seção "Ajustes obrigatórios" vale sobre a missão)
- **Corte do MVP e triagem dos achados:** docs/produto/briefs/garimpo-feminino-mvp.md (vale sobre este plano onde divergir: etapa 11 e estratégias 5 a 7 da etapa 15 ficam para depois)
- Data: 2026-11-06

## Objetivo e critérios de aceite
Montar uma ferramenta de terminal, isolada em `tools/garimpo_feminino/`, que o dono roda fase por fase. Ela garimpa por categoria os produtos femininos da Open API, gera links de teste com subIds e mede as conversões. Os agentes nunca rodam a ferramenta contra a API: eles leem log, banco e exports entre uma fase e outra.

- **CA1:** `docs/api_findings.md` traz limites medidos, não suposições. Cada número aponta uma linha da tabela `medicoes`.
- **CA2:** o mapa de categorias tem nome, classe (`feminina`, `mista` ou `fora`) e nicho, em `docs/mapa_categorias.md` e na tabela `categories`.
- **CA3:** o garimpo roda até saturar, ou a parada fica documentada por categoria.
- **CA4:** exports e relatório gerados. Retomada testada: o dono interrompe uma vez e retoma, e só a página em curso se repete.
- **CA5:** nenhum segredo em log, export, `garimpo.db` ou git.
- **CA6:** resumo final com o total de produtos, o total por nicho, onde a API limitou a cobertura e 3 próximos passos.
- **CA7:** cada fase que chama a API é um subcomando do dono, com:
  - teto de requisições, checkpoint, retomada e log em arquivo sem segredo;
  - saídas 0/1/2/3 no padrão do `coletar_shopee.py` (e 130 no Ctrl+C).
- **CA8:** o comportamento de produção do Etiqueta não muda.
  - `coletar_shopee.py`, `servidor.py` e `achadinhos.db` ficam intactos.
  - Os testes atuais passam, inclusive `test_shopee_qa.py:649`.
- **CA9:** os testes não usam rede (opener falso, proxies em `127.0.0.1:9`). Cobrem assinatura, checkpoint e retomada, dedupe, score de foco, saturação, teto e subIds.

## Contexto atual
- **Não existem** `tools/` nem `docs/produto/decisoes.md`. As decisões anteriores vêm dos planos `perfumaria-tres-lojas.md` e `atualizar-precos-shopee-por-item.md`.
- **`coletar_shopee.py`, o que dá para reaproveitar sem mudar:**
  - `URL_API` (fixa, `:65`), `ERRO_LIMITE` (`:67`), `TIMEOUT` (`:86`) e `MAX_RESPOSTA` de 2 MB (`:81`);
  - `Segredo` (`:91-107`), `assinar` (`:148-150`) e `autorizacao` (`:153-155`);
  - `codigo_de_erro` (`:279-292`), `credenciais()` com `pop` (`:314-323`) e `_ler_json` com teto (`:356-363`);
  - `SemRedirecionar` e `OPENER_API` (`:366-373`), `destino`/`conferir_dono` com `OPENER_CONFERENCIA` (`:400-420`);
  - `_numero`, `_inteiro`, `_texto` e `sem_acento` (`:165-200`), e as exceções (`:110-144`).
- **O que não serve ao garimpo:**
  - `buscar` (`:376-397`) só faz a consulta por keyword (`:70-74`).
  - `nos_da_resposta` corta em `POR_BUSCA = 30` (`:310`) e descarta `pageInfo`.
- **Importar o módulo** puxa `servidor` e `disparo` (`:53-54`). O import não abre banco: `servidor.py:28` só monta o caminho, e o resto do topo é constante (`:27-73`, `:188-424`). O `criar_banco`/`conectar` (`servidor.py:76-83`) só roda se for chamado.
- **Testes:**
  - `test_shopee_qa.py:647-650` conta um único `OPENER_API.open(` **dentro do `coletar_shopee.py`**.
  - O padrão de isolamento (proxies, `ACHADINHOS_DB` temporário, `pop` das credenciais antes do import) está em `test_coletar_shopee.py:31-45`.
- **Plano pendente** `atualizar-precos-shopee-por-item.md` (Decisão 1): acrescenta `CONSULTA_ITEM`, `POR_ITEM`, `corpo_item`, `_pedir`, `buscar_item`, `no_do_item` e `conferir --por-item`. Não renomeia nem muda nenhum dos nomes acima. O `_pedir` dele devolve a **lista de nós cortada em 30**, não a resposta.
- **`.gitignore`:** já ignora `*.db`, `*.db-wal`, `*.log` e `.env*`. Falta `exports/`.
- **Schema público** (só terceiros; a doc oficial fica no painel logado; **não verificado**):
  - Apify `viralanalyzer` e MCP `shopee-br-affiliate-mcp` confirmam `shopOfferV2`, `shopeeOfferV2`, `conversionReport`, `validatedReport`, `listItemFeeds` (FULL/DELTA) e `getItemFeedData` (`datafeedId`, `offset`, `limit`).
  - `generateShortLink` aceita até 5 subIds.
  - O relatório pagina até 500 por página. O `scrollId` vale 30 s e serve uma vez, e a 1ª consulta de cada relatório precisa de mais de 30 s de intervalo.
  - O MCP chama a categoria de `category_id`: o nome `productCatId` e o par `listType`/`matchId` ficam para a Fase 1.

## Abordagens consideradas
| Abordagem | Prós | Contras | Risco |
|---|---|---|---|
| A. Garimpo importa `coletar_shopee` sem mudá-lo. Tem **um** ponto de rede próprio (`cliente.pedir`) que usa o mesmo `CS.OPENER_API`, `CS.URL_API`, `CS._ler_json`, `CS.assinar` e `CS.credenciais` | Produção intacta (CA8). Não depende de plano não aprovado. Recebe a resposta inteira (`pageInfo`, outras operações, `limit` > 30) | Dois pontos de chamada no repositório, um por ferramenta. Usa um nome privado (`_ler_json`) | Baixo: teste estático no garimpo e teste de contrato dos nomes importados |
| B. Esperar o `_pedir` do plano pendente | Um só ponto de rede | O `_pedir` devolve nós cortados em 30: o garimpo exigiria uma 2ª mudança no `coletar_shopee.py`. Prende o garimpo a um plano sem aprovação | Alto (prazo e CA8) |
| C. Criar agora um `_post_assinado` genérico no `coletar_shopee.py` | Um ponto de rede | Mexe em produção e no mesmo arquivo da etapa 1 do plano pendente (conflito) | Médio |

**A** é a escolhida. A segunda chamada **não fica fora do padrão**: usa o mesmo objeto opener (sem redirect), a mesma constante de host (nunca parâmetro) e o mesmo teto de 2 MB. Convergir para um ponto único (`_pedir` chamando um `_post_assinado` usado pelos dois) fica como próximo passo, depois que o plano pendente fechar.

## Decisão
1. **Isolamento.** Código, testes e dados em `tools/garimpo_feminino/`.
   - Nada importa `S.conectar`, `S.criar_banco` nem `S.upsert`.
   - O banco é `garimpo.db` (o caminho muda com `ACHADINHOS_GARIMPO_DIR`, para teste). Logs em `logs/`, exports em `exports/`.
2. **Rede.** Só em `cliente.py`:
   - `pedir(cred, consulta, variaveis)` monta o corpo JSON (valores **só** em `variables`), assina com `CS.assinar`/`CS.autorizacao`, faz `CS.OPENER_API.open(Request(CS.URL_API, ...), timeout=CS.TIMEOUT)` e lê com `CS._ler_json`;
   - a conferência de link usa `CS.conferir_dono` ou, no `reconhecer`, `CS.destino` + `CS.dono_ok`, para separar "dono errado" de "conferência sem resposta" (S5);
   - ritmo de ~1 req/s: pausa de 1,0 s mais jitter de 0 a 0,25 s, ajustável no `achados.json` com piso de 0,5 s;
   - no 10030 ou HTTP 429, backoff `min(900, 30·2^k)·U(0,8; 1,2)` com até 5 tentativas. Depois disso, saída 3 com o checkpoint salvo. Cada evento de limite fica em `requisicoes`;
   - orçamento: `MAX_TOTAL_REQUESTS` (padrão 20.000, conta todas as requisições no `garimpo.db`) e `--max-req` por rodada. Os dois saem com 3.
3. **Checkpoint.** A tabela `consultas` guarda a chave (operação + variáveis canônicas sem `page`) e a `ultima_pagina`.
   - Cada página grava, numa só transação `BEGIN IMMEDIATE`: requisição, produtos, fontes e checkpoint.
   - Se a rodada cair, refaz no máximo a página em curso.
   - Um `flock` em `garimpo.lock` impede duas rodadas ao mesmo tempo (saída 2).
4. **Ciclo entre fases.** A medição vira configuração versionada e revisada:
   - `achados.json`: `limit`, teto de página, tipo do Int64, `listType` úteis, separador de subIds, ordem das estratégias e orçamento aprovado;
   - `categorias.json`: classe e nicho finais por `cat_id`;
   - o dev escreve esses dois arquivos a partir de `medicoes` e do mapa. A ferramenta os lê com validação estrita (tipos e faixas) e sai com 2 se estiverem inválidos.
5. **Links.**
   - Exporta só o `offerLink`/`shortLink` que passa em `S.eh_link_shopee`. O `productLink` fica só no banco, nunca como link de teste (regra do dono).
   - Confere o dono (`utm_source=an_18328801339`) de **cada** link de teste. No export, confere uma amostra: o 1º link e um por nicho, até 20. Uma falha aborta sem escrever (saída 1).
6. **Foco.** O score do brief é calculado sem acento, por palavra inteira (`\bmen\b` não pega "women").
   - Faixas (premissa P5): ≥ 5 alto, 2 a 4 médio, 0 a 1 neutro, < 0 ou categoria `fora` descartado.
   - Nada é apagado: só marcado.
7. **Saturação de uma categoria.** As últimas 5 consultas concluídas trouxeram, cada uma, menos de 2% de novos.
   - Dentro de uma consulta, a paginação para com `hasNextPage` falso, no teto de página medido ou depois de 3 páginas seguidas sem nenhum novo (ajustável).
8. **Excesso de engenharia evitado:**
   - sem paralelismo de requisições e sem fila;
   - sem cliente GraphQL genérico: as consultas são constantes;
   - sem raw_json nas conversões (lista de campos permitidos);
   - sem gerar links para o catálogo inteiro (só lote por categoria, nicho ou item).

## Esquema e contratos
`garimpo.db` (`PRAGMA user_version = 1`, criado de uma vez na etapa 2; mudança futura só aditiva):

| Tabela | Colunas principais |
|---|---|
| `products` | `item_id` PK (dedupe), `shop_id`, nome, `product_link`, `offer_link`, `image_url`, preços e taxas (REAL, do texto decimal), `sales`, `rating_star`, `commission`, `cat_l1/l2/l3`, `shop_name/type`, `period_start/end`, `raw_json`, `first_seen`, `last_seen`, `foco_score`, `foco` |
| `product_sources` | (`item_id`, `consulta_id`) PK, `pagina`, `posicao`, `visto_em` |
| `categories` | `cat_id` PK, `nivel`, `pai`, `nome`, `nome_origem` (`datafeed`, `titulos` ou `manual`), `classe`, `nicho`, `frequencia`, `saturada`, `bateu_teto`, `parada` (texto do motivo) |
| `shops` | `shop_id` PK, `nome`, `tipo`, `itens_femininos`, `catalogo_feito` |
| `campaigns` | `id` PK, nome, `commission_rate`, `period_start/end`, `raw_json` |
| `consultas` | `id` PK, `chave` UNIQUE, `fase`, `estrategia`, `cat_id`, `ultima_pagina`, `status` (`pendente`, `esgotada`, `teto`, `saturada` ou `erro`), `vistos`, `novos` |
| `requisicoes` | `id` PK, `consulta_id`, `pagina`, `em`, `operacao`, `http`, `codigo`, `ms`, `bytes`, `n_nos`, `novos` (sem cabeçalho nem corpo) |
| `medicoes` | `id` PK, `nome`, `valor_json`, `em` |
| `test_links` | `id` PK, `item_id`, `short_link`, `sub_ids`, `lote`, `criado_em`, `dono_ok` |
| `conversoes` | `chave` PK, `relatorio`, `purchase_time`, `item_id`, `shop_id`, `sub_ids`, `comissao`, `status` (só campos permitidos) |

```
# cliente.py
class Teto(CS.ErroColeta)                                   # orçamento total ou --max-req → saída 3
def pedir(cred, consulta: str, variaveis: dict, *, registrar) -> dict   # devolve "data"; LimiteAtingido/ErroApi/RespostaInvalida/Teto
# banco.py
def abrir(caminho) -> sqlite3.Connection; def travar(dir) -> ctx    # flock; outra rodada → ErroConfig
def gravar_pagina(con, consulta_id, pagina, nos, req) -> int        # novos; uma transação
# foco.py
def score(titulo, classe, nicho) -> tuple[int, str]; def slug(texto) -> str   # [a-z0-9]{1,20}
# motor.py
def paginar(con, cli, consulta, variaveis, *, teto_pagina, limit) -> dict      # retoma de ultima_pagina+1
def garimpar_categoria(con, cli, cat, estrategias) -> str                     # 'saturada' | 'teto' | 'esgotada'
# garimpo.py (CLI): conferir | reconhecer | mapa | piloto | garimpar | links | exportar | conversoes
#   cada subcomando vive em fase_<nome>.py com configurar(parser) e rodar(args, ctx); carregado sob demanda
```

`nichos.json` traz os 18 nichos do brief: `{slug, nome, sementes}`, 196 sementes em NFC, slug sem hífen (o hífen pode ser o separador dos subIds no relatório; **não verificado**).

SubIds: `fem`, `<slug do nicho>`, `<id L3>`, `t<AAAAMMDD>`, `<canal>`, cada um `[a-z0-9]{1,20}`. O canal sai de uma lista fixa (P3).

## Etapas
| # | Etapa | Arquivos | Verificação | Responsável | Grupo | Sensível | CAs |
|---|---|---|---|---|---|---|---|
| 1 | `cliente.pedir`: corpo canônico com valores só em `variables`; assinatura e Authorization por `CS.assinar` sobre os bytes exatos do corpo; host = `CS.URL_API`; ritmo; backoff do 10030/429 com jitter (relógio e `sleep` injetáveis); `Teto`; `registrar` sem cabeçalho. Testes: assinatura do corpo enviado, `full_url` fixa mesmo com variável de ambiente, 3xx não seguido, resposta > 2 MB recusada, backoff 5× e depois `LimiteAtingido`, teto total e por rodada, Secret marcador ausente em `repr`, exceção e `registrar` | `tools/garimpo_feminino/cliente.py`, `tools/garimpo_feminino/testes/test_cliente.py` | `python3 -m py_compile tools/garimpo_feminino/cliente.py && python3 tools/garimpo_feminino/testes/test_cliente.py -v` | dev | A | sim (credencial, assinatura, HTTP) | CA5, CA7, CA9 |
| 2 | `banco.py`: esquema completo acima, `gravar_pagina` numa transação, dedupe por `item_id` (`first_seen` fica, `last_seen` e campos atualizam), `product_sources`, checkpoint, `flock`. Testes: dedupe, retomada depois de exceção no meio da página (nada parcial), 2ª trava sai com erro, `user_version` 1 | `tools/garimpo_feminino/banco.py`, `tools/garimpo_feminino/testes/test_banco.py` | `python3 tools/garimpo_feminino/testes/test_banco.py -v` | dev | A | sim (concorrência) | CA4, CA9 |
| 3 | `foco.py` + `nichos.json`: `score`, faixas, exceção de Gestante & Maternidade, `slug`. Testes: cada termo do brief com e sem acento, `men` × `women`/`menina`, faixas nas bordas, slugs dos 18 nichos únicos em `[a-z0-9]`, sementes em NFC e sem `\|` | `tools/garimpo_feminino/foco.py`, `tools/garimpo_feminino/nichos.json`, `tools/garimpo_feminino/testes/test_foco.py` | `python3 tools/garimpo_feminino/testes/test_foco.py -v` | dev | A | não | CA9 |
| 4 | `garimpo.py`: argparse, despacho sob demanda, leitura estrita de `achados.json`/`categorias.json` com padrões, log em `logs/<sub>-<AAAAMMDD-HHMMSS>.log` (última linha `SAIDA=<n>`), saídas 0/1/2/3/130 como `coletar_shopee.py:606-627`, `CS.credenciais()` antes de qualquer banco, subcomando `conferir` (1 requisição + `CS.conferir_dono`). `.gitignore`: `tools/garimpo_feminino/exports/`, `tools/garimpo_feminino/logs/`, `tools/garimpo_feminino/garimpo.lock`. `testes/comum.py`: ambiente isolado e `ApiFalsa`. Testes: Secret ausente sai com 2 sem rede; marcador do Secret e `Signature=` nunca aparecem em log, banco ou stdout; `ACHADINHOS_DB` temporário continua inexistente depois de rodar; teste estático: um só `OPENER_API.open(` em `tools/garimpo_feminino/*.py` (no `cliente.py`), nenhum `urlopen(`, `build_opener(`, `http.client` ou `socket`, nenhum `conectar(`, `criar_banco` ou `upsert(`; contrato: os nomes de `CS` usados existem | `tools/garimpo_feminino/garimpo.py`, `tools/garimpo_feminino/testes/comum.py`, `tools/garimpo_feminino/testes/test_cli.py`, `.gitignore` | o teste da etapa e, com os proxies em `127.0.0.1:9`: `python3 testes/test_coletar_shopee.py -v` (83 OK), `python3 testes/test_shopee_qa.py -v` (65 OK), `python3 testes/test_ordens_qa.py -v` (28 OK) | dev | B | sim (credencial, HTTP) | CA5, CA7, CA8, CA9 |
| 5 | `consultas.py`: constantes GraphQL de `productOfferV2` (todos os campos do brief + `pageInfo`), `shopOfferV2`, `shopeeOfferV2`, `generateShortLink`, `conversionReport`, `validatedReport`, `listItemFeeds`, `getItemFeedData` e introspecção, e os leitores de `nodes`/`pageInfo` com tipos conferidos. Testes: nenhuma query muda com o valor das variáveis; leitores recusam formato errado | `tools/garimpo_feminino/consultas.py`, `tools/garimpo_feminino/testes/test_consultas.py` | `python3 tools/garimpo_feminino/testes/test_consultas.py -v` | dev | C | não | CA7, CA9 |
| 6 | `fase_reconhecer.py` (Fase 1): introspecção (→ `docs/schema.json`) ou sondas fixas; `limit` 20/50/100/500; profundidade de `page` em saltos; sobreposição dos `sortType`; `listType` 0 a 4 × `productCatId`; `isAMSOffer`/`isKeySeller`; Int64 como número e como texto; rajada de taxa em degraus (1, 2 e 4 req/s, até 120 requisições, para no 1º 10030); subIds com `-` e `_`; `listItemFeeds` FULL/DELTA + 1 página de `getItemFeedData`; 1 página de `shopOfferV2`, `shopeeOfferV2` e `conversionReport`. Grava `medicoes` e gera `docs/api_findings.md` só com valor medido ou "não medido". Mensagem de erro da API: `CS._texto` com até 300 caracteres, só no banco | `tools/garimpo_feminino/fase_reconhecer.py`, `tools/garimpo_feminino/testes/test_reconhecer.py` | `python3 tools/garimpo_feminino/testes/test_reconhecer.py -v` | dev | D | sim (HTTP, links gerados) | CA1, CA7, CA9 |
| 7 | `motor.py`: `paginar` com retomada, parada por `hasNextPage`/teto/3 páginas sem novo, `garimpar_categoria` com as estratégias 1 a 4 do brief (sortType 1 a 5; `listType` 4 e 3 com `matchId`; AMS/KeySeller; fatiamento keyword + `productCatId` com sementes e bigramas dos títulos, em bola de neve) e saturação. Testes: interromper na página 3 e retomar na 4; saturação nas bordas (1,9% e 2%); teto marca `bateu_teto` | `tools/garimpo_feminino/motor.py`, `tools/garimpo_feminino/testes/test_motor.py` | `python3 tools/garimpo_feminino/testes/test_motor.py -v` | dev | D | não | CA3, CA4, CA9 |
| R1 | **Dono:** `conferir` e depois `reconhecer` (comandos abaixo). O lead lê o log, `medicoes` e `docs/api_findings.md` | nenhum | `SAIDA=0` no log | dono + lead | — | sim (credencial) | CA1 |
| 8 | Achados: `achados.json` com os valores medidos (`limit`, teto de página, Int64, `listType` úteis, separador de subIds, pausa); `docs/api_findings.md` completado com a interpretação; ajuste de `consultas.py` se o schema divergir. Se `productCatId` não existir, **pare** e devolva ao arquiteto | `tools/garimpo_feminino/achados.json`, `tools/garimpo_feminino/docs/api_findings.md`, `tools/garimpo_feminino/consultas.py` | `python3 tools/garimpo_feminino/testes/test_cli.py -v` (lê o `achados.json` real) e `test_consultas.py` | dev | E | não | CA1 |
| 9 | `fase_mapa.py` (Fase 2): sementes × sortType 1, 2 e 5 × 2 páginas; trios [L1, L2, L3] com frequência; nome pelo datafeed ou pelas palavras frequentes; sugestão de classe (% de títulos com termo feminino) e de nicho (semente majoritária); expansão por `productCatId` até não surgir id novo; `docs/mapa_categorias.md` | `tools/garimpo_feminino/fase_mapa.py`, `tools/garimpo_feminino/testes/test_mapa.py` | `python3 tools/garimpo_feminino/testes/test_mapa.py -v` | dev | F | não | CA2, CA7 |
| 10 | `fase_links.py` (Fase 5): `--categoria`, `--nicho` ou `--item` (um dos três é obrigatório), `--canal`, `--max-links` (padrão 300). Lote de 10 por comissão em R$, 10 mais vendidos e 10 por nota com vendas mínimas, sem repetir loja. `originUrl` só `https://shopee.com.br/...`. Confere o dono de cada link antes de gravar em `test_links`. Testes: subIds válidos e recusados, lote sem loja repetida, dono errado não grava | `tools/garimpo_feminino/fase_links.py`, `tools/garimpo_feminino/testes/test_links.py` | `python3 tools/garimpo_feminino/testes/test_links.py -v` | dev | F | sim (link de afiliado, HTTP) | CA5, CA7, CA9 |
| 11 | `fase_conversoes.py` (Fase 7): `--desde`/`--ate`; `conversionReport` e `validatedReport` pelo `scrollId` (usado em menos de 30 s, uma vez); só campos permitidos; ranking por subId de nicho, categoria e produto em `exports/conversoes.csv` e `docs/conversoes.md`. Testes: `scrollId` expirado recomeça a consulta; campo fora da lista não é gravado | `tools/garimpo_feminino/fase_conversoes.py`, `tools/garimpo_feminino/testes/test_conversoes.py` | `python3 tools/garimpo_feminino/testes/test_conversoes.py -v` | dev | F | sim (relatório financeiro, HTTP) | CA6, CA7, CA9 |
| 12 | `fase_exportar.py` (Fase 6, sem API): recalcula o foco, gera `produtos_femininos.csv/.json`, `por_categoria/<nicho>/<cat>.csv`, `plano_de_testes.csv` e `RELATORIO.md` (seções do brief + "Piloto" a partir de `docs/piloto.md` + resumo do CA6). Célula que começa com `= + - @ \t \r` ganha `'` na frente; só link que passa no `eh_link_shopee`; amostra de dono antes de escrever | `tools/garimpo_feminino/fase_exportar.py`, `tools/garimpo_feminino/testes/test_exportar.py` | `python3 tools/garimpo_feminino/testes/test_exportar.py -v` | dev | F | sim (dono do link, injeção em CSV) | CA4, CA5, CA6 |
| R2 | **Dono:** `mapa`, e uma vez Ctrl+C no meio, depois rodar de novo (prova do CA4). O lead confere em `requisicoes` que só a página em curso se repetiu | nenhum | `SAIDA=0` | dono + lead | — | sim (credencial) | CA2, CA4 |
| 13 | `categorias.json` revisado (classe e nicho finais por `cat_id`) e `docs/mapa_categorias.md` final | `tools/garimpo_feminino/categorias.json`, `tools/garimpo_feminino/docs/mapa_categorias.md` | `python3 tools/garimpo_feminino/testes/test_cli.py -v` | dev + lead | G | não | CA2 |
| 14 | `fase_garimpar.py`, subcomando `piloto --categorias A,B,C` (grande, média e pequena): motor completo, requisições por categoria, únicos, saturação e rendimento por estratégia, estimativa total pela classe de tamanho; `docs/piloto.md`. Se passar do orçamento restante, imprime "PERGUNTE AO DONO" e sai com 0 | `tools/garimpo_feminino/fase_garimpar.py`, `tools/garimpo_feminino/testes/test_garimpar.py` | `python3 tools/garimpo_feminino/testes/test_garimpar.py -v` | dev | H | não | CA3, CA7 |
| R3 | **Dono:** `piloto`. O lead leva a estimativa ao dono; com o sim, o dev grava `orcamento_aprovado` e a ordem das estratégias no `achados.json` | `tools/garimpo_feminino/achados.json` | `SAIDA=0` e `docs/piloto.md` | dono + lead + dev | — | sim (credencial) | CA3 |
| 15 | `fase_garimpar.py`, subcomando `garimpar`: só começa se a estimativa couber em `orcamento_aprovado`; categorias femininas e mistas das folhas L3 para cima; estratégias 5 a 7 (lojas por `shopOfferV2` e catálogo das N lojas com mais itens femininos, `--max-lojas` padrão 200; datafeed FULL filtrado pelo mapa, se o R1 confirmou as colunas; `shopeeOfferV2`); grava a `parada` de cada categoria | `tools/garimpo_feminino/fase_garimpar.py`, `tools/garimpo_feminino/testes/test_garimpar.py` | idem 14 | dev | I | não | CA3, CA7 |
| R4–R6 | **Dono:** `garimpar` (várias rodadas, pode ir para o fundo), `exportar`, `links` dos nichos escolhidos e, depois do período de teste, `conversoes` | nenhum | `SAIDA=0` de cada um | dono + lead | — | sim (credencial) | CA3, CA4, CA6 |
| 16 | Docs: `tools/garimpo_feminino/README.md` (ordem das fases, comandos, saídas, como retomar); `README.md` com uma seção curta apontando para ele; `CLAUDE.md` com um bullet na lista de camadas (isolada, não grava no `achadinhos.db`, credencial como na coleta) e os testes na "Verificação" | `tools/garimpo_feminino/README.md`, `README.md`, `CLAUDE.md` | `rg -n "garimpo_feminino" README.md CLAUDE.md` com resultado | dev | J | não | CA7 |

Paralelismo:
- Os grupos são sequenciais: A, B, C, D, E, F, G, H, I e J.
- Dentro do A (1, 2 e 3), do D (6 e 7) e do F (9 a 12), as etapas não compartilham arquivo. O `testes/comum.py` nasce no B. As etapas 1 a 3 trazem o próprio isolamento no topo, como `test_coletar_shopee.py:31-45`.
- **Corte recomendado em entregas** (o plano é grande): entrega 1 = etapas 1 a 8 e o R1; entrega 2 = 9 a 14 e o R2/R3; entrega 3 = 15, 16 e o R4–R6. O que vem depois do R1 pode mudar com os achados: se uma premissa cair, o arquiteto revisa o plano.

## Fases que o dono roda, em ordem
Num terminal só para isso, na raiz do projeto. Nunca rode `set`, `declare -p`, `env` ou `printenv` antes do `unset S`.
```
read -rs S; ACHADINHOS_SHOPEE_SECRET="$S" ACHADINHOS_SHOPEE_APP_ID=<id> python3 tools/garimpo_feminino/garimpo.py <sub> [opções]; unset S
# em segundo plano (o log da ferramenta registra tudo e termina com SAIDA=<n>):
read -rs S; ACHADINHOS_SHOPEE_SECRET="$S" ACHADINHOS_SHOPEE_APP_ID=<id> nohup python3 tools/garimpo_feminino/garimpo.py garimpar >/dev/null 2>&1 & unset S
```
Ordem: `conferir` → `reconhecer` → (dev: `achados.json`) → `mapa` (com uma interrupção) → (dev: `categorias.json`) → `piloto` → (dono aprova o orçamento) → `garimpar` até sair 0 → `exportar` (sem credencial) → `links --nicho X --canal wpp` → dias de teste → `conversoes --desde ... --ate ...` → `exportar` de novo.

Não rode o garimpo junto com `coletar_shopee.py` ou `atualizar_precos.py shopee`: a cota do AppID é a mesma.

## Estimativa de requisições por fase (não medida; o R1 e o R3 corrigem)
| Fase | Conta | Requisições | Tempo a ~1,7 s/req |
|---|---|---|---|
| conferir | 1 busca (+1 conferência de link, fora da API) | 1 | segundos |
| 1 reconhecer | ~25 sondas de schema e parâmetros, ~15 de profundidade, ~20 de sort/listType, até 120 de taxa, ~10 de subIds/feeds/relatórios (`--max-req` 250) | 80 a 250 | 5 a 10 min |
| 2 mapa | 196 sementes × 3 sortTypes × 2 páginas = 1.176, mais a expansão de 100 a 300 ids × 2 páginas | 1.400 a 2.400 | 40 a 70 min |
| 3 piloto | grande 300 a 600, média ~150, pequena ~30 | 500 a 800 | 15 a 25 min |
| 4 garimpar | (150 a 250 categorias) × custo médio do piloto, mais lojas (até ~1.000) e o datafeed FULL (linhas ÷ 500) | provavelmente > 20.000; **o piloto decide e o dono aprova** | 6 a 15 h, em várias rodadas |
| 5 links | 1 por link (lote de 30 por categoria), mais 1 conferência de dono por link fora da API | 30 por categoria | ~1 a 2 min por categoria |
| 6 exportar | 0 (até 20 conferências de dono, fora da API) | 0 | segundos |
| 7 conversões | páginas de 500, por relatório e período | 2 a 20 | minutos (30 s entre relatórios) |

As fases 1 a 3 cabem em ~3.500 requisições, bem dentro dos 20.000. Se o FULL tiver colunas de categoria e uma contagem razoável, o datafeed pode sair mais barato que a busca por categoria: a decisão fica para o R1.

## Pontos para o seguranca
- **Rede:**
  - um só `OPENER_API.open(` no garimpo (`cliente.py`), com o mesmo objeto opener sem redirect, o host em constante e o teto de 2 MB do `coletar_shopee.py`;
  - teste estático reprova `urlopen`, `build_opener`, `http.client` e `socket`;
  - o `originUrl` do `generateShortLink` só aceita `https://shopee.com.br/`.
- **Secret:**
  - `CS.credenciais()` (com `pop`) e `Segredo`;
  - nunca vai para `argv`, log, banco ou export; o Authorization (assinatura reutilizável dentro da janela do timestamp) nunca é registrado;
  - rodada longa em segundo plano: o Secret continua legível em `/proc/<pid>/environ` para o mesmo usuário enquanto o processo vive (o `pop` não apaga ali). É uma máquina de uma pessoa só; avalie se é risco aceito.
- **Texto da API:** mensagem de erro só no `reconhecer`, saneada e cortada em 300. Títulos vão para CSV com a defesa contra fórmula e para Markdown com `|` escapado.
- **Link do dono:** conferido em cada link de teste e numa amostra no export. O export nunca usa o `productLink`.
- **Conversões:** só campos permitidos, sem `raw_json` (pode haver dado de pedido). Ficam no `garimpo.db` e em `exports/`, fora do git.
- **Cota e conta:** ritmo, backoff, teto por rodada e total, `flock`. A rajada de taxa do R1 tem teto de 120 requisições e para no 1º 10030 (P4).
- **Isolamento:** testes provam que o `achadinhos.db` não é aberto nem criado.

## Riscos e como reverter
- **Bloqueio temporário do AppID** (rajada ou garimpo longo) para também a coleta do Etiqueta.
  - Mitigação: teto, backoff e P4.
  - Reverter: parar a ferramenta (Ctrl+C ou `kill`) e esperar; o checkpoint fica.
- **A API não tem `productCatId` nem `listType`/`matchId`.** A espinha dorsal cai: a etapa 8 para e o plano volta ao arquiteto (keyword + loja + datafeed).
- **Teto de paginação baixo.** Vira `bateu_teto` e o fatiamento por keyword entra. O relatório declara a cobertura parcial (CA6).
- **Resposta acima de 2 MB** (introspecção ou feed de 500 linhas). Vira `RespostaInvalida`, medido no R1; baixar o `limit` no `achados.json`, sem subir o teto.
- **O plano pendente entra depois.** Ele não toca nenhum nome importado. O teste de contrato da etapa 4 falha se um deles mudar.
- **Reverter tudo:** sem migração no `achadinhos.db` e sem mudança no código de produção. Apagar `tools/garimpo_feminino/` e as 3 linhas do `.gitignore`. O `garimpo.db` é descartável.
- **Risco aceito pelo dono (06/11, depois das etapas 1 a 7):** "Tire a revisão da Shopee, estou disposto ao risco" (texto corrigido na digitação). O lead encerrou a revisão.
  - O `revisor` entregou MUDANÇAS NECESSÁRIAS e a `seguranca`, CORRIGIR ANTES DO RELEASE. O `qa` foi interrompido sem relatório: seu `test_qa_entrega1.py` ficou incompleto e não vale como prova. As correções não tiveram rodada 2 de revisão.
  - Depois, o dono pediu "o que for melhor" para o MVP, e o lead fez a triagem em `docs/produto/briefs/garimpo-feminino-mvp.md`. Corrigidos: R1 a R5, R9, S1, S2, S4, S5, S6 e a parte combinada de S8 e S9.
  - Abertos, como risco aceito: R6, R7, R8, S3, S7 e o resto de S8 e S9.
  - Lido como sim à P4 (a rajada do `reconhecer`, que não tem como ser desligada; o `--refazer` não a repete sem `--refazer-taxa`). Os termos da Open API seguem não lidos.
- **Requisitos para as etapas 14 e 15, vindos da correção do R2:**
  - portão de credencial no início do `piloto` e do `garimpar`, porque um Secret errado que responda código com HTTP 200 marcaria as consultas como `erro` para sempre;
  - um jeito de limpar esses `erro`.

## Perguntas em aberto e premissas adotadas
- **P1:** se a estimativa do piloto passar de 20.000, o dono aprova um novo teto? O brief manda perguntar, e a premissa é parar até a resposta.
- **P2:** versionar `achados.json`, `categorias.json`, `docs/*.md`, `schema.json` e `RELATORIO.md`?
  - Premissa: sim, porque não têm segredo e o `RELATORIO.md` não traz link.
  - O banco, os logs e os exports ficam fora do git.
- **P3:** quais canais vão no subId5? Premissa: `wpp`, `ig`, `tt`, `fb` e `outro`.
- **P4:** o dono aceita a rajada de medição até o 10030? Ela pode travar a cota por um tempo. Premissa: sim, com teto de 120 requisições e fora do horário de coleta. Com um não, o limite real sai só dos 10030 naturais.
- **P5:** faixas de foco: ≥ 5 alto, 2 a 4 médio, 0 a 1 neutro, < 0 ou `fora` descartado. Nenhuma está no brief.
- **P6:** catálogo de lojas limitado às 200 com mais itens femininos (`--max-lojas`).
- **Premissas:**
  - Os docs ficam em `tools/garimpo_feminino/docs/`, como na Fase 6 do brief.
  - O dedupe é por `itemId`, como pede o brief. O `shop_id` fica em coluna.
  - A data dos subIds é a do dia da geração.

## ADR
**Ferramenta isolada em `tools/` com banco próprio e um 2º ponto de rede da Shopee.**
- **Contexto:** o garimpo é exploratório, longo e com volume muito acima da coleta. O plano que unificaria o ponto de rede ainda não foi aprovado, e o `_pedir` dele não devolve a resposta inteira.
- **Decisão:** ver abordagem A.
  - Pasta nova, `tools/garimpo_feminino/`, com SQLite próprio e configuração medida versionada.
  - Reaproveita do `coletar_shopee.py`, sem mudá-lo: assinatura, credencial, host, opener e leitor com teto.
  - O módulo tem um único ponto de rede, com o mesmo opener.
- **Consequências:**
  - Há dois pontos de chamada no repositório, cada um coberto por teste estático no próprio módulo.
  - Depende de um nome privado (`_ler_json`), coberto pelo teste de contrato.
  - Convergir para um `_post_assinado` comum fica como próximo passo depois do plano `atualizar-precos-shopee-por-item`.
- **Alternativas rejeitadas:** B e C (tabela acima).
