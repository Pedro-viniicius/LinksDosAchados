# Plano técnico: perfumaria nas três lojas (Shopee como terceira loja, ordenações e 42 termos)
- Brief: não há. Fazem o papel dele o pedido do lead de 2026-11-03 (lista do dono com 20 tipos, nesta ordem) e a spec `docs/produto/specs/shopee-terceira-loja.md`.
- Data: 2026-11-03

## Objetivo e critérios de aceite
Chegar a pelo menos 1.500 itens de perfumaria com link de afiliado, vindos da Amazon, do Mercado Livre e da Shopee, priorizando os mais vendidos, os mais bem avaliados, os mais caros e as boas marcas. Para isso a Shopee entra como terceira loja em todo o sistema. Na lista do dono, "Renner" foi tratado como ruído.

- **CA1 (servidor):** `loja` aceita `shopee`. Um item `shopee` só é gravado (POST e `upsert` direto) com link de afiliado da Shopee, no formato `https://s.shopee.com.br/<código alfanumérico>` (o host final é confirmado no F3). Qualquer outra URL com `loja:'shopee'` dá 400 e o lote inteiro não é gravado. O PATCH de `url` aceita esse link. O `upsert` nunca troca um link da Shopee já gravado. Amazon e ML não mudam.
- **CA2 (disparo):** uma regra pode ter `shopee` em `lojas`. Um item da Shopee só sai com link de afiliado do host da Shopee e com foto do CDN dela. `{LOJA}` vira "Shopee" no `buildMsg` e no `montar_mensagem`, com a paridade provada em `testes/mensagens.test.html`. As regras gravadas continuam `["amazon","ml"]`. A prévia devolve a `loja` de cada item.
- **CA3 (interface):** atende os CA-V1 a CA-V12 da spec `docs/produto/specs/shopee-terceira-loja.md`, sem "Atualizar preço" para a Shopee. Um link colado de domínio desconhecido não vira `amazon` em silêncio: aparece o toast da spec.
- **CA4 (termos):** a aba "Perfumes e Perfumaria" de `buscas.json` tem 42 termos na ordem da tabela "Termos". Os 28 atuais ficam com o texto idêntico, byte a byte. Todos em NFC, sem `|` e sem repetição. O bloco `BUSCAS` do `coletar_ml.js` é igual ao arquivo (o teste existente cobre isso).
- **CA5 (Amazon):** `coletar_amazon.py buscas --cat "<aba>" --ordens vendidos,avaliados,caros` coleta só os termos da aba, com `&s=<valor>`. A relevância mantém a URL e a chave `busca|<termo>` de hoje: nada do que já foi feito é coletado de novo. As outras ordens usam a chave `ordem|<ordem>|<termo>`. `--ordens` sem `--cat` é recusado. O campo `busca` continua sendo o termo.
- **CA6 (ML):** `ColetaML.coletar({termos, ordem:'caros'})` busca a listagem ordenada. Ordem desconhecida é recusada antes de qualquer fetch. O progresso da relevância continua sendo o termo puro (compatível com o `localStorage` atual), e o das outras ordens é `<ordem>|<termo>`.
- **CA7 (Shopee):** `coletar_shopee.py` usa a Open API de afiliados. AppID e Secret vêm só do ambiente, e o Secret nunca aparece em arquivo, stdout, log ou mensagem de erro. Termo e ordem vão como variáveis GraphQL, nunca concatenados na query. As ordens são `relevancia`, `vendidos` e `caros`, com piso de qualidade. O script só grava `offerLink` que passa em `eh_link_afiliado`. Antes de gravar o primeiro termo, confere que o link é do dono (`utm_source=an_<ID>`). Erro de limite para a coleta e preserva o progresso.
- **CA8 (meta):** depois da E9, a aba "Perfumes e Perfumaria" tem pelo menos 1.500 itens, com itens das 3 lojas. `GET /api/ml-sem-afiliado` devolve `[]` e todo item `shopee` passa em `eh_link_afiliado`. A contagem é feita por SQL em modo `ro`.
- **CA9 (docs):** o `README.md` explica as ordens, a Shopee (credenciais, conferência e reversão) e o uso do plugin do Chrome. O lead atualiza o `CLAUDE.md`.
- **CA10:** as suítes da linha de base continuam passando, com só os ajustes listados nas etapas.

