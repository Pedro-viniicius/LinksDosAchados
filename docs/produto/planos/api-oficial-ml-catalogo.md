# Plano técnico: API oficial do ML pelo catálogo (revisão do G1)
- Brief: não há. Revisa as etapas 4 e 5 de `docs/produto/planos/api-oficial-ml.md` (seções "Decisões do dono" e "Registro do G1"). Esse plano continua valendo para OAuth, tokens, `Sessao` e regras de saída.
- Data: 2026-11-05

## Objetivo e critérios de aceite
O dono pediu "a API funcionando". A única porta aberta é o catálogo (`/products/*`). Com ela, queremos **atualizar o preço dos itens do ML** e, numa segunda entrega, **coletar ofertas**. O `meli.la` continua vindo do `ColetaML.afiliar()`.

- CA1: `ml_api.py sondar --catalogo [--amostra N] [--semente S]` só lê.
  - O banco abre em `mode=ro` e nenhum arquivo é gravado pelo código. (Risco aceito pelo lead em 05/11, Q1 do qa: ao abrir um banco WAL em `mode=ro` sem o servidor conectado, o próprio SQLite cria `achadinhos.db-wal` vazio e `-shm`; o `.db` não muda, os dois estão no `.gitignore` e o `ids_do_banco` já fazia o mesmo.)
  - Usa no máximo `--amostra` itens (padrão 50, máximo 100) e para em 500 chamadas.
  - Imprime só status, código de erro, nomes de campo, contagens, nomes de aba e até 5 ids `MLB` por linha. Título, preço e token nunca saem.
  - Saídas 0/1/2/3, as mesmas do `ml_api.py`.
- CA2: a sonda mede F7 a F15 (ver "Perguntas"), cada um numa linha própria com prefixo `F<n>`. No fim, imprime "chamadas: N, 429: N, tempo: Xs".
- CA3: um anúncio só se liga a um produto de catálogo **com prova**: o `item_id` do banco é o `buy_box_winner.item_id` do produto ou aparece em `/products/{id}/items`. Semelhança de título nunca basta.
  - O vínculo fica em `ml_catalogo.json` (o caminho vem de `ACHADINHOS_ML_CATALOGO`). O arquivo está no `.gitignore` e é gravado por escrita atômica.
  - A leitura é estrita: só arquivo comum do usuário, até 2 MB, ids casando com `RE_MLB`/`RE_PRODUTO`.
  - Um vínculo negativo é tentado de novo depois de 7 dias.
- CA4: `atualizar_precos.py ml [--cat ABA] [--vincular N] [--max-chamadas N]` só grava itens que já existem (`inserir=False`) e nunca troca o `meli.la`.
  - O preço vem **só da oferta do próprio anúncio**: do `buy_box_winner` quando o `item_id` é o mesmo, ou senão da linha dele em `/products/{id}/items`. O preço do vencedor nunca vale para outro anúncio.
  - `titulo`, nota, vendas, foto, frete e cupom vêm do banco. Só `preco`, `preco_antigo` e `desconto` mudam.
  - `condition != 'new'` ou `eh_usado` contam como `usado`. Moeda diferente de `BRL` ou preço inválido contam como `sem_preco`. Item vinculado que saiu do produto conta como `indisponivel`. Item sem vínculo conta em `nao_vistos`. Nenhum deles é gravado.
- CA5: o comando tem limites e saídas fixas.
  - `--vincular` tem padrão 300 e máximo 1000. `--max-chamadas` tem padrão 3000 e máximo 10000. Há uma pausa de 0,3 a 0,8 s entre chamadas.
  - `Limite` dá saída 3, com o que já foi gravado mantido. `SemPermissao`, `RefazerAutorizacao` e `ConfigFaltando` dão saída 2. O Secret só é pedido se o token precisar ser renovado.
- CA6: nenhum teste sai para a rede. O `py_compile`, `test_ml_api.py` (100) e `test_ml_api_qa.py` (30) continuam passando, e as outras suítes também, salvo as 3 falhas que já existem no `test_atualizar_precos`.
- CA7: o README explica `sondar --catalogo`, `atualizar_precos.py ml`, o arquivo de vínculos, os tempos e as saídas.
- CA8: `servidor.py`, `index.html`, `disparo.py`, `api_ofertas.py`, `coletar_ml.js`, `mensagens.html` e `amazon.php` não mudam. Não há migração, e nada vai para a tabela `config`.
- CA9 (entrega 2, condicional ao G3): `coletar_ml.py buscas --cat ABA` coleta pelo catálogo. O desenho está na seção "Coleta pelo catálogo".

