# Plano técnico: gênero (público) nas categorias e melhoria de UX
- Brief: não há. Faz o papel dele o pedido literal do dono, repassado pelo lead em 2026-11-03: "Coloca uma separação de masculino e feminino também nas categorias que existem coisas para os dois sexos, melhore o UX/UI". A spec de UI está em `docs/produto/specs/genero-e-ux.md` (Parte A: gênero; Parte B: M1 a M8).
- Data: 2026-11-03
- Não há `docs/produto/decisoes.md`. Este plano segue os planos `disparo-automatico.md` (migração por `user_version`), `api-achadinho-turbo.md` (contrato v1 só cresce) e `perfumaria-tres-lojas.md`.

## Objetivo e critérios de aceite
Separar as ofertas por público (feminino, masculino, unissex) onde isso faz sentido, e usar essa separação na página principal, nas regras do disparo e na API v1. Junto, aplicar a parte da melhoria de UX que o dono aprovar.

- **CA1 (classificação):** todo item tem `genero` ∈ `feminino`, `masculino`, `unissex` ou `sem`. A regra é determinística, nesta ordem: correção manual, depois o título, depois uma linha de produto conhecida no título, depois o termo `busca`. Item de aba fora de `ABAS_COM_GENERO` é sempre `sem`. Na base de 2026-11-03, a aba "Perfumes e Perfumaria" fica perto de F 696, M 966, U 178 e sem 1.211 (±3%).
- **CA2 (item novo):** item que entra por qualquer caminho (coleta da Amazon, da Shopee, do ML ou link colado no site) já sai classificado na próxima leitura, sem passo extra.
- **CA3 (página principal):** atende os CA-V1 a CA-V12 da spec. O controle "Público" só aparece em aba com gênero e tem contagens. O selo aparece só em "Todos".
- **CA4 (correção manual):** pelo site, o dono troca o gênero de um item (os 4 valores ou "Automático"). A correção persiste, vale para a tela, o disparo e a API, e só a origem local grava. Ninguém edita o banco à mão. Depende da P2.
- **CA5 (disparo):** a regra ganha `generos` (lista; vazia quer dizer "todos"). O filtro vale só para itens de abas com gênero; as outras categorias marcadas passam inteiras. Regra gravada antes elege exatamente os mesmos itens. O contador, a prévia e o aviso de "nada casa" levam o filtro em conta.
- **CA6 (API v1):** cada oferta ganha `genero`. `/api/v1/ofertas` aceita `genero` (repetível, valores dos 4; valor inválido ou repetido dá 400). `/api/v1/categorias` traz `generos` por categoria. Nenhum campo, parâmetro ou erro que já existe muda, a `versao` continua 1 e o contrato fica atualizado.
- **CA7 (migração):** `PRAGMA user_version` 2, só aditiva, idempotente e atômica. Os dados ficam intactos e o código antigo continua rodando sobre o banco migrado.
- **CA8 (UX geral):** os itens da Parte B da spec aprovados pelo dono entram nesta entrega, conforme o corte da P4. Nenhuma lógica de dados muda neles.
- **CA9 (testes):** há testes do classificador com títulos reais, da migração, da rota de correção e dos filtros (front, disparo e API). As 18 suítes Python, as 4 Node e as páginas do front continuam passando.