## Contexto atual
- **Lojas fixas em dois lugares.** `LOJAS = ('amazon', 'ml')` em `servidor.py:25` e `disparo.py:51`.
  - `eh_link_afiliado` só conhece `meli.la` e a Amazon com a tag (`servidor.py:89-104`). `HOSTS_LOJAS`/`eh_url_de_loja` estão em `servidor.py:107-126`.
  - O lote recusa outra loja (`servidor.py:170-174`). O `upsert` preserva o link com um `CASE` só para meli.la e a tag (`servidor.py:205`). O PATCH de `url` exige afiliado (`servidor.py:488-489`).
- **Disparo.**
  - O padrão da coluna é `lojas DEFAULT '["amazon","ml"]'` (`disparo.py:35`). Não há mudança de esquema: `loja` é TEXT (`servidor.py:59`).
  - A validação fica em `disparo.py:225-227`, `NOMES_LOJA` em `:395`, `link_da_loja_ok` em `:628-632` (mapa loja→host) e `HOSTS_FOTO` em `:59`.
  - `previa` não devolve a `loja` (`disparo.py:800-801`). A fila e o histórico trazem `item_pk`, mas não a loja (`disparo.py:816-820`).
- **Testes que usam `shopee` como loja inválida:** `testes/test_disparo.py:303`, `testes/test_disparo_qa.py:90` e `:906`. O `test_disparo_qa` roda o `buildMsg` do `index.html` real (`:55-57`), então mudar o nome de uma loja sem mudar o outro lado quebra a paridade.
- **Amazon.**
  - A URL hoje é `/s?k=<termo>`, só a página 1, com no máximo `POR_BUSCA=30` (`coletar_amazon.py:14`, `:116-117`).
  - A chave de progresso é `busca|{termo}` (`:83-84`). **Armadilha:** `feitos()` lê toda linha `busca|…` pelo último segmento (`:94`). Por isso uma chave `busca|<termo>|<ordem>` seria lida como o termo "<ordem>". As ordens precisam de outro prefixo.
  - O teste extrai o termo com `split('k=')` (`testes/test_coletar_amazon_qa.py:139`). A URL da relevância precisa ficar igual.
  - A coleta dos 28 termos atuais terminou: 635 itens, só por relevância (informação do lead).
- **ML.** Busca `'/' + slug(termo)` (`coletar_ml.js:540`). O progresso é o termo (`:529`, `:580`), e há no máximo 30 itens por termo (`:45`). O lead está coletando os 28 termos agora, com o código atual e pelo plugin.
- **Front.** Os pontos de mudança estão em `index.html`:
  - `:300` (`#fLoja`), `:317` (`LOJA`), `:379` (`HOSTS_FOTO`), `:468` (selo), `:477` (abrir) e `:481` (atualizar só Amazon);
  - `:519` (contador), `:550` (detecção cai em `amazon`), `:659` (`textoLojas`), `:1131` (padrão) e `:1144-1202` (rádio "Ambas").
  - Testes que usam o rádio: `testes/disparo.test.html:569-571`, `testes/disparo-qa.test.html:541-543` e `testes/disparo-integracao.test.html:158`.
- **Shopee (pesquisa na web, 2026-11-03).**
  - **Links do afiliado.** O link de afiliado é curto (`shope.ee/…` nos documentos antigos, `s.shopee.com.br/…` nos exemplos do Brasil). Ao abrir, ele vira uma URL com `utm_source=an_<ID de afiliado>`, e essa é a forma oficial de conferir o dono (FAQ da Shopee).
  - **Open API.** É GraphQL em `https://open-api.affiliate.shopee.com.br/graphql`, com o cabeçalho `Authorization: SHA256 Credential=<AppID>, Timestamp=<unix>, Signature=sha256(AppID+Timestamp+corpo+Secret)`.
    - `productOfferV2(keyword, sortType, page, limit)` devolve `itemId`, `shopId`, `productName`, `priceMin`, `priceDiscountRate`, `ratingStar`, `sales`, `imageUrl` e `offerLink`.
    - `sortType`: 1 relevância, 2 vendas, 3 maior preço, 4 menor preço, 5 comissão. Não há ordem por nota. O erro 10030 é limite de requisições.
    - **Fontes de terceiros, não verificado** na documentação oficial (ela fica dentro do painel). O F5 confirma.