## Contexto atual
- **`ml_api.py`** (commit 34d80cf). Peças que reaproveito:
  - `Sessao.get` (`:635`): host fixo, Bearer, 401 → uma renovação, 429 → `Limite`, 403 PolicyAgent → `SemPermissao`.
  - `montar_url` (`:663`), que faz `urlencode` dos params.
  - `RE_MLB`/`RE_PRODUTO` (`:70-71`), `formatar_preco`/`desconto`/`eh_usado` (`:209`, `:219`, `:236`) e o padrão atômico `gravar_tokens` (`:383`).
  - `ids_do_banco` (`:794`, banco `ro` com `query_only`), `_sonda`/`sondar` (`:814`, `:839`), `ler_argumentos` (`:889`) e `main` (`:899`).
- **`atualizar_precos.py`.**
  - `ID_DA_LOJA` (`:56`) ainda não tem `ml`.
  - O `SELECT` do `selecionar` (`:120`) lê só `id, item_id, cat, busca, preco, preco_em`.
  - `gravar_pagina` (`:154`) chama `S.upsert(..., inserir=False)` (`:174`). `atualizar` (`:180`) captura `Bloqueio` e conta `nao_vistos`.
  - Também estão aqui `FONTES` (`:371`), os subcomandos (`:381`) e o `main` (`:442`).
- **Armadilha (continua valendo).** O `upsert` regrava todos os `CAMPOS` (`servidor.py:37`, `:361`, `:383-387`), então a fonte precisa mandar `data` completo com o que está no banco. O `CASE` com `sql_link_preservado` mantém o `meli.la`. Nos 1.112 itens sem afiliado, a url é trocada pela url montada pelo id, que é a mesma forma de hoje.
- **Foto.** `disparo.imagem_permitida` e `HOSTS_FOTO_LOJA['ml'] = ('http2.mlstatic.com',)` ficam em `disparo.py:87` e `:690`. A coleta do JS monta a foto pelo id: `https://http2.mlstatic.com/D_Q_NP_2X_<id>-E.webp` (`coletar_ml.js:643-646`).
- **Banco** (medido em `ro`, 2026-11-05):
  - 3.818 itens do ML: 3.817 com id `MLB` e 2.705 com `meli.la`.
  - 14 abas com ML. As maiores são Celulares e Informática (721), TV/Alexa (422) e Beleza (340).
  - 157 termos `busca` distintos. `preco_em` vai de 03/11 a 04/11, todo do console. Isso permite comparar o preço da API com o do banco (F11).
  - O polycard tem `metadata.id`. Se ele traz também `product_id`, não verifiquei (`coletar_ml.js:600-604` não lê esse campo).

### O que a doc oficial diz (developers.mercadolivre.com.br, lida por `curl` em 2026-11-05)
- **Buscador de produtos** (atualizado em 29/12/2025):
  - `GET /products/search` aceita `site_id` (obrigatório) e `status`: `active` traz o produto apto a receber anúncio, e sem o parâmetro vêm ativos e inativos.
  - Aceita também `q` (palavras-chave, part number ou product id), `product_identifier` (GTIN, prioridade 1, devolve um produto), `domain_id`, `offset` e `limit`. O teto do `limit` não está escrito.
  - Cada resultado traz `id`, `status`, `domain_id`, `name`, `attributes` (`BRAND`, `MODEL`, `GTIN`…), `pictures`, `parent_id`, `children_ids` e, no formato novo, `catalog_product_id`. Existe ainda um `POST /products/search` por atributos, que exige pelo menos 3.