## Contexto atual
- **Itens:** `items` tem `cat`, `busca` e o `titulo` como coluna (`servidor.py:73-85`). `linha_para_item` monta o JSON do `/api/items` (`servidor.py:99-102`), que entrega **todos** os itens ao front (`servidor.py:659-663`). O front filtra tudo no cliente em `filtrada()` (`index.html:518-524`) e monta abas, contagens e o select de buscas em `render()` (`index.html:526-545`).
- **Escritas:** o `upsert` é usado pelo POST, pelo `coletar_amazon.py:88` e pelo `coletar_shopee.py:371`. O `coletar_ml.js` grava por POST e PATCH. O `migrar_categorias.py` e o `classificar_lista.py` regravam `cat` e `busca`. Gênero derivado na leitura não precisa de gancho em nenhum desses caminhos.
- **Esquema:** `disparo.migrar` (`disparo.py:97-119`) é o único dono do `user_version`. Hoje está na versão 1 (`disparo.py:27`, `ESQUEMA_V1` em `:28-48`) e é chamado por `servidor.criar_banco` (`servidor.py:90-91`), que também roda nas coletas. O banco real está em `user_version` 1 (lido em `mode=ro`).
- **Disparo:** `validar_regra` (`disparo.py:218-287`), `PADRAO_REGRA`, `CAMPOS_REGRA` e `LISTAS_REGRA` (`:291-299`), `elegiveis` (`:720-751`) e `AVISO_FILTROS` (`:957`). No front, `contarItens` (`index.html:693-703`) e `htmlFormRegra`/`lerFormRegra` (`index.html:1173-1244`).
- **API v1:** `PARAMETROS`, `REPETIVEIS` e `MAX_PARES` em `api_ofertas.py:26-29`, `oferta()` em `:58-113`, `filtros()` em `:122-187`, `_casa()` em `:190-197` e `categorias()` em `:244-255`. O contrato (`docs/produto/referencias/api-ofertas.md:53`) diz que campo novo pode entrar na v1 e que o consumidor ignora o que não conhece.
- **CORS:** só as rotas de `ROTAS_ML` (`servidor.py:44`) aceitam origem do ML. Uma rota `/api/items/<id>/genero` fica fora dela e recebe 403 dessas origens sem nenhum código novo.
- **Testes que fixam a versão 1:** `testes/test_disparo.py:150,173,182,204` e o teste "versão maior" (`:209`, que usa 2) precisam mudar.

### Medição no banco (`mode=ro`, 8.381 itens, script no scratchpad)
| Aba | Itens | Título com marca de gênero | Leitura |
|---|---|---|---|
| Perfumes e Perfumaria | 3.051 | 1.333 (M 667, F 534, U 88, M+F 30...) | Vale separar |
| Black Friday \| Eletrônicos | 3.110 | 25, quase todos smartwatch "Masculino e Feminino" | Não vale |
| Casa e Decoração | 1.117 | 7, todos falsos ("Donna" é linha de louça, "Lady" é modelo de sofá) | Não vale |
| Eletrodomésticos | 1.103 | 0 | Não vale |

Na Perfumaria, o termo de busca sozinho não basta. Em "Perfume feminino importado" há 1 masculino e 3 "masculino e feminino". "Natura Essencial" tem 28 M e 23 F, "Natura Kaiak" tem 45 M e 9 F, e "212 VIP" tem 19 M e 17 F. Por isso o título manda e a busca é só o último recurso. Origem do resultado: título 1.364, linha 212, busca 264, sem 1.211. Os "sem" se concentram em hidratante, óleo, sabonete, perfume para cabelo e infantil, que de fato não têm gênero. Uma classificação completa leva cerca de 66 ms para 8.381 itens (Python 3.14).

## Abordagens consideradas
| Abordagem | Prós | Contras | Risco |
|---|---|---|---|
| **A. Derivado na leitura + tabela `generos_manuais` para correções** | Não muda `items`, sem backfill. Item novo e mudança de regra valem na hora. Um módulo puro, testável. | Custa ~66 ms por leitura completa. A mudança de regra não mexe em `atualizado_em` (o cursor do Turbo não vê). | Baixo |
| B. Coluna `genero` em `items`, gravada na escrita, com backfill | Filtro em SQL | Gancho em 6 caminhos de escrita (upsert, PATCH, 3 coletas, 2 scripts). Backfill a cada ajuste de regra. `ALTER` em `items` quebra testes que comparam linhas inteiras (`test_disparo.py:158-174`). | Médio: gênero desatualizado em silêncio |
| C. Gênero por termo em `buscas.json` | Simples | Errado nos números acima (termos de marca são mistos). Muda o formato copiado no `coletar_ml.js`. | Alto |