## Abordagens consideradas (coleta da Shopee)
| Abordagem | Prós | Contras | Risco |
|---|---|---|---|
| A. Open API em `coletar_shopee.py` (Python, só stdlib, mesmo molde do `coletar_amazon.py`) | Sem captcha nem página para reverter. Já devolve `offerLink` de afiliado, vendas, nota e preço. Testável com resposta falsa. Não muda CORS do servidor | Exige o dono aprovado na Open API e um segredo no ambiente | Médio (segredo). Campos não verificados até o F5 |
| B. Script de console na busca da Shopee mais o "Link personalizado" do painel (molde do `coletar_ml.js`) | Atende "pelo navegador" ao pé da letra | A API interna da busca tem assinatura antibot (não verificado). Precisa de descoberta, fixture, 2 origens novas no CORS e afiliação em lote de tamanho desconhecido | Alto (frágil, mais superfície no servidor) |
| C. Plugin lê o DOM da busca e gera os links no painel um a um | Nada de código novo de coleta | Lento para centenas de itens, sem teste, sem repetição confiável | Alto |

## Decisão
- **A para a Shopee.** O plugin do Chrome fica onde ele é necessário: no ML (captcha e linkbuilder logado) e nas conferências do E0.
- Se o dono não tiver ou não conseguir a Open API (P1), a Shopee pelo navegador (B) vira uma **entrega 2**, com descoberta própria. As etapas E1 a E3 continuam valendo, porque preparam a loja.
- As ordens são uma opção nas coletas existentes, não scripts novos. O campo `busca` continua sendo o termo, e a ordem não é gravada (ninguém lê esse dado).
- **Excesso evitado:** sem página 2, sem a ordem por comissão (P5), sem coluna nova e sem migração.
- A meta não depende das ordens. Amazon (635) + ML (28 termos, em andamento) + 14 termos novos já passam de 1.500 com folga (estimativa, não verificado). As ordens servem à prioridade de qualidade pedida pelo dono.

## Esquema e contratos
- **Sem migração.** `items.loja` passa a aceitar `'shopee'`. `item_id` = `"<shopId>.<itemId>"`. `url` = `offerLink`. `busca` = termo.
- **`servidor.py`.**
  - `LOJAS = ('amazon','ml','shopee')`.
  - `HOSTS_AFILIADO_SHOPEE = ('s.shopee.com.br',)`, confirmado no F3. `shope.ee` só entra se o exemplo do dono usar esse host.
  - Em `eh_link_afiliado`, para o host da Shopee, exigir path `^/[A-Za-z0-9]+$`, sem query.
  - `eh_url_de_loja` aceita esses hosts.
  - O lote recusa `loja=='shopee'` sem `eh_link_afiliado` (400, com a mensagem "url da Shopee precisa ser link de afiliado"). `upsert` levanta `ValueError` no mesmo caso.
  - O `CASE` de `:205` também preserva `url LIKE 'https://s.shopee.com.br/%'`.
- **`disparo.py`.**
  - `LOJAS` com `shopee` e `NOMES_LOJA['shopee']='Shopee'`.
  - `link_da_loja_ok` passa a usar um mapa loja→tupla de hosts.
  - `HOSTS_FOTO` recebe o host do CDN da Shopee (F4).
  - A mensagem de validação passa a ser "lojas deve ter amazon, ml e/ou shopee, sem repetir".
  - O dicionário da `previa` ganha `'loja'`.
  - A fila e o histórico pegam a loja no front, por `items.find(i => i.id === e.item_pk)`, sem mudar a API. Se o item foi excluído, o rótulo da loja fica de fora.
- **`coletar_amazon.py`.**
  - `ORDENS = {'relevancia': None, 'vendidos': 'exact-aware-popularity-rank', 'avaliados': 'review-rank', 'caros': 'price-desc-rank'}` (os valores ficam a confirmar no F1).
  - `chave_busca(termo, ordem='relevancia')` → `busca|{termo}` ou `ordem|{ordem}|{termo}`.
  - A CLI vira `buscas [--cat ABA] [--ordens a,b]`, com `argparse`. O padrão continua sendo só a relevância.
- **`coletar_ml.js`.**
  - `ORDENS_ML = {relevancia: '', caros: '_OrderId_PRICE*DESC'}` (F2). O ML não tem "mais vendidos" nem "mais avaliados" na listagem (F2 confirma).
  - A busca usa `'/' + slug(termo) + ORDENS_ML[ordem]`.
  - O progresso guarda `termo` na relevância e `ordem|termo` nas outras ordens. Isso não colide, porque os termos não têm `|`.