- **Detalhe** (`GET /products/{id}`):
  - Traz `status`, `permalink` (`.../p/<id>`, sem o item), `name`, `pickers`, `pictures` (`id` e `url`), `main_features`, `attributes`, `parent_id`, `children_ids` e `settings`.
  - Traz também o `buy_box_winner`: `null` sem competidor, ou objeto com `item_id`, `price`, `original_price`, `currency_id`, `condition`, `shipping.free_shipping`, `seller_id`, `listing_type_id`, `tags` e `product_id`. E o `buy_box_winner_price_range` (`min`/`max.price`).
  - O produto pai nunca é `active` e não pode ser comprado: os filhos ficam em `children_ids`. Um produto inativo vem com `permalink` vazio e `pictures` e `pickers` nulos.
  - **Não há nota nem vendas no produto.**
- **`/products/{id}/items`:** não achei esse endpoint na doc oficial (fica a confirmar, F9). Um PR de terceiro relata 200 com o preço de cada anúncio e usa justamente a regra "preço só se o produto contém o anúncio".
  - O `/items/{id}/price_to_win` (concorrência em catálogo) é do vendedor dono do anúncio e não serve aqui.
- **Mais vendidos** (`/highlights/MLB/category/{cat}`, atualizado em 22/06/2026): devolve até 20 elementos do tipo `ITEM`, `PRODUCT` ou `USER_PRODUCT` (`MLBU`). Exige "Métricas do negócio".
- **Permissões funcionais** (21/11/2025): "Buscador de produtos" e "Busca de items" estão sob **Publicação e sincronização**, que já está ativa. "Pedidos e opiniões" está sob **Vendas e envios**, que não está ativa. A doc não diz se isso abre o `/reviews/item` de terceiros (a confirmar, F13).
- **Sem token** (status medido agora):
  - `/products/{id}`: `401 unauthorized`, não PolicyAgent, o que indica que deve abrir com token.
  - `/products/{id}/items` e `/products/search`: 403 PolicyAgent (com token, F3 deu 200).
  - `/highlights`: `401 unspecified_token`.
  - `/reviews/item`: 403 PolicyAgent.
  - `/sites/MLB/search?product_id=`: `403 forbidden`, como o F1.

## O problema central: ligar o anúncio `MLB<n>` ao produto de catálogo
| Caminho | Como | Avaliação |
|---|---|---|
| (a) `/products/search?q=<título>` + escolha por título, marca e modelo | Ranqueia os candidatos | Sozinho, **descartado**: um título parecido não prova que o anúncio do link é daquele produto, e o preço sairia de outro vendedor. Serve só para **gerar candidatos** |
| **(a)+(c) candidatos por título e prova por pertença** | Para os até 3 primeiros candidatos (e até 3 filhos de um pai): `GET /products/{id}`. Se `buy_box_winner.item_id == item_id`, está provado. Senão, `GET /products/{id}/items` procurando o `item_id` (até 3 páginas) | **Escolhido.** Não há falso positivo: o anúncio está listado no produto. Custa de 2 a 13 chamadas por item uma vez só, e o resultado vai para o cache |
| (b) `product_identifier` (GTIN) | Exato | Não temos GTIN, e o `/items/{id}` (que traria `catalog_product_id`) dá 403: inviável |
| (c) `permalink` do produto | — | O `permalink` é `/p/<produto>` e não traz o item. Só o `buy_box_winner.item_id` serve, e ele já está dentro de (a)+(c) |
| (d) Página pública do anúncio | Ler `/p/` ou `MLB-<n>` | Fora: é scraping, não API |
| (e) O console grava o `product_id` do polycard | Vínculo direto, sem busca | Fica para um plano futuro (P6): mexe em `coletar_ml.js`, no contrato do servidor e no esquema |

**Cobertura esperada:** não verificada. Só entra no catálogo o anúncio que é publicação de catálogo ou que está ligado a um produto. Meu chute é de 30% a 60%: mais alto em Celulares, TV, Games e Eletro, e mais baixo em Beleza, Casa, Pets e Mercado, onde há muito anúncio sem catálogo e muito `MLBU`.

**Como medir (F10):**
- Uma amostra de 50 itens com semente fixa e o título como `q` (sem acento e sem pontuação, até 12 palavras).
- O resultado mostra quantos tiveram candidato, quantos ficaram **provados** (pelo `buy_box_winner` ou pela lista) e a contagem por aba.
- Com 50 itens, o intervalo de 95% é de cerca de ±14 pontos, o que basta para decidir.