## Decisão
**A.** Um módulo novo, `genero.py`, só com a biblioteca padrão e sem importar `servidor` nem `disparo` (mesmo padrão do `disparo.py`). Ele é usado por `servidor.py`, `disparo.py` e `api_ofertas.py`. Justificativa do arquivo novo: a regra precisa ser idêntica nos três consumidores, e o `disparo.py` já tem 1.258 linhas de outro assunto.
- **Abas com gênero:** `ABAS_COM_GENERO = ('Perfumes e Perfumaria',)` só no Python. O front não guarda a lista; segue a regra da spec: a aba tem gênero quando seus itens têm 2 valores ou mais. Fora dessas abas tudo é `sem`, então o resultado é o mesmo.
- **Unissex:** vale para unissex declarado e para título com masculino e feminino juntos (kits "Feminino e Masculino"). Fica separado de feminino e masculino.
- **Correção manual:** fica na tabela `generos_manuais` e entra por rota própria, `PUT /api/items/<id>/genero`. O PATCH, que é contrato do ML, não muda. Item que sai de uma aba com gênero volta a `sem`, mas a correção fica guardada e vale de novo se ele voltar.
- **Disparo:** `generos` é uma lista (padrão `[]`, que quer dizer todos), como `lojas`. A UI da spec manda `[]` ou um valor (rádio). Se o dono pedir "Feminino + Unissex" depois, só a tela muda.
- **API v1:** o filtro `genero` é exato. Quem pede `genero=feminino` não recebe geladeira; para combinar, o cliente usa `cat`. Já no disparo, o filtro vale só nas abas com gênero (CA5). A diferença é de propósito: na regra a tela explica isso; numa API, filtro que se ignora em silêncio confunde.

## Esquema e contratos
**Migração v2** (em `disparo.migrar`, mesma transação `BEGIN IMMEDIATE`; com v0 roda a v1 e depois a v2):
```sql
CREATE TABLE IF NOT EXISTS generos_manuais (item_pk INTEGER PRIMARY KEY,
  genero TEXT NOT NULL CHECK (genero IN ('feminino','masculino','unissex','sem')),
  atualizado_em TEXT NOT NULL);
ALTER TABLE regras ADD COLUMN generos TEXT NOT NULL DEFAULT '[]';
```
`VERSAO_ESQUEMA = 2`. Nada destrutivo. Banco já em v2 ou mais não é tocado.

**`genero.py`:**
```python
GENEROS = ('feminino', 'masculino', 'unissex', 'sem')
ABAS_COM_GENERO = ('Perfumes e Perfumaria',)
def classificar(cat, busca, titulo) -> tuple[str, str]   # (genero, origem); origem: 'titulo' | 'busca' | ''
def manuais(con) -> dict[int, str]                      # {} se a tabela não existe (banco sem migrar)
def do_item(item_pk, cat, busca, titulo, manuais) -> tuple[str, str]   # origem 'manual' quando há correção e a aba tem gênero
def definir_manual(con, item_pk, genero_ou_None, agora_iso) -> None    # None apaga (volta ao automático); sem commit
```
Regras do `classificar`. O texto passa por NFKD, perde os acentos e passa por `casefold`, e as palavras são casadas com `\b`.
1. Se a `cat` está fora de `ABAS_COM_GENERO`, devolve `sem`.
2. **Título.** Se casa U, é `unissex`. Se casa M e F, é `unissex`. Só M é `masculino`. Só F é `feminino`.
   - U: `unissex|unisex|unissexo|ambos os sexos`
   - M: `masculin[oa]s?|masc|homens?|homme|men|man|uomo|hombre|male|boys?|menino|for him|pour lui`
   - F: `feminin[oa]s?|fem|mulher(es)?|women|woman|femme|donna|mujer|lady|girls?|menina|for her|pour elle`
3. **Linha no título** (o passo 2 vem antes, então "Lady Million" sai F). `invictus|sauvage|malbec|million|pos[- ]?barba|barbear|barber` dá `masculino`, `la vie est belle` dá `feminino` e `ck one` dá `unissex`. Origem `titulo`.
4. **Busca**, com as palavras do passo 2. Origem `busca`.
5. Se nada casou, devolve `sem`.