- **`coletar_shopee.py`.**
  - **Uso:** `python3 coletar_shopee.py conferir` | `buscas --cat ABA [--ordens relevancia,vendidos,caros]`.
  - **Ambiente:** `ACHADINHOS_SHOPEE_APP_ID` e `ACHADINHOS_SHOPEE_SECRET` (sem eles, sai com código 2 e uma mensagem). `ACHADINHOS_FEITOS_SHOPEE` troca o arquivo de progresso (padrão `coleta_shopee_feitos.txt`, com a chave `<ordem>|<termo>`).
  - **Constante:** `ID_AFILIADO_SHOPEE` (P2; não é segredo, aparece em todo link do dono).
  - **Funções puras testáveis:** `assinar(app_id, ts, corpo, secret)`, `corpo_consulta(termo, sort_type)`, `no_para_item(no, termo, cat)` e `dono_ok(location)`.
  - **Rede:** um único `urlopen` com host fixo, sem variável de ambiente que troque a URL (o Secret iria junto). A conferência usa um opener que **não** segue redirect e lê só o `Location`.
  - **Mapeamento:**
    - `titulo` = `productName`, cortado em 500.
    - `preco` = "R$ 1.234,56" a partir de `priceMin`.
    - `desconto` = `-N%` se `priceDiscountRate` > 0. `preco_antigo` fica vazio, sem preço inventado.
    - `avaliacao` = "4.8 de 5 estrelas" e `vendas` = "N vendidos".
    - `imagem` só se o host estiver em `HOSTS_FOTO`.
  - **Piso de qualidade (P6):** pula `sales == 0` e `ratingStar < 4.5`.
  - **Conferência:** o primeiro `offerLink` da execução precisa dar 3xx com `Location` em `shopee.com.br`, contendo `utm_source=an_<ID>`. Se não der, aborta sem gravar nada. Se o F3 mostrar que não há 3xx, a conferência vira manual (o dono abre 2 links) e o lead registra isso como premissa.

### Termos (aba "Perfumes e Perfumaria", nesta ordem; * = novo)
1 Perfume feminino importado · 2 Perfume masculino importado · 3 Perfume feminino nacional · 4 Perfume masculino nacional · 5 Kit perfume com hidratante* · 6 Kit perfume com desodorante* · 7 Perfume árabe feminino* · 8 Perfume árabe masculino* · 9 Perfume unissex* · 10 Body splash feminino* · 11 Body splash masculino* · 12 Colônia feminina* · 13 Colônia masculina* · 14 Hidratante corporal perfumado · 15 Óleo corporal perfumado* · 16 Desodorante corporal perfumado* · 17 Kit sabonete perfumado* · 18 Perfume para cabelo* · 19 Miniatura de perfume · 20 Kit perfume · 21 Loção pós-barba* · depois os 4 genéricos atuais (Body splash, Desodorante colônia, Perfume árabe, Perfume infantil) e os 17 de marca, na ordem de hoje. Total: 28 atuais + 14 novos = 42. O item 19 do dono ("Miniaturas e kits") é coberto por 19 e 20.