## Preço
- O `meli.la` leva ao anúncio `MLB-<n>`. Numa publicação de catálogo, a página mostra a oferta **daquele** anúncio (não verifiquei se é sempre assim). Portanto o preço certo é o do próprio anúncio.
- **Regra:**
  1. Se `buy_box_winner.item_id == item_id`, vale o `price`/`original_price` do vencedor.
  2. Senão, vale a linha do `item_id` em `/products/{id}/items`.
  3. Senão, nada é gravado: o item conta como `indisponivel` (vinculado, mas ausente) e o preço envelhece. A trava do `preco_em` no disparo (`preco_validade_horas`) e o selo "Desatualizado" o tiram de circulação sozinhos.
  - Trocar o anúncio do banco pelo vencedor exigiria um `meli.la` novo: isso é coleta, não atualização.
- **Risco:** o preço da API pode ser diferente do preço da vitrine (Pix, promoção, preço por quantidade).
  - O F11 compara, nos itens provados da amostra, o preço da API com o preço do banco gravado pelo console há até 48 h. Cada item cai em uma de três faixas: igual, até 2% de diferença, ou acima de 2%.
  - Antes do primeiro lote real, o lead faz um backup com `sqlite3 backup`, e o dono confere 5 itens na página.

## Coleta pelo catálogo (entrega 2, condicional; proposta de corte)
- **Fluxo.**
  1. `/products/search?q=<termo>&status=active&site_id=MLB`.
  2. Para cada produto filho ativo, `/products/{id}`.
  3. O `buy_box_winner` precisa ser não nulo, `condition == 'new'`, moeda `BRL` e não passar no `eh_usado(name)`.
  4. Gravação: `item_id = bbw.item_id`, url `https://produto.mercadolivre.com.br/MLB-<n>` montada pelo id, `titulo = name`, preço por `formatar_preco`/`desconto`, frete por `shipping.free_shipping` e foto pelo `pictures[0].id` (regex `[0-9]+-ML[A-Z][0-9]+_[0-9]+`), passando pelo `imagem_permitida`.
  5. O item entra sem afiliado, e a saída lembra o dono de rodar o `ColetaML.afiliar()`.
- **Piso (P1 = (a), decidido pelo dono).** Nota ≥ 4,5 e N avaliações exigem o `/reviews/item`, que deu **403** (F5), e o produto não traz nota. **Hoje o piso é inviável.**
  - Opção 1: o dono ativa "Vendas e envios" em leitura e a sonda refaz o F13. Ainda não se sabe se isso abre o `/reviews/item` de terceiros.
  - Opção 2: trocar a P1 por (b), `/highlights` (top 20 por categoria do ML, que exige "Métricas do negócio", F14). Isso pede um mapa de aba para `category_id`.
  - Opção 3: a coleta fica no console.
- **Portão G3:** a coleta só entra se o F13 der 200 com a permissão ativada ou se o dono trocar a P1. Quando entrar, ganha uma revisão curta deste plano, como a etapa 5 do plano anterior.

## Decisão
1. **Primeiro, o G2.** O `sondar --catalogo` mede F7 a F15 com termos e títulos reais do banco. As etapas 2 e 3 só entram se **F8 = 200, F10 ≥ 25% de provados e F11 com pelo menos 80% de "igual"** (P4).
2. O vínculo vem de candidatos por título e é provado por pertença. Ele fica num arquivo-cache, não no banco: sem migração e sem tocar o `servidor.py`. Se o arquivo se perder, basta vincular de novo.
3. Tudo o que fala com a API fica no `ml_api.py`, que só ganha código novo. A fonte `ml` do `atualizar_precos.py` só orquestra.
4. Fora desta entrega: a coleta (G3), o vínculo pelo console (P6) e aposentar o `ColetaML.atualizar`.

## Esquema e contratos
- **Arquivo de vínculos** (`ml_catalogo.json`, JSON até 2 MB, modo 0600, sem segredo): `{"v":1,"itens":{"MLB<n>":{"p":"MLB<m>"|null,"em":"AAAA-MM-DD","via":"bbw"|"lista"|null}}}`.
  - Para gravar, o `dev` extrai o miolo de `gravar_tokens` numa `gravar_atomico(caminho, bytes, teto)`, que as duas gravações usam, sem mudar o comportamento dos tokens.