Casos reais que os testes precisam fixar: "212 Men NYC" dá M. "Lady Million Paco Rabanne Feminino" dá F. "Natura Kaiak Feminino" sob a busca "Natura Kaiak" dá F. "Kit Perfumes Feminino e Masculino" dá U. "Perf. Fem. EDP" dá F. "Armani Code Masc" dá M. "LANCÔME LA NUIT TRESOR" sob "Paco Rabanne One Million" dá sem. "Olympea EDP" sob "Perfume feminino importado" dá F com origem busca. "Hidratante Corporal ..." sem marca dá sem. Smartwatch "Masculino Feminino" em Eletrônicos dá sem.

**HTTP (`servidor.py`):**
- Cada item de `GET /api/items` (e a resposta do PATCH) ganha `"genero"` e `"genero_origem"` (`titulo`, `busca`, `manual` ou `''`). O `manuais(con)` é lido uma vez por pedido.
- `PUT /api/items/<id>/genero` com o corpo `{"genero": "feminino"|"masculino"|"unissex"|"sem"|null}`, onde `null` volta ao automático. Responde 200 com o item (`linha_para_item`). Dá 404 para item inexistente e 400 para valor fora da lista, corpo que não seja objeto ou `cat` fora de `ABAS_COM_GENERO` ("esta categoria não separa por público"). Os 415 e 413 vêm do `corpo()`. A rota grava `items.atualizado_em = agora()`, para o cursor da v1 ver a mudança. Só a origem local chega aqui: o `bloquear()` recusa o ML, porque a rota está fora de `ROTAS_ML`.
- `DELETE /api/items/<id>` passa a apagar também a linha de `generos_manuais`.

**Disparo:** `generos` entra em `CAMPOS_REGRA`, `LISTAS_REGRA` e `PADRAO_REGRA` (`[]`). A validação aceita de 0 a 4 valores de `GENEROS`, sem repetir, e normaliza na ordem de `GENEROS`. Em `elegiveis`, com `generos` preenchido, um item de aba com gênero só passa se `do_item(...)[0] in generos`; os das outras abas passam. O `AVISO_FILTROS` passa a citar "público". As assinaturas de `_item`, `ordenar`, `link_da_loja_ok` e `urls_da_mensagem` não mudam, porque o `api_ofertas.py` depende delas.

**API v1:**
- `PARAMETROS` e `REPETIVEIS` ganham `genero`, e `MAX_PARES` soma `len(GENEROS)`.
- `filtros()` devolve `generos`. Valor fora dos 4 dá 400 "genero deve ser feminino, masculino, unissex, sem, sem repetir", sem ecoar o valor recebido.
- A oferta ganha `"genero"`. O filtro roda em `_casa`, e `total` conta já filtrado.
- Cada categoria ganha `"generos": {"feminino": n, "masculino": n, "unissex": n, "sem": n}`, com as 4 chaves sempre presentes.
- `oferta(row, eh_afiliado, manuais=None)` mantém compatibilidade com quem chama com 2 argumentos.

**Front (dados e estados; o visual é da spec):**
- Dados: `item.genero` e `item.genero_origem`.
- Lógica testável em `function` global: `abaTemGenero(cat)`, `contarGeneros(lista)` e `casaGenero(item, generos)`, esta usada por `filtrada()` e `contarItens()`.
- Estados:
  - controle ausente em aba sem gênero;
  - público lembrado por aba (`localStorage`, `genero:<aba>`), com valor inexistente caindo em "Todos";
  - contagens com os filtros de loja e título, sem o próprio público;
  - correção: salvando, erro (toast de erro e select volta ao valor anterior) e sucesso (selo e contagens mudam sem recarregar);
  - no formulário da regra, `generos` vira `[]` em "Todos" e `[valor]` no resto.

