# Plano técnico: atualizar o preço da Shopee item a item pela Open API
- Brief: não há. Pedido do lead de 06/11/2026; os planos de origem são `docs/produto/planos/atualizar-precos.md` (CA4), `perfumaria-tres-lojas.md` (F5) e, como modelo de fonte com teto, `api-oficial-ml-catalogo.md`.
- Data: 2026-11-06
- **G1 de 09/11/2026 (dono):** a credencial passou (`OK: o link gerado pela API é do afiliado 18328801339`), mas a consulta por item voltou `ERRO: a API da Shopee recusou (código 10010)`. É o caso já medido no garimpo (medições #37 e #38 em `tools/garimpo_feminino/docs/api_interpretacao.md`): `shopId`/`itemId` são `Int64` no schema e, como número JSON, a API recusa com 10010; como texto, aceita e devolve o item. Ajuste do lead, previsto em "Riscos": a query continua com `$shopId: Int64, $itemId: Int64` e os ids vão nas variáveis como texto de dígitos (`str(int())` depois do `_inteiro` e do `MAX_ID_API`; zero à esquerda some). Revisado (revisor R1/R2/R4, seguranca S1). G1 de novo às 04:2x: passou. 1ª rodada completa (04:36): 535 dos 540 itens voltaram da API (item), 5 ficaram `tentado` e 378 gravaram preço; os outros 157 voltaram, mas não gravaram (piso, usado ou sem preço legível).
- **Atualização de 08/11/2026 (implementado, revisado em 2 rodadas):** a etapa 2 foi feita antes do G1, que segue com o dono. A decisão 2 mudou: resposta vazia, resposta só com outros produtos e erro do item gravam `shopee|<dia>|tentado|<iid>`, e o item tentado vai para o fim da fila nos dias seguintes. A parada "não filtrou" vale com 5 divergentes novos ou 20 respostas novas sem produto, sem nenhum item casado. Erro do item (`productOfferV2: null` ou código fora de `ERROS_GERAIS` com HTTP 200) marca e segue; erro geral marca e sai com 1. O processo chama `proteger_processo()` (`PR_SET_DUMPABLE=0`) antes de ler o Secret. O G1 exige `no_para_item` e imprime o preço lido. Detalhes no README e nas docstrings.

## Objetivo e critérios de aceite
`python3 atualizar_precos.py shopee --cat ABA` passa a consultar cada item selecionado pela Open API, pelo produto (`shopId` + `itemId`). Hoje ele só reconhece o item que ainda aparece na página 1 da busca do termo. Na rodada real de 06/11, isso deu 29 atualizados de 540 e 457 não vistos.

- **CA1:** cada item selecionado é consultado por `productOfferV2(shopId, itemId)`. Só vale o nó cujo `shopId`/`itemId` é o pedido.
  - O argumento não tem confirmação oficial (veja "Contexto atual"). O portão **G1** prova o filtro antes da primeira rodada real.
  - Se a API não filtrar, a rodada para com 1 e não queima a cota.
- **CA2:** só `preco`, `preco_antigo` e `desconto` são gravados, sobre a linha relida (o mesmo `RELER` do ML).
  - O link de afiliado nunca é trocado e nenhum item é inserido (`upsert(inserir=False)`).
  - O piso (nota ≥ 4,5 e ≥ 50 vendas) e a recusa de usado continuam como hoje, pelos dados que a API devolve.
- **CA3:** a rodada tem um teto de chamadas à API, `--max-chamadas` (padrão 1000, máximo 5000), e uma pausa de 1 a 3 s entre as chamadas.
  - O limite da API (10030 ou HTTP 429) e o teto saem com 3.
  - O progresso por dia fica em `atualizar_precos_feitos.txt`, com a linha `shopee|<dia>|item|<shopId>.<itemId>`. Rodar de novo no mesmo dia retoma.
- **CA4:** o Secret e o AppID continuam só no ambiente do comando: o Secret é lido com `pop` e nunca vai para `argv`, log ou arquivo. O link é conferido por `utm_source=an_<ID>` antes da primeira gravação.
- **CA5:** os testes não usam rede (openers falsos, proxies em `127.0.0.1:9`), no padrão de `testes/test_atualizar_precos*.py`. O README e o CLAUDE.md são atualizados.

## Contexto atual
- **Fonte de hoje.** `fonte_shopee_api` (`atualizar_precos.py:412-438`) percorre os termos da aba nas ordens de `coleta_shopee_feitos.txt` e chama `CS.buscar`, que pede 1 página de 30 (`coletar_shopee.py:70-74`, `:158-162`, `POR_BUSCA = 30`, `:68`).
  - `_observacao_shopee` (`atualizar_precos.py:394-409`) transforma o nó em `ok`, `usado`, `fora_do_piso` ou `indisponivel`, pelo `no_para_item` (`coletar_shopee.py:219-256`).
  - A gravação é a `_gravar` completa (`atualizar_precos.py:211-222`). Ela regrava **todos** os `S.CAMPOS` (título, nota, vendas, foto) com o que vem da API, porque o `upsert` faz `UPDATE ... SET` de todos os CAMPOS (`servidor.py:381-387`). O link fica, pelo `CASE` com `sql_link_preservado` (`servidor.py:172-180`).
- **Gravação só do preço:** já existe para o ML. `_gravar_relendo` (`atualizar_precos.py:225-246`) relê a linha em `BEGIN IMMEDIATE` e troca só os `CAMPOS_DO_PRECO` (`:90`). Para ativá-la, basta a chave `RELER` no `it` (`:207`).
- **Teto e saída 3:** `Bloqueio(TETO)` (`:91-100`) e `_resultado` (`:603-613`) já imprimem a mensagem do `--max-chamadas`.
- **Retomada por rótulo de item:** já existe no `produto|<ASIN>` da Amazon (`:363-370`). `atualizar()` marca o rótulo a cada página (`:264-271`).
- **Rede da Shopee:**
  - `buscar` (`coletar_shopee.py:376-397`) é o **único** `OPENER_API.open(`. O `testes/test_shopee_qa.py:649` reprova se houver um segundo.
  - Não segue redirect (`:366-373`). O limite vira `LimiteAtingido` pelo 10030 ou pelo HTTP 429 (`:394-395`).
  - `credenciais()` faz `pop` (`:314-323`) e `conferir_dono` confere o link (`:418-420`).
- **`conferir`** (`coletar_shopee.py:435-442`) faz 1 busca e confere o dono. Os testes `test_coletar_shopee.py:508-526` e `test_shopee_qa.py:941-950` contam com **uma** chamada à API, então a prova do filtro não pode entrar no `conferir` sem flag.
- **Dados de 06/11, pelo `GET /api/items`, sem ler o banco:**
  - 540 itens da Shopee, todos em "Perfumes e Perfumaria", em 307 lojas distintas (a maior tem 21 itens).
  - Os ids têm até 11 dígitos, todos abaixo de 2^63.
  - O `preco_em` é de 03/11 em 511 itens e de 06/11 em 29.
  - Nenhum item tem `preco_antigo`.
- **Documentação.** A oficial fica dentro do painel logado (`affiliate.shopee.com.br/open_api`); o WebFetch só viu o título da página. Quatro fontes de terceiros, independentes, dizem que `productOfferV2` aceita `shopId: Int64` e `itemId: Int64`, opcionais, junto de `keyword`, `sortType`, `page`, `limit`, `listType` e `matchId`:
  - a documentação `bcat95/shopee-aff` (Vietnã);
  - a `affiliateshopee.com.br/documentacao` (Brasil, não oficial);
  - o SDK `Shopee.Affiliate` no NuGet;
  - um PR do `ugcbatch-studio`.

  As mesmas fontes trazem `priceMin`/`priceMax` como String, 10030 = limite, 11001 = erro de parâmetro e 10010 = erro de parse. Nenhuma diz a cota por hora. **Não verificado no oficial.**
- **Linha de base (arquiteto, 06/11, 03:54, proxies em `127.0.0.1:9`):**
  - `test_coletar_shopee` 83 OK, `test_shopee_qa` 65 OK, `test_ordens_qa` 28 OK.
  - `test_atualizar_precos`: 40 testes, **3 falhas**: `test_item_confirmado_hoje_nao_e_selecionado`, `test_encaixe_sem_rede` e `test_resumo_lista_ate_20_ids_e_nenhum_titulo`.
    - As três gravam `preco_em = hoje T07:00:00`. Antes das 06:55 esse horário fica "no futuro" além da `FOLGA_FUTURO_PRECO` (`disparo.py:751`) e conta como velho.
    - É um teste dependente da hora, sem relação com este plano. Rode a suíte depois das 07:00 ou registre o caso para o `qa` (ver "Perguntas").

## Abordagens consideradas
| Abordagem | Prós | Contras | Risco |
|---|---|---|---|
| A. `productOfferV2(shopId, itemId)`, uma chamada por item | Cobre 100% dos selecionados; independe do termo e da ordem; reaproveita `_pedir`, `_observacao_shopee`, `RELER`, `Bloqueio(TETO)` | ~540 chamadas por rodada (~20-25 min com a pausa, não medido); argumento sem confirmação oficial | Médio: G1 prova o filtro antes da rodada real |
| B. Paginar a busca do termo (páginas 2..N) até ver os pendentes | Sem argumento novo | Não garante achar o item (ele pode ter saído do índice do termo); mais chamadas que A para os itens fundos | Alto: continua cego |
| C. `listType 5` + `matchId = shopId` (vitrine da loja) | Uma chamada serve vários itens da mesma loja | 307 lojas para 540 itens: economiza pouco; paginação por loja; argumento também não verificado | Médio, sem ganho |

**A** é a certa: B não resolve a causa e C não economiza com 307 lojas.

## Decisão
1. **`coletar_shopee.py`** ganha a consulta por item:
   - `CONSULTA_ITEM` e `corpo_item(shop, item)`: ids como **texto de dígitos** em `variables` (`$shopId: Int64`), gerados por `str(int())` depois do `_inteiro` e do `MAX_ID_API`, nunca na query. Até o G1 de 09/11/2026 iam como número JSON, o que deu 10010.
   - `POR_ITEM = 5` (a confirmar no G1).
   - `_pedir(cred, corpo)`: o corpo atual do `buscar`, que continua sendo o único `OPENER_API.open(`.
   - `buscar(cred, termo, ordem)` passa a ser `_pedir(cred, corpo_consulta(...))`.
   - `buscar_item(cred, shop, item)` devolve a lista de nós.
   - `no_do_item(nos, shop, item)` devolve o nó com os mesmos ids ou `None`.
   - Novo `conferir --por-item` (portão G1): faz o `conferir` de hoje e depois consulta por item o primeiro nó válido da busca.
     - Sai com 0 se o nó voltar com os mesmos ids e preço legível.
     - Sai com 1 com "a consulta por item não devolveu o produto pedido".
     - Sai com 1 e o código, se a API recusar (10010 ou 11001 = argumento não aceito).
     - O `conferir` sem a flag não muda.
2. **`atualizar_precos.py`**: `fonte_shopee_item` substitui `fonte_shopee_api` em `FONTES`, e a busca por termo sai do atualizar.
   - Ordem dos itens: `preco_em` mais antigo primeiro. Pula o item com `item|<iid>` em `feitos` de hoje.
   - Antes de cada chamada, menos a primeira, `CS.pausa()`. Chegando a `max_chamadas`, para com `Bloqueio(TETO)`.
   - Mapeamento da resposta (página `item|<iid>`):
     - nó com os mesmos ids: `_observacao_shopee(CS, no, linha['busca'], linha['cat'], itens)`. Se der `ok`, ganha `RELER: True`;
     - nenhum nó: `indisponivel`, com rótulo marcado (não repete hoje);
     - nós sem o item: não visto e rótulo **não** marcado. A rodada conta `divergentes`.
   - Parada de segurança: com `divergentes >= DIVERGENTES_PARA_PARAR` (5) e nenhum nó casado na rodada, levanta `FiltroIgnorado`. O `_rodar_shopee` sai com 1: "a API não filtrou pelo item; rode coletar_shopee.py conferir --por-item".
   - Confere o dono no primeiro `ok`, antes de devolvê-lo (como hoje, `:434-436`).
   - `LimiteAtingido` vira `Bloqueio()`. `ErroApi`/`RespostaInvalida` param com 1, como hoje: o progresso já marcado fica e a rodada seguinte retoma.
3. **`--cat` continua obrigatório** na Shopee. Assim o quadro do site (`index.html:518-523`, `precisaCat:true`) não muda.

Excesso de engenharia evitado:
- sem cache, sem arquivo novo e sem migração;
- sem manter a fonte por termo como fallback: se o G1 falhar, a etapa 2 nem começa;
- sem retentar `ErroApi` por item;
- sem gravar nota, vendas e foto atualizadas (CA2 pede só preço).

## Esquema e contratos
Sem mudança de banco. Contratos novos:
```
# coletar_shopee.py
POR_ITEM = 5                                    # a confirmar (G1)
CONSULTA_ITEM = '''query PorItem($shopId: Int64, $itemId: Int64, $page: Int, $limit: Int) {
  productOfferV2(shopId: $shopId, itemId: $itemId, page: $page, limit: $limit) {
    nodes { itemId shopId productName priceMin priceDiscountRate ratingStar sales imageUrl offerLink }
  }
}'''                                            # a confirmar (G1): se a API filtra por esses argumentos
def corpo_item(shop: str, item: str) -> str     # variables {'shopId': '<dígitos>', 'itemId': '<dígitos>', 'page': 1, 'limit': POR_ITEM}
def _pedir(cred, corpo: str) -> list            # único OPENER_API.open(; mesmas exceções do buscar de hoje
def buscar_item(cred, shop: str, item: str) -> list
def no_do_item(nos, shop: str, item: str) -> dict | None   # compara _inteiro(no['shopId'/'itemId']) com os textos
# atualizar_precos.py
CHAMADAS_SHOPEE_PADRAO, MAX_CHAMADAS_SHOPEE = 1000, 5000
DIVERGENTES_PARA_PARAR = 5
class FiltroIgnorado(Exception)
def fonte_shopee_item(itens, opcoes)            # opcoes: cred, max_chamadas, feitos, agora (de atualizar())
FONTES = {'amazon': ..., 'shopee': fonte_shopee_item, 'ml': ...}
```
Linha de comando: `atualizar_precos.py shopee --cat ABA [--max-chamadas N]` (de 1 a 5000) e `coletar_shopee.py conferir [--por-item]`.

Id acima de 2^63-1 não vai à API: a fonte o deixa como não visto. Hoje não existe nenhum (máximo de 11 dígitos), mas o `ID_DA_LOJA` aceita 20.

## Etapas
| # | Etapa | Arquivos | Verificação | Responsável | Grupo | Sensível | CAs |
|---|---|---|---|---|---|---|---|
| 1 | `coletar_shopee.py`: o corpo do `buscar` vai para `_pedir`, que continua sendo o único `OPENER_API.open(`. Entram `CONSULTA_ITEM`, `POR_ITEM`, `corpo_item`, `buscar_item`, `no_do_item` e `conferir --por-item`. Testes: ids como texto de dígitos (`str(int())`) em `variables`, fora da query; mesmo host, assinatura e Authorization do `buscar`; `no_do_item` ignora nó de outro id, id em texto e `bool`; `--por-item` dá 0 com o mesmo nó, 1 com lista vazia, 1 com nó de outro id e 1 com `ErroApi(11001)` (o código aparece, o Secret não); faz 2 chamadas e confere o dono antes da segunda; `conferir` sem a flag continua com 1 chamada; 10030 e 429 em `buscar_item` levantam `LimiteAtingido`. Docstring do topo: `conferir --por-item` e "a confirmar (G1)" | `coletar_shopee.py`, `testes/test_coletar_shopee.py` | `python3 -m py_compile coletar_shopee.py`; com os proxies em `127.0.0.1:9`: `python3 testes/test_coletar_shopee.py -v`, `python3 testes/test_shopee_qa.py -v`, `python3 testes/test_ordens_qa.py -v` | dev | A | sim (HTTP, assinatura, credencial) | CA1, CA4, CA5 |
| G1 | **Portão, só o dono:** `read -rs S; ACHADINHOS_SHOPEE_SECRET="$S" ACHADINHOS_SHOPEE_APP_ID=<id> python3 coletar_shopee.py conferir --por-item; unset S`. Passa com saída 0. Com 1 e código 10010/11001, o lead traz a saída: o ajuste é o tipo (`Int64` → `String`, ou os ids em texto). Com 1 e "não devolveu o produto pedido", **pare**: a abordagem A cai e o plano volta ao arquiteto | nenhum | saída do comando, só código e texto fixo | lead + dono | — | sim (credencial) | CA1 |
| 2 | `atualizar_precos.py`: `fonte_shopee_item` no lugar de `fonte_shopee_api`. Também `--max-chamadas` no subparser `shopee`, `FiltroIgnorado` tratado no `_rodar_shopee` (saída 1, texto fixo) e `max_chamadas` em `opcoes`. A docstring do topo (seção Shopee e progresso) é reescrita. Testes, com `CS.buscar_item`, `CS.destino` e `CS.pausa` falsos e os openers que levantam erro (`Base` atual): cada selecionado é consultado 1 vez pelo id, o mais velho primeiro; só `preco`/`preco_antigo`/`desconto` mudam (título, nota, vendas, foto e url iguais aos do banco); piso, usado, sem preço e lista vazia não gravam; o dono é conferido antes da 1ª gravação e, se errado, nada é gravado (saída 1); o limite sai com 3 e o resumo é impresso; com `--max-chamadas 2` e 5 itens, saída 3, 2 chamadas, e a 2ª rodada no mesmo dia pula os já marcados; 5 divergentes sem casado saem com 1; Secret ausente sai com 2 sem chamar; o Secret nunca aparece, nem em exceção. Os testes da busca por termo (`test_usa_as_ordens_da_coleta_da_shopee`) e o `test_fontes_tem_as_tres_lojas` são ajustados | `atualizar_precos.py`, `testes/test_atualizar_precos.py` | `python3 -m py_compile atualizar_precos.py`; com os proxies em `127.0.0.1:9`: `python3 testes/test_atualizar_precos.py -v` (depois das 07:00; ver a linha de base), `python3 testes/test_atualizar_precos_qa.py`, `python3 testes/test_atualizar_precos_ml.py`, `python3 testes/test_atualizar_precos_ml_qa.py` | dev | B (depois do 1 e do G1) | sim (credencial, rede, gravação no banco) | CA1, CA2, CA3, CA4, CA5 |
| 3 | Docs. **README**, seção "Atualizar preços > Shopee" (`README.md:536-556`): o texto "ainda não tem a credencial" sai. Entram o comando com `--max-chamadas`, o G1 (`conferir --por-item`), o tempo estimado ("~20 a 25 min para 540 itens, não medido"), a linha `item|<id>` no progresso e o que significam `indisponíveis`, `não vistos` e a saída 1 "não filtrou". Em "Reverter", a linha da Shopee. **CLAUDE.md**, bullet do `atualizar_precos.py`: `shopee --cat ABA [--max-chamadas N]` por item, teto, `RELER` e progresso `item\|<id>`; bullet do `coletar_shopee.py`: `conferir [--por-item]` | `README.md`, `CLAUDE.md` | `rg -n "ainda não tem a credencial\|o dono ainda não tem a credencial" README.md CLAUDE.md` vazio; `rg -n "conferir --por-item" README.md CLAUDE.md` com resultado | dev | C (depois do 2) | não | CA5 |

Os grupos A, B e C são sequenciais: a etapa 2 faz `mock.patch.object(CS, 'buscar_item')`, que só existe depois da etapa 1.

## Pontos para o seguranca
- **Um ponto de rede.** Continua havendo um único `OPENER_API.open(` em `coletar_shopee.py` (`test_shopee_qa.py:649`), com host fixo, sem redirect e teto de 2 MB. O `_pedir` não aceita URL como parâmetro.
- **Ids.** Vêm do banco, já filtrados por `ID_DA_LOJA['shopee']`, e vão nas `variables` como texto de dígitos gerado por `str(int())` depois do `_inteiro` (`\d{1,20}` com `re.A`, ou int sem bool) e do teto 2^63-1, nunca interpolados na query. Afrouxar essa validação deixaria texto livre chegar à API. Id acima de 2^63-1 não sai.
- **O que vem da API.** Ela só influi em preço e desconto (`RELER`): título, foto e link do banco não mudam. Isso reduz a superfície de texto externo que chega à mensagem do WhatsApp, em relação à fonte de hoje.
- **Saída.** Só ids numéricos, contagens e textos fixos. A exceção genérica imprime só o tipo (`atualizar_precos.py:684-686`). `FiltroIgnorado` tem texto fixo.
- **Credencial.** O `pop` é feito no `_rodar_shopee`, antes do banco. O `conferir --por-item` usa o mesmo `credenciais()`. Nenhum teste cria credencial real: são marcadores, como em `test_atualizar_precos.py:56-64`.
- **Cota.** O teto padrão de 1000 e a pausa de 1 a 3 s dão no máximo ~1.800 chamadas por hora. A cota real não está verificada (P2). A parada por `FiltroIgnorado` evita gastar a cota com um filtro que não funciona.
- **Dono do link.** Conferido uma vez por rodada, no primeiro `ok`, como hoje. O link gravado nunca muda (`CASE` do `upsert`).

## Riscos e como reverter
- **O filtro não funciona** (G1 com "não devolveu"). A etapa 2 não começa. A etapa 1 é inofensiva: o `buscar` e o `conferir` sem flag não mudam. Reverter é `git revert` do commit da etapa 1, se o dono preferir.
- **O tipo `Int64` é recusado** (10010/11001 no G1). Aconteceu no G1 de 09/11/2026 (10010, número JSON). Os ids passaram a ir como texto nas variáveis `Int64`, como medido no garimpo (#38), e o G1 roda de novo.
- **Cota estourada no meio.** Sai com 3, e o progresso `item|<id>` fica. Espere e rode de novo, ou baixe o `--max-chamadas`.
- **Preço gravado errado** (por exemplo, `priceMin` de uma variação mais barata). É o mesmo campo que a coleta já grava hoje, então o risco não piora. Para reverter um lote: backup antes da 1ª rodada real (`sqlite3 achadinhos.db ".backup backups/antes-shopee-item.db"`, com o servidor parado) e `migrar_categorias.py --restaurar`, que devolve o banco **inteiro** (`README.md`, "Reverter"). Sem migração, voltar o código basta para parar novas gravações.
- **Rodada longa interrompida (Ctrl+C).** O item em curso não foi marcado e é refeito. Os gravados têm commit por item.

## Perguntas em aberto e premissas adotadas
- **P1 (G1).** O dono confirma no painel logado (Open API > documentação do `productOfferV2`) que `shopId` e `itemId` existem e qual é o tipo deles? O G1 prova na prática, mas a confirmação no painel tira o "a confirmar" do código.
- **P2.** Qual a cota de chamadas por hora da Open API (está na mesma página do painel)? Premissa: ela comporta 1000 chamadas com pausa de 1 a 3 s. O padrão do `--max-chamadas` se ajusta a ela.
- **P3.** O quadro "Como atualizar os preços" do site (`index.html:518-523`) ainda mostra "Por enquanto: importar" e "Quando a credencial chegar". Com a credencial liberada, o texto fica velho. Premissa: fica para uma mudança só visual do `designer`, **depois** que a mudança em curso no `index.html` (spec `black-friday`, ainda sem commit) for fechada. Este plano não toca o `index.html`.
- **P4.** O `qa` precisa tratar o teste dependente da hora em `test_atualizar_precos.py` (`T07:00:00` fixo) como bug baixo e separado? Premissa: sim, fora deste plano.
- **Premissas:**
  - `--cat` segue obrigatório.
  - `preco_antigo` continua vazio: a API não dá o preço cheio e o código não o inventa a partir do `priceDiscountRate`.
  - Nota, vendas e foto não são atualizadas por esta fonte.
  - O `coletar_shopee.py buscas` e o `importar` não mudam.

## ADR
Não há decisão significativa nova: sem dependência, sem modelo de dados e sem API pública. A fonte por id já estava prevista como "ponto de troca" em `atualizar-precos.md` (Decisão 3). O que muda de padrão é a Shopee passar a gravar só o preço (`RELER`), como o ML já faz. O registro fica neste plano.