- **`ml_api.py`: código novo.**
  - `consulta_do_titulo(titulo) -> str`.
  - `candidatos(sessao, q, k=3) -> [pid]`, com filhos de pai, no máximo 3 cada.
  - `produto(sessao, pid) -> dict`.
  - `ofertas_do_produto(sessao, pid, ids, paginas=3) -> {item_id: Oferta|None}`: primeiro pelo `bbw`, depois pela lista.
  - `Oferta = namedtuple('Oferta', 'item_id preco preco_antigo moeda condicao via')`.
  - `oferta_valida(o)`: `preco` finito, 0 < preco < 10⁷ e moeda `BRL`.
  - `vincular(sessao, item_id, titulo) -> (pid|None, via)`.
  - `ler_vinculos()`/`gravar_vinculos()`.
  - `sondar_catalogo(sessao, db, amostra, semente, termos=5, teto=500)`.
  - Antes de entrar no caminho, o pid passa por `RE_PRODUTO.fullmatch`. O `item_id` da resposta só vale se casar com `RE_MLB`.
- **`atualizar_precos.py`.**
  - `ID_DA_LOJA['ml'] = re.compile(r'MLB[0-9]{6,19}')`, e o `selecionar` passa a ler também os `S.CAMPOS`.
  - `fonte_ml_catalogo(itens, opcoes)` vincula até `--vincular` itens (gravando o cache a cada 20) e agrupa os vinculados por produto.
  - Ela gera `('catalogo|<1º pid do lote>', [Observacao])` a cada 20 produtos. A retomada vem do `preco_em` de hoje, como no plano anterior.
  - `Limite` vira `Bloqueio`, e o teto de chamadas para com saída 3.
  - O `_rodar_ml` usa `ml_api.sessao_do_ambiente()`.

## Etapas
| # | Etapa | Arquivos | Verificação | Responsável | Grupo | Sensível | CAs |
|---|---|---|---|---|---|---|---|
| 1 | `sondar --catalogo [--amostra N] [--semente S]` em `ml_api.py` (argumentos novos em `ler_argumentos`; o `sondar` sem flag não muda). A amostra vem do banco em `ro`: `item_id, titulo, cat, preco, preco_em`. A sonda mede F7–F15 (lista em "Perguntas"), com o teto de 500 chamadas e uma pausa de 0,3 a 0,8 s. Testes com opener falso: a saída nunca traz título nem preço; ela conta os provados por `bbw` e pela lista; para no teto; pai vai para os filhos; 404 no `/items` não derruba; `Limite` dá 3; `SemPermissao` num F não para os outros | `ml_api.py`, `testes/test_ml_api_catalogo.py` | `python3 -m py_compile ml_api.py`, `python3 testes/test_ml_api_catalogo.py -v`, `python3 testes/test_ml_api.py`, `python3 testes/test_ml_api_qa.py` | dev (opus) | A | sim (token em uso, saída filtrada) | CA1, CA2, CA6 |
| G2 | O dono roda o `sondar --catalogo` (um comando por bloco). O lead registra F7–F15 e aplica o critério da Decisão 1 | — | saída da sonda | dono + lead | — | — | — |
| 2 | Vínculo e ofertas em `ml_api.py`: `gravar_atomico`, `ler_vinculos`/`gravar_vinculos`, `vincular`, `ofertas_do_produto` e `oferta_valida`. Mais `ml_catalogo.json` e `.ml_catalogo.json.*.tmp` no `.gitignore`. Testes: só há vínculo com prova; título idêntico sem pertença dá `None`; o negativo volta depois de 7 dias; arquivo symlink, 0644 ou acima de 2 MB é recusado; o pid é validado antes do caminho; `bbw` de outro item nunca vira oferta do nosso | `ml_api.py`, `testes/test_ml_api_catalogo.py`, `.gitignore` | o mesmo da 1 e `git check-ignore ml_catalogo.json .ml_catalogo.json.0123456789abcdef.tmp` (lista os 2) | dev (opus) | B | sim (rede, arquivo novo) | CA3, CA6 |
| 3 | Fonte `ml` no `atualizar_precos.py`: `ID_DA_LOJA`, `selecionar` com `CAMPOS`, `fonte_ml_catalogo`, subcomando `ml` e `_rodar_ml`. Testes: o `meli.la` fica; nada é inserido; nota, vendas, foto e título do banco ficam; o preço do vencedor que é outro anúncio não é gravado; `usado`, `sem_preco` e `indisponivel` não gravam; item sem vínculo cai em `nao_vistos`; `Limite` dá 3 e o que foi gravado fica; falta de Secret com token vencido dá 2; o teto de chamadas é respeitado | `atualizar_precos.py`, `testes/test_atualizar_precos_ml.py` | `python3 testes/test_atualizar_precos_ml.py -v`, `python3 testes/test_atualizar_precos.py` (só as 3 falhas de antes), `python3 testes/test_atualizar_precos_qa.py` | dev (opus) | C | sim (rede, segredo, escrita no banco) | CA4, CA5, CA6, CA8 |
| 4 | README: "Preços do ML pela API (catálogo)" com a sonda, `atualizar_precos.py ml`, o primeiro vínculo (cerca de 3.818 × 3 chamadas, em várias rodadas por aba), o arquivo de vínculos, o backup antes do primeiro lote e as saídas | `README.md` | leitura do revisor | dev | D | não | CA7 |
| G3 | Só para a coleta: o dono decide a P5. Se o F13 der 200 ou a P1 mudar, o arquiteto revisa este plano para o `coletar_ml.py` | — | — | dono + arquiteto | — | — | CA9 |