## Etapas
| # | Etapa | Arquivos | Verificação | Responsável | Grupo | Sensível | CAs |
|---|---|---|---|---|---|---|---|
| 1 | `genero.py` com `classificar`, `manuais`, `do_item` e `definir_manual`. Teste com cerca de 40 títulos reais da amostra acima (inclusive os casos listados e as 4 abas), com prioridade título > linha > busca, NFKD/acentos, tabela ausente dando `{}`, e `definir_manual` gravando e apagando. | `genero.py`, `testes/test_genero.py` | `python3 testes/test_genero.py -v` e `python3 -m py_compile genero.py` | dev | A | não | CA1, CA9 |
| 2 | Migração v2 em `disparo.migrar`: `ESQUEMA_V2`, `VERSAO_ESQUEMA=2`, v0→v2 e v1→v2 na mesma transação. Testes: v1 com regras e itens vira v2 sem perder nada (`generos='[]'`), repetir não faz nada, falha no meio desfaz tudo, v3 não é tocada. Atualizar os asserts de versão 1. | `disparo.py` (só o bloco de esquema), `testes/test_disparo.py` (só a classe de migração) | `python3 testes/test_disparo.py -v` | dev | A | **sim** | CA7, CA9 |
| 3 | Servidor: `genero` e `genero_origem` em `linha_para_item` e no GET/PATCH; rota `PUT /api/items/<id>/genero`; limpeza no DELETE. Testes em subprocesso com banco temporário: upsert novo já sai classificado (CA2); correção persiste e volta ao automático com `null`; 400, 404, 415 e 413; Origin do ML dá 403; `Sec-Fetch-Site: cross-site` dá 403; aba sem gênero dá 400; `atualizado_em` muda. | `servidor.py`, `testes/test_genero_servidor.py` (novo); `testes/test_servidor.py` só se algum assert fixar as chaves do item | `python3 testes/test_genero_servidor.py -v && python3 testes/test_servidor.py -v && python3 testes/test_servidor_qa.py -v` | dev | B | **sim** | CA2, CA4, CA9 |
| 4 | Disparo: `generos` na regra (validação, CRUD e prévia) e em `elegiveis`; texto do `AVISO_FILTROS`. Testes: regra antiga elege o mesmo conjunto antes e depois; `["feminino"]` com Perfumaria + Casa leva só perfumes F e a Casa inteira; correção manual vale; valor inválido ou repetido dá 400. | `disparo.py` (validação e seleção), `testes/test_disparo.py` (classes de regra e seleção); `testes/test_disparo_qa.py` só se fixar campos | `python3 testes/test_disparo.py -v && python3 testes/test_disparo_qa.py -v && python3 testes/test_disparo_servidor.py -v` | dev | C | não | CA5, CA9 |
| 5 | API v1: `genero` na oferta, filtro e contagem em categorias. Testes: oferta com os 4 valores; `genero` repetível, inválido dá 400 sem eco, repetido dá 400; `MAX_PARES`; categorias com as 4 chaves; nada que existe muda (os testes antigos passam sem edição, exceto a lista de parâmetros na mensagem). Contrato: campo, parâmetro, erro, exemplo e a nota "mudança de regra do classificador não mexe em `atualizado_em`". | `api_ofertas.py`, `testes/test_api_ofertas.py`, `docs/produto/referencias/api-ofertas.md`; `testes/test_api_ofertas_qa.py` só se fixar a mensagem | `python3 testes/test_api_ofertas.py -v && python3 testes/test_api_ofertas_servidor.py -v && python3 testes/test_api_ofertas_qa.py -v && node --test testes/api_ofertas.test.mjs testes/api_ofertas_qa.test.mjs` | dev | B | **sim** | CA6, CA9 |
| 6 | Front, Parte A, lógica e marcação mínima conforme a spec: público em `filtrada()` e `render()`, contagens, select de buscas restrito, memória por aba, selo em "Todos", correção em "Mais ações" (se P2 = sim), campo da regra, `contarItens` e resumo da regra. Página de teste nova com itens falsos via `renderCard` e as funções globais; o PUT é interceptado pela guarda, como no `abas.test.html`. Ajustar páginas que contam botões. | `index.html`, `testes/genero.test.html` (novo); `testes/disparo.test.html` e `testes/disparo-qa.test.html` só no que a spec mudar | Servidor de teste com cópia (`sqlite3 backup`) na 8766: `PORTA=8766 node testes/rodar.mjs genero`, `copiar-imagem`, `abrir-e-adicionar`, `mensagens`; com `ACHADINHOS_DISPARO=0`: `disparo`, `disparo-qa` | dev | D | não | CA3, CA4, CA5 |
| 7 | Visual da Parte A (CA-V1 a CA-V12) e itens **só de apresentação** aprovados da Parte B (M1, M6 e M7). Mexe só em estilo, marcação e textos. | `index.html` | As mesmas páginas da etapa 6, mais conferência em 320 e 1280 px, claro e escuro | designer | E | não | CA3, CA8 |
| 8 | Docs: seção "Público (gênero)" no README (como corrigir, abas com gênero, como incluir uma aba nova em `ABAS_COM_GENERO`); CLAUDE.md (camada `genero.py`, `user_version` 2, rota PUT, novos testes na Verificação). | `README.md`, `CLAUDE.md` | `rg -n "genero" README.md CLAUDE.md` | dev | E | não | CA9 |
| 9 | (se P4 = entrega única) Itens da Parte B com JS de estado: M3 (carregando, erro, vazio), M5 (foco preservado) e, se aprovados, M2, M4 e S1/S2. | `index.html`, `testes/genero.test.html` | As mesmas páginas da etapa 6 | dev | F | não | CA8 |