## Etapas
| # | Etapa | Arquivos | Verificação | Responsável | Grupo | Sensível | CAs |
|---|---|---|---|---|---|---|---|
| E0 | Conferir F1 a F5 (ver abaixo) sem escrever código e passar os valores ao `dev` no pacote | nenhum | os valores anotados pelo lead | lead (plugin) + dono | 0 | não | CA1, CA2, CA5-7 |
| E1 | Shopee no servidor: `LOJAS`, `eh_link_afiliado`, `eh_url_de_loja`, recusa no lote e no `upsert`, `CASE` do `upsert`, texto do erro do PATCH, com testes de aceite e recusa (host parecido, query, `http`, porta, path vazio, loja shopee com link da Amazon) | `servidor.py`, `testes/test_servidor.py` | `python3 testes/test_servidor.py -v` e `test_servidor_qa.py` | dev | A | **sim** | CA1, CA10 |
| E2 | Shopee no disparo: `LOJAS`, `NOMES_LOJA`, `link_da_loja_ok` por tupla, `HOSTS_FOTO`, mensagem, `loja` na `previa`. Nos testes, trocar `'shopee'` inválido por `'outra'` e criar testes de regra com shopee e de item shopee com link errado que não sai | `disparo.py`, `testes/test_disparo.py`, `testes/test_disparo_qa.py` | `python3 testes/test_disparo.py -v`, `test_disparo_qa.py` e `test_disparo_servidor.py` | dev | A | **sim** | CA2, CA10 |
| E3 | 42 termos em `buscas.json` e o bloco `BUSCAS` no `coletar_ml.js` (colar o bloco que o teste imprime). Ajustar contagens `[60,19,19,42]` e `PLANO_PERFUMES` no teste do qa | `buscas.json`, `coletar_ml.js` (só o bloco), `testes/test_coletar_amazon_qa.py` | `node --test testes/coletar_ml.test.mjs`, `python3 testes/test_coletar_amazon_qa.py -v`, `test_migrar_categorias*.py` e `test_classificar_lista*.py` | dev | A | não | CA4 |
| E4 | Interface conforme a spec: `LOJA` com shopee usado no filtro, no contador (sem zeros) e em `textoLojas`, `aria-label` do "Abrir na loja", chips de caixa de seleção em `#f-lojas` (padrão: as 3; regra antiga abre como está), erro "Escolha ao menos uma loja.", loja na prévia, na fila e no histórico, placeholder, detecção `s.shopee.com.br` → shopee e domínio desconhecido → toast, `HOSTS_FOTO`. Caso de paridade com loja shopee em `mensagens.test.html` | `index.html`, `testes/disparo.test.html`, `testes/disparo-qa.test.html`, `testes/disparo-integracao.test.html`, `testes/abrir-e-adicionar.test.html`, `testes/mensagens.test.html` | `PORTA=8766 node testes/rodar.mjs` com `disparo`, `disparo-qa`, `abrir-e-adicionar`, `mensagens`, `copiar-imagem` e `abas` (servidor de teste, como no README); `python3 testes/test_disparo_qa.py -v` | dev | B | não | CA3, CA2 |
| E5 | Ordens na Amazon: `ORDENS`, `chave_busca` com ordem, URL `&s=`, `--cat`/`--ordens`. Testes: relevância com URL e chave idênticas às de hoje, progresso antigo sem recoleta, chave `ordem|…`, `--ordens` sem `--cat` recusado, `cat` e `url` preservadas | `coletar_amazon.py`, `testes/test_coletar_amazon.py` | `python3 testes/test_coletar_amazon.py -v` e `test_coletar_amazon_qa.py` | dev | B | não | CA5 |
| E6 | Ordem no ML: opção `ordem`, `ORDENS_ML`, sufixo da URL, chave de progresso. Testes: ordem inválida sem fetch, URL com sufixo, progresso antigo vale para a relevância | `coletar_ml.js`, `testes/coletar_ml.test.mjs` | `node --test testes/coletar_ml.test.mjs` e `coletar_ml_qa.test.mjs` | dev | B | não | CA6 |
| E7 | `coletar_shopee.py` (Open API) e testes com `urlopen` trocado por um falso: assinatura conhecida, query com variáveis, mapeamento, piso, link fora do padrão descartado, conferência boa e ruim (ruim aborta sem gravar), 10030 para com progresso, Secret ausente sai com 2, Secret nunca em stdout/stderr (rodar com um Secret marcador e procurar a string). Mais `coleta_shopee_feitos.txt` no `.gitignore` | `coletar_shopee.py`, `testes/test_coletar_shopee.py`, `.gitignore` | `python3 -m py_compile coletar_shopee.py` e `python3 testes/test_coletar_shopee.py -v`, com proxies mortos | dev | B | **sim** | CA7 |
| E8 | Docs: seções "Ordens da coleta", "Coleta da Shopee" e "Plugin do Chrome" | `README.md` | leitura pelo `revisor` | dev | C | não | CA9 |
| E9 | Coleta real, pelo protocolo abaixo, e contagem final | banco (via scripts) | SQL `ro` por loja na aba e `curl -s localhost:8765/api/ml-sem-afiliado` = `[]` | lead + dono | D | **sim** (dados reais) | CA8 |