As etapas 1 e 2 dividem `ml_api.py` e o teste, então rodam em sequência. A 3 depende da 2. O CLAUDE.md fica com o lead: camadas (`ml_catalogo.json`), verificação (`test_ml_api_catalogo.py`, `test_atualizar_precos_ml.py`) e `atualizar_precos.py ml`.

## Pontos para o seguranca
- **Dado não confiável vindo da API.** Ids, preço, moeda e id de foto passam por regex ou faixa. A url é montada pelo `item_id` validado e nunca vem do `permalink`. O pid é validado antes do caminho, e `montar_url` recusa o resto.
- **`meli.la`.** Só existe gravação por `upsert(inserir=False)`. Há teste com o item `meli.la` e o banco temporário.
- **Saídas.** A sonda e o resumo mostram só contagens, ids `MLB`, status e códigos filtrados. Título e preço também ficam de fora, para não abrir precedente.
- **Arquivo de vínculos.** Não é segredo, mas é entrada local: tem leitura estrita e escrita atômica 0600. Os tokens continuam só no `ml_tokens.json`.
- **Volume.** O teto de chamadas por rodada e as pausas evitam bloqueio da app. Termos de uso do ML para afiliado que usa dados de catálogo: não verifiquei (vai como risco ao dono).
- **Permissões.** Ativar "Vendas e envios" (P5) amplia o escopo para pedidos. Em leitura e só se o dono aceitar. O `conferir` continua avisando `write`.

## Riscos e como reverter
- **Cobertura baixa ou preço divergente no G2.** As etapas 2 e 3 não entram, o ML segue no console e só fica a etapa 1. Para reverter, `git revert` da etapa.
- **Preço gravado errado.** O backup com `sqlite3 backup` vai para `backups/antes-ml-catalogo.db` antes do primeiro lote e é restaurado com o servidor parado (as atualizações feitas desde então se perdem). O link nunca muda.
- **O vínculo envelhece** (o anúncio sai do catálogo): o item conta como `indisponivel` e não grava. Para vincular de novo, apague `ml_catalogo.json`.
- **429 ou app bloqueada:** saída 3 e progresso pelo `preco_em`. Baixe `--vincular` e rode por aba.
- **O ML fecha `/products/*`:** `SemPermissao` dá saída 2, e o console continua como fallback.