Ordem: A (1 ∥ 2) → B (3 ∥ 5) → C (4) → D (6) → E (7 ∥ 8) → F (9). A etapa 4 fica fora do grupo B porque divide `disparo.py` e `test_disparo.py` com a 2 (e a 2 precisa estar pronta). Também podia rodar junto com a 3 e a 5, que não tocam esses arquivos; separei para o `test_disparo_servidor` rodar contra um `servidor.py` já estável. As etapas 6, 7 e 9 tocam `index.html` e ficam sempre sozinhas no grupo. Antes da etapa 9, a 7 tem de ter terminado.

## Pontos para o seguranca
- **Rota nova de escrita (etapa 3):**
  - origem do ML e `Sec-Fetch-Site` cross-site/same-site dão 403;
  - `Content-Type`, tamanho do corpo e valor só da lista;
  - id inteiro e SQL só com `?`;
  - nenhuma mensagem de erro repete o valor recebido;
  - a correção não troca `url` nem nenhum outro campo do item.
- **Migração (etapa 2):** `BEGIN IMMEDIATE` com releitura da versão, aditiva, e o `ALTER` só em `regras`. Um servidor antigo rodando enquanto uma coleta nova migra não quebra, porque ele ignora a coluna e a tabela novas.
- **API v1 (etapa 5):** whitelist do parâmetro, teto `MAX_PARES`, a conexão continua `query_only`, e o `genero` não abre caminho para oferta sem link de afiliado (o `oferta()` confere antes).
- **Front:** `genero` e as contagens sempre por `esc()`/`textContent`, e valores só da lista.
- **LGPD:** é gênero do produto, não de pessoa. Nenhum dado pessoal novo.

## Riscos e como reverter
- **Migração:** antes de subir o código novo pela primeira vez, faça `sqlite3 achadinhos.db ".backup backups/antes-genero.db"`. Para reverter, volte o código: o antigo vê `user_version` 2 ≥ 1, não migra, e ignora a tabela e a coluna. Não há migração destrutiva neste plano. Se um dia for preciso apagar `generos_manuais`, isso vai numa migração separada, que aborta se houver dados.
- **`migrar_categorias.py --restaurar`:** ele devolve o banco inteiro e apaga as correções feitas depois do backup. O README já avisa que tudo volta; a etapa 8 passa a citar as correções também.
- **Classificação errada:** a correção manual (CA4) cobre o caso a caso, e um ajuste em `genero.py` vale na hora para todos. Achado lateral: há vinho "Malbec" e "Bota Invictus" na aba (ruído da coleta), que saem como masculino.
- **Renomear a aba "Perfumes e Perfumaria":** o gênero some até `ABAS_COM_GENERO` ser atualizada. O `test_genero.py` confere que cada aba da constante existe em `buscas.json`.
- **Desempenho:** a classificação completa leva ~66 ms no `/api/items` e é feita por regra a cada tick, só nas abas da regra. Se pesar, classifique só as linhas de `ABAS_COM_GENERO` (o resto é `sem`).
- **Turbo:** quando a regra do classificador muda, o gênero muda sem mexer em `atualizado_em`. O contrato manda reler do início se precisar. O Turbo não usa `genero` hoje; o lado dele não faz parte deste plano.