- **Dependências.** O grupo A roda antes do B: o E4 precisa do E2 (paridade do `{LOJA}`), e o E7 precisa do E1 (`upsert` com shopee).
- **Verificação do grupo.** Os grupos A e B importam o `servidor.py` nos testes. Rode a verificação de cada grupo só depois que todas as etapas dele terminarem.
- **Docs do lead.** O `CLAUDE.md` fica com o lead, depois do E8.

**E0: fatos a confirmar (só leitura, nada é gravado).**
- **F1:** na busca da Amazon, os valores de `s=` do menu "Classificar por" para "Mais vendidos", "Avaliação média" e "Preço: alto para baixo".
- **F2:** a URL do ML ao escolher "Maior preço", e se existem outras ordens.
- **F3:** um link da Shopee gerado pelo dono no painel. Confira o host e a URL final (`utm_source=an_<ID>`). Depois rode `curl -sI <link>` e veja se a resposta é 3xx com `Location`.
- **F4:** o host do `imageUrl` e se há CORS: `curl -sI -H 'Origin: http://localhost:8765' <imagem>`. Sem `access-control-allow-origin`, o "Copiar imagem" da Shopee falha com a mensagem "rede". É risco aceito: registrar e avisar o `designer`.
- **F5:** o dono confirma, na documentação da Open API dentro do painel, o endpoint BR, a fórmula da assinatura, os `sortType`, o `limit` máximo e os campos `offerLink`, `ratingStar` e `sales`. Se algum fato diferir do plano, o lead ajusta o pacote do `dev`. Se for o caso de B, pare e volte a mim.

**E9: protocolo (fazer backup antes, pela seção "Backup" do README).**
1. **Amazon.** Primeiro numa cópia (8766, com `ACHADINHOS_FEITOS` copiado). Depois no banco real:
   - `python3 coletar_amazon.py buscas --cat "Perfumes e Perfumaria"` (os 14 novos);
   - em seguida, com `--ordens vendidos,avaliados,caros`.
2. **ML, pelo plugin.**
   - Na aba `lista.`, injetar o `coletar_ml.js` e rodar `coletar({termos: <os 14 novos>})` e depois `coletar({termos: ColetaML.BUSCAS['Perfumes e Perfumaria'], ordem: 'caros'})`.
   - Na aba do linkbuilder, rodar `afiliar()`, conferindo antes `achadosmenicas` e "Links curtos".
3. **Shopee, no terminal do dono.** O dono faz `read -rs ACHADINHOS_SHOPEE_SECRET; export ACHADINHOS_SHOPEE_SECRET ACHADINHOS_SHOPEE_APP_ID=<id>` e roda `python3 coletar_shopee.py conferir`. Depois, `buscas --cat "Perfumes e Perfumaria" --ordens relevancia,vendidos,caros`, primeiro na 8766 com 2 termos.
4. **Contagem `ro`** por loja. Se der menos de 1.500, rode os termos que faltam ou mais ordens antes de pensar em página 2.

**Plugin do Chrome (o que o dono faz).**
- Faz login nas três contas de afiliado com a própria senha. O plugin nunca digita senha.
- Deixa abertas `https://lista.mercadolivre.com.br` e `https://www.mercadolivre.com.br/afiliados/linkbuilder`.
- Pega AppID e Secret em `affiliate.shopee.com.br`, **com o plugin desconectado ou fora dessa aba**: o plugin lê a tela, e o Secret iria para a conversa.
- O lead usa o plugin para injetar só o `coletar_ml.js` do repositório, para ler URLs e menus do F1 e do F2 e para conferir 2 ou 3 links gerados.

## Pontos para o seguranca
- **E1 e E2.** O allowlist de afiliado da Shopee precisa ser estrito: host exato, sem query nem porta. Um link curto não prova o dono. A defesa é a origem (API com as credenciais do dono) mais a conferência por `utm_source`. Item `shopee` com link comum nunca entra (lote e `upsert`) e nunca sai (`link_da_loja_ok`).
- **E7.**
  - O Secret fica só no ambiente. Nunca em `repr`, traceback, `argv` ou URL. O erro é impresso só com o tipo e o código da API.
  - O host da API é fixo, sem variável de ambiente que troque a URL.
  - O GraphQL usa variáveis, e o termo nunca é concatenado na query.
  - A conferência não segue redirect e lê só o `Location`.
  - O conteúdo da API é dado não confiável: limite de tamanho e só texto (`conferir_tipos` já existe).