## Perguntas em aberto e premissas adotadas
- **A confirmar pela sonda (G2):**
  - F7: busca pelo título. Medir quantos itens têm candidato, a média de candidatos e o teto real do `limit`.
  - F8: `/products/{id}` com token. Campos de `buy_box_winner` (`item_id`, `price`, `original_price`, `currency_id`, `condition`, `shipping`), `pictures[].id`, `children_ids` e `status`.
  - F9: `/products/{id}/items`. Formato (`results[].item_id`, `price`, `original_price`, `condition`), `paging` e o que o 404 significa (produto pai ou sem anúncio).
  - F10: cobertura dos provados, pelo `bbw` e pela lista, total e por aba.
  - F11: preço da API contra o preço do banco (até 48 h).
  - F12: busca por 5 termos do `buscas.json`. Medir produtos ativos com `bbw` não nulo e `new` (para a coleta).
  - F13: `/reviews/item/{id}`, que continua 403 até a P5.
  - F14: `/highlights/MLB/category/<cat do bbw>`.
  - F15: `/sites/MLB/search?product_id=`, que deve dar 403.
- **P4.** O dono aceita o critério do G2 (F10 ≥ 25% e F11 ≥ 80% igual)? Premissa: sim.
- **P5.** Para a coleta: (1) ativar "Vendas e envios" em leitura só para testar o F13, (2) trocar a P1 pelo `/highlights` (exige "Métricas do negócio") ou (3) coleta só no console? Premissa: (3) até a resposta.
- **P6.** Vale um plano futuro para o console gravar o `product_id` do polycard (vínculo sem busca, cobertura maior)? Premissa: só se o F10 vier baixo e o F11 bom.
- **Premissas.**
  - Os 1.112 itens sem `meli.la` também são atualizados (o link continua sem afiliado e o `afiliar()` resolve).
  - Uma máquina e um usuário.
  - A coleta pelo catálogo é a entrega 2.

## Decisões do dono (2026-11-05, registradas pelo lead)
- Plano aprovado; começa pela etapa 1 (sonda) e só segue para 2 e 3 se o G2 passar.
- P4: critério do G2 aceito (F10 ≥ 25% de provados e F11 ≥ 80% "igual").
- P5: **(3)** a coleta continua no console; a API fica só para preços. A entrega 2 (CA9) fica suspensa.

## Registro do G2 (2026-11-05, sonda rodada pelo dono: amostra 50 de 3.817, semente 20261105, 241 chamadas, 2×429, 239 s)
- F7: `/products/search` 200 com `limit=50` (paging.limit 50). Pelo título: 50 de 50 itens com candidato, média de 3,0 candidatos, 1 descartado.
- F8: `/products/{id}` 200 em 84 de 84. **`buy_box_winner` veio `null` em todos** (também nos 15 do F12). `pictures[].id` em 84, `status` active em 84, sem `children_ids` e sem `category_id` no produto.
- F9: `/products/{id}/items` 200 em 64 e 404 `not_found` em 20 (todos com `bbw` nulo). `results[]` traz `item_id, price, original_price, currency_id, condition, seller_id, listing_type_id, official_store_id, category_id, shipping`; `paging` com `limit, offset, total`.
- F10: **37 de 50 provados (74%)**, todos pela lista (0 pelo `bbw`). Por aba: Celulares 8/10, Bebês 5/6, Eletroportáteis 4/5, Pets 4/5, Cozinha 4/4, Casa 3/4, TV/Alexa 3/4, Mercado 2/3, Games 2/4, Beleza 1/2, Eletrodomésticos 1/1, Cama/Mesa/Banho 0/1, Áudio 0/1.
- F11 (preço do banco até 48 h): **igual 10, até 2% 0, acima de 2% 2 → 83% igual** em 12. Com preço mais antigo: igual 10, até 2% 3, acima de 2% 12 (esperado: o banco está velho).
- F12: 5 termos → 5×200; 15 produtos ativos, nenhum com `bbw` (a coleta pelo catálogo não teria preço por esse campo).
- F13: `/reviews/item` 403 PolicyAgent (continua fechado). F14: pulado (sem `category_id` no produto). F15: 403 forbidden.
- **Critério (Decisão 1 e P4): F8 = 200 ✔, F10 74% ≥ 25% ✔, F11 83% ≥ 80% ✔. G2 aprovado; seguem as etapas 2, 3 e 4.**
- Consequências para a etapa 2: a prova pelo `bbw` fica no código como está no contrato, mas a prova real é pela lista; o 404 no `/items` conta como "sem oferta" e não derruba. Na etapa 3, o `category_id` do `results[]` não é usado.