## Decisões tomadas na implementação (03/11/2026)
- **Dono:** gênero só em "Perfumes e Perfumaria" (P1); correção à mão nesta entrega (P2); sem "Infantil" (P3); UX agora = Parte A + M1, M3, M5, M6, M7 (P4), com M2, M4 e M8 para a entrega 2; M7 aprovada (Template e "Editar templates" saem do cabeçalho do disparo).
- **Lead:** o front usa a constante `ABAS_COM_GENERO` (espelho do `genero.py`, conferida por `testes/test_front_constantes.py`) em vez de decidir a aba pela regra "2 valores ou mais"; `PUT /api/items/<id>/genero` com `null` vale em qualquer aba (apaga a correção guardada) e só mexe em `atualizado_em` quando algo mudou; id no caminho com teto de 19 dígitos (404 acima de 2^63-1); o servidor devolve `genero_auto` para a tela mostrar "Automático (<valor>)".
- **Classificador:** `homem|homens`, `hombres?`, `mujer(?:es)?`; a linha de produto não vale com vinho/bota/calçado no título.

## Perguntas em aberto e premissas adotadas
- **P1 — Abas com gênero.** Recomendo só "Perfumes e Perfumaria", pela tabela de medição. Os smartwatches (cerca de 20) poderiam entrar se o dono quiser; para isso basta acrescentar a aba à constante.
- **P2 — Correção à mão pelo site.** Recomendo entrar nesta entrega: são 264 itens classificados só pela busca, com erros visíveis (ex.: "Granado Vintage" em "árabe masculino"). Fazer depois exigiria uma migração v3. A spec deixou isso de fora (pergunta 1 dela). Se o dono aprovar, o `designer` acrescenta o select "Público" em "Mais ações", e o CA4 e a parte da etapa 6 entram.
- **P3 — Infantil.** Hoje fica `sem` (53 de 62 itens "kids/infantil" não têm marca). Um quinto valor fica fora; recomendo não fazer agora.
- **P4 — Corte do "melhore o UX/UI".** Recomendo que esta entrega leve a Parte A, mais M1, M6 e M7 (só apresentação, etapa 7), mais M3 e M5 (corrigem falhas reais: página em branco quando a API falha e foco perdido, etapa 9). M2, M4 e M8 mudam paginação, filtros e seletores usados nos testes; viram uma entrega 2 com plano próprio. A spec ainda tem as perguntas 4 e 5 dela para o dono.
- **P5 — "Feminino + Unissex" na regra.** A spec usa rádio, e o dado já aceita a lista. Se o dono quiser a combinação, só a tela muda.
- **Premissas:**
  - `genero_origem` sai só no `/api/items`, não na v1;
  - a v1 continua na `versao` 1;
  - a regra do disparo aceita `sem` na API, mas a tela não oferece;
  - a "aba com gênero" do front segue a regra da spec (2 valores ou mais), equivalente à constante do Python.

## ADR
**ADR — Gênero derivado na leitura, com correção manual em tabela própria.**
- **Contexto:** o gênero depende do título e da busca, que mudam por 6 caminhos de escrita, e a regra vai ser ajustada com o uso.
- **Decisão:** um módulo puro, `genero.py`, calcula o gênero a cada leitura. Só a exceção do dono é persistida, em `generos_manuais` (`user_version` 2). As abas com gênero ficam em `ABAS_COM_GENERO`.
- **Consequências:**
  - item novo e mudança de regra não exigem backfill;
  - `items` não muda;
  - o filtro não vai para o SQL, mas os três consumidores já filtram em Python;
  - incluir uma aba exige mudar a constante;
  - a mudança de regra não mexe em `atualizado_em`.
- **Alternativa rejeitada:** coluna em `items` gravada na escrita, pelo risco de o gênero ficar desatualizado em silêncio e pelo backfill a cada ajuste.