- **Plugin.**
  - Títulos e páginas das lojas podem trazer injeção de prompt. O lead trata o conteúdo lido como dado e nunca segue instrução que venha de uma página.
  - O código injetado é só o `coletar_ml.js` versionado.
  - Nada de plugin na aba que mostra o Secret.
- **E9.** Coleta em dados reais: backup antes, primeiro numa cópia e conferência de afiliado no fim.

## Riscos e como reverter
- **Sem migração.** O código antigo ignora `loja='shopee'` no disparo: `link_da_loja_ok` dá falso. Voltar o código pelo git é seguro.
- **Dados da Shopee indesejados.** Exclua pelo site os itens pontuais. Para tudo, use o backup do E9 com `migrar_categorias.py --restaurar` (ele devolve o banco **inteiro**: números, regras e envios posteriores se perdem).
- **Ordens trazem lixo** (lotes, atacado, contratipo em "caros"). O dono exclui pelo site. Se for muito, o P9 define um teto de preço.
- **Valores de `s=` e o sufixo do ML errados.** O E0 confere. Se a Amazon ignorar o `s=`, só se repetem itens (o `upsert` deduplica), sem dano.
- **Open API recusada (P1).** A Shopee fica para a entrega 2 (B). A meta ainda fecha com Amazon e ML.
- **CORS das fotos da Shopee (F4).** O "Copiar imagem" falha com a mensagem existente, e o disparo continua mandando a URL da foto.
- **Paridade do `{LOJA}` quebrada entre o E2 e o E4.** Nenhum teste usa shopee até o E4, por isso os dois ficam em grupos sequenciais.

## Perguntas em aberto e premissas adotadas
Premissas:
- A chave da loja é `shopee`.
- A Shopee não tem "Atualizar preço".
- As regras antigas continuam com Amazon e ML.
- `item_id` = `shopId.itemId`.
- A ordem não é gravada no item.
- Só a página 1.
- A meta de 1.500 conta a aba inteira, que estava vazia em 2026-11-03.

Perguntas ao dono:
1. Você tem acesso à **Open API** no painel de afiliados da Shopee (menu Open API, com AppID e Secret)? Se não tiver, pode pedir? Sem ela, a Shopee fica para uma segunda entrega, pelo navegador.
2. Qual é o seu **ID de afiliado da Shopee** (Configurações da conta > Informações da conta)? É o número que aparece como `utm_source=an_<ID>` quando o link abre. Não é segredo.
3. Pode mandar **um link de afiliado** que você gerou no painel? Ele confirma o domínio (`s.shopee.com.br` ou `shope.ee`).
4. "**1.500 novos**" conta a aba inteira (hoje 635 da Amazon mais o ML em andamento) ou são 1.500 **além** do que entrou hoje?
5. Quer a **ordem por maior comissão** na Shopee, além de mais vendidos, relevância e mais caros?
6. **Piso de qualidade na Shopee:** nota mínima 4,5 e pelo menos 1 venda está bom?
7. As **regras de disparo atuais** continuam só com Amazon e Mercado Livre, ou devem passar a incluir a Shopee?
8. "**Melhores marcas**": os 17 termos de marca de hoje bastam, ou quer acrescentar outros (ex.: Chanel, YSL, Lancôme Idôle, Boticário Lily, Natura Ekos)?
9. Em "**mais caros**", quer um teto de preço para evitar lotes e atacado?

## ADR
**ADR: Shopee como terceira loja, coletada pela Open API oficial de afiliados.**
- **Contexto.** O dono virou afiliado da Shopee. A regra do dono exige link de afiliado. O link curto da Shopee não identifica o dono pelo formato.
- **Decisão.**
  - `loja='shopee'`, sem migração.
  - Coleta por `coletar_shopee.py` (stdlib, GraphQL assinado), gravando o `offerLink` que a própria API gera para as credenciais do dono.
  - Conferência do dono por `utm_source=an_<ID>` antes de gravar.
  - Secret só no ambiente.
- **Alternativas.** Script de console na busca e no painel, ou o plugin item a item: rejeitadas por fragilidade, falta de teste e mais origens no CORS. Ficam para a entrega 2 se não houver Open API.
- **Consequências.**
  - Primeiro segredo do projeto, que entra em `CLAUDE.md` > Segredos.
  - Primeira API externa autenticada.
  - Nenhuma dependência nova.
  - O servidor não ganha origem CORS.