## Registro das etapas 2 e 3 (2026-11-05, lead)
- Etapa 2 (vínculo e `ml_catalogo.json`): duas rodadas. R1/S1 (o `vincular` engolia o inconclusivo e a renovação com 5xx; agora `RenovacaoFalhou` sai do `Sessao.renovar` e o inconclusivo levanta o erro) e Q1 (lista sem `paging.total` válido não é mais negativo conclusivo) corrigidos. Veredito final: revisor aprovado com ressalvas, qa aprovado, segurança sem bloqueios.
- Etapa 3 (`atualizar_precos.py ml`): rodada 1 sem achado obrigatório. O lead mandou corrigir S1/R5 (reler a linha antes do `upsert`, para não sobrescrever edição feita durante a rodada), R1 (mensagem do teto), R2 ("Nada foi gravado" → "Os tokens não mudaram"), R3 (vínculo para na metade do teto), R4 (`sondar_catalogo` usa `com_teto`) e a leitura dos vínculos antes do banco.
- **Risco aceito (Q1 da etapa 3):** coluna NULL em `CAMPOS` vira `''` pelo `d.get(c) or ''` do `servidor.upsert`. O banco real tem 0 NULL nesses campos, o front trata `''` e NULL igual e o CA8 proíbe mexer no `servidor.py`.
- **Riscos aceitos (S2/S3 da etapa 3, informativas):** sem `flock` no `ml_catalogo.json` (premissa: uma máquina, um comando por vez; o README avisa) e `.tmp` só sobra com SIGKILL.
- O teste `test_ml_api_qa.py::test_nenhum_modulo_do_servidor_ou_do_site_cita_o_ml_api` foi ajustado pelo lead: o `atualizar_precos.py` pode citar `ml_api`/`ACHADINHOS_ML_SECRET` (é a etapa 3), mas continua proibido de citar `ml_tokens`/`ACHADINHOS_ML_TOKENS`.
- Etapa 3, rodada 2 (2026-11-05): um dev foi cortado pelo limite de uso no meio da correção; outro conferiu as edições, corrigiu 2 desvios (marcador `reler` chegando ao `upsert` e texto da mensagem do teto) e escreveu os testes. Veredito final: qa aprovado (56 testes na suíte `_ml_qa`), revisor aprovado com ressalvas, segurança sem bloqueios. R6 (`--max-chamadas` abaixo de 40 não fecha lote) e R7 (textos) vão como texto na etapa 4.
- Etapa 4 (2026-11-05): README da fonte `ml` (CA7). Rodada 1 do revisor com R1 (tempo total do primeiro vínculo: de 7 a 11 h, não 5) e R2 (backup antes dos comandos) e as sugestões R3 a R10; rodada 2 deixou R6 e R10 parciais. O dono autorizou uma conferência curta depois da rodada 2: aprovado. Só texto: nenhum código mudou.
- **Risco aceito pelo dono (05/11, depois da etapa 4):** R3 da segurança, termos de uso do ML para afiliado que usa dados de catálogo (`/products/*`) para atualizar preço; ninguém leu os termos. Mitigações: só leitura, teto de chamadas por rodada, pausa entre chamadas e parada no 429. O R2 da segurança (`code` do OAuth no log da Hostinger) já foi aceito pelo dono em 05/11 (`api-oficial-ml.md`, "Risco aceito pelo dono").

## ADR
**ADR: o preço do ML pelo catálogo, com o vínculo provado por pertença e guardado num cache local.**
- **Contexto:** `/items/*` e `/sites/MLB/search` estão fechados para afiliado. Só o `/products/*` responde, e o banco tem anúncios, não produtos.
- **Decisão:** o título gera candidatos, e o vínculo só vale com o `item_id` no `buy_box_winner` ou em `/products/{id}/items`. O preço é sempre o do próprio anúncio. O vínculo fica em `ml_catalogo.json`, fora do banco.
- **Consequências:** só os anúncios de catálogo ganham preço pela API, e o resto segue no console. O primeiro vínculo é caro (milhares de chamadas, em várias rodadas). Não há migração nem mudança no servidor.
