# API de ofertas v1 (Etiqueta para o Achadinho Turbo)

- Plano: `docs/produto/planos/api-achadinho-turbo.md`. Código: `api_ofertas.py` (regra das ofertas) e `servidor.py` (token, guarda HTTP e log).
- Estado descrito aqui: o código final da etapa 2, conferido em 2026-11-03.
- Resumo: duas rotas só de leitura, `GET /api/v1/ofertas` e `GET /api/v1/categorias`, em `http://127.0.0.1:8765` (ou na porta de `ACHADINHOS_PORTA`). Toda oferta sai com **link de afiliado da própria loja**, como está no banco. O consumidor é um processo no mesmo computador (o Achadinho Turbo, em Node), não um navegador.

## Como usar em 1 minuto

```
python3 -c "import secrets; print(secrets.token_urlsafe(32))" > api_token.txt; chmod 600 api_token.txt
# reinicie o servidor.py
{ printf 'Authorization: Bearer '; cat api_token.txt; } > api_cabecalho.txt; chmod 600 api_cabecalho.txt
curl -s -H @api_cabecalho.txt "http://localhost:8765/api/v1/categorias"
```

O `curl` lê o cabeçalho de um arquivo (`-H @arquivo`, curl 7.55 ou mais novo) em vez de receber o token na linha de comando: um `$(cat api_token.txt)` na linha aparece para qualquer usuário no `ps` e no histórico do shell. **O `api_cabecalho.txt` também é segredo** (tem o token): permissão 600, nunca versionar (confira se está no `.gitignore`; se faltar, acrescente) e apague quando não precisar mais. Se trocar o token, gere o arquivo de cabeçalho de novo.

Sem `api_token.txt` (ou com token inválido) a v1 fica desligada e responde 503 (o motivo aparece no terminal do servidor); o resto do Etiqueta funciona normalmente.

## Token

- **Onde:** arquivo `api_token.txt` ao lado do `servidor.py`. `ACHADINHOS_API_TOKEN_ARQUIVO` troca o caminho. O arquivo está no `.gitignore`: nunca vai para o git.
- **Formato:** 32 ou mais caracteres de `A-Z`, `a-z`, `0-9`, `_` e `-`, só ASCII. Os espaços e a quebra de linha das pontas são ignorados. O arquivo precisa ser um arquivo comum (não pasta, nem FIFO) e ter no máximo 4096 bytes.
- **Gerar:** `python3 -c "import secrets; print(secrets.token_urlsafe(32))" > api_token.txt; chmod 600 api_token.txt` (43 caracteres). Qualquer outro gerador serve, desde que respeite o formato.
- **Permissão:** o servidor **não recusa** um arquivo legível por outros usuários, só avisa no terminal ("o arquivo do token pode ser lido por outros usuários"). Use `chmod 600`.
- **Leitura única:** o servidor lê o arquivo uma vez, na subida. Para **trocar** o token, troque o arquivo e **reinicie o `servidor.py`**; depois atualize o valor no consumidor.
- **Para desligar** a API: apague o arquivo e reinicie. A v1 passa a dar 503.
- **Onde vai o token:** só no cabeçalho `Authorization: Bearer <token>` (o esquema `Bearer` vale sem diferenciar maiúsculas). **`?token=` na URL não autentica.** Mais de um cabeçalho `Authorization` dá 401. A comparação é em tempo constante (`hmac.compare_digest`).
- **Nunca** cole o token em conversa de chat, issue, commit, print ou log. O servidor também não o grava: o log de acesso da v1 mostra só o método, a rota e `?(omitida)` no lugar da query, e a mensagem de subida traz só o caminho do arquivo.
- Se o token vazar, gere outro, troque o arquivo, reinicie e atualize o consumidor.

## Guardas, na ordem em que valem

| # | Condição | Resposta |
|---|---|---|
| 1 | `Host` diferente de `localhost:<porta>` ou `127.0.0.1:<porta>` | 403 `host não permitido` |
| 2 | Cabeçalho `Origin` (mesmo a do próprio Etiqueta) ou `Sec-Fetch-Site` presente, que é o que um navegador manda | 403 `a API v1 não aceita pedidos de navegador` |
| 3 | Sem token válido carregado (API desligada) | 503 `a API v1 está desligada: veja o motivo no log do servidor` |
| 4 | Sem `Authorization: Bearer <token>` certo | 401 `token ausente ou inválido: envie Authorization: Bearer <token>`, com `WWW-Authenticate: Bearer` |
| 5 | Método diferente de GET (inclui HEAD e OPTIONS) | 405 `método não permitido: a API só aceita GET`, com `Allow: GET` |
| 6 | Rota que não é `ofertas` nem `categorias` | 404 `rota não encontrada` |
| 7 | Parâmetro inválido | 400 (veja "Erros") |

- **Sem CORS:** nenhuma resposta da v1 leva `Access-Control-Allow-*` e `OPTIONS` não é liberado (dá 401 ou 405, como qualquer método que não seja GET). Uma página aberta no navegador não lê a v1, nem com o token.
- O 405 só aparece depois da autenticação: quem não tem o token vê 401 (ou 503), nunca 405.
- O `fetch` do Node 22 e o `curl` não mandam `Origin` nem `Sec-Fetch-Site`, então passam. Um navegador sempre manda um deles, então é barrado.
- O servidor só escuta em `127.0.0.1`. Esta API **não** foi pensada para a internet (veja "Limites").

## Resposta e formato

- `Content-Type: application/json; charset=utf-8`, com acentos em UTF-8. `Cache-Control: no-store`.
- Toda resposta de sucesso traz `"versao": 1`. Erro é sempre `{"error": "<frase em português>"}`.
- Mudança incompatível exige `/api/v2/`. **Campo novo pode entrar na v1:** o consumidor deve ignorar campo que não conhece.
- **Texto cru:** `titulo`, `busca`, `categoria` e `cupom` saem como foram coletados, sem escape. O consumidor precisa escapar antes de pôr esses campos em HTML (ou em qualquer formato com caracteres especiais).
- Horários (`criado_em`, `atualizado_em`) são texto ISO **local do computador, sem fuso**, com precisão de segundo (`2026-11-03T12:24:23`). Trate como texto.
- Medido em 2026-11-03 com 8.380 itens: cada pedido leva cerca de meio segundo e uma página de 200 ofertas tem cerca de 120 KB. A v1 lê o banco inteiro a cada pedido, então **numa varredura completa use `limite=200`** (o máximo: menos pedidos) e **não faça pedidos em paralelo**.

## `GET /api/v1/ofertas`

Parâmetros (todos opcionais). **A validação é estrita:** parâmetro desconhecido, parâmetro repetido onde não pode, valor vazio onde não pode e valor fora da faixa dão 400. Nenhuma mensagem de erro devolve o valor enviado.

| Parâmetro | Regra |
|---|---|
| `cat` | Nome exato da aba (como em `categorias`). Repetível, até 20; cada um de 1 a 200 caracteres. O mesmo valor duas vezes dá 400. Sem `cat`: todas as abas. Várias: qualquer uma delas. |
| `loja` | `amazon`, `ml` ou `shopee`. Repetível; o mesmo valor duas vezes dá 400. Sem `loja`: as três. |
| `q` | Até 200 caracteres. Vírgula separa até 10 termos; basta **um** aparecer no título, sem diferenciar maiúsculas nem acentos. `q=` vazio ou `a,,b` (termo vazio) dá 400. |
| `desconto_min` | Inteiro de 0 a 99. Filtra pelo `desconto_pct` da própria oferta, que **inclui o desconto calculado pelo preço antigo** (veja a tabela de campos). |
| `ordem` | `atualizacao` (padrão), `relevancia`, `desconto`, `menor_preco`, `maior_preco`, `cupom` ou `recentes`. `aleatoria` (que existe no disparo) dá 400: ela não pagina. |
| `limite` | Inteiro de 1 a 200. Padrão 50. |
| `cursor` | O valor de `proximo` da página anterior, na **mesma ordem**. Opaco: não monte nem altere. Cursor adulterado ou de outra ordem dá 400. |

Mais de 28 pares `nome=valor` no total também dá 400 (`parâmetros demais`). Em `curl`, use `-G --data-urlencode` para acentos e espaços; `+` na query vira espaço.

### Resposta

```json
{"versao": 1,
 "ofertas": [ { "id": 4211, "chave": "amazon:B0G5NZ82TJ", "...": "..." } ],
 "proximo": "2026-11-03T12:36:48~5520",
 "total": 2764}
```

- `ofertas`: a página, na ordem pedida.
- `proximo`: cursor da próxima chamada ou `null` (as regras mudam conforme a ordem; veja "Paginação").
- `total`: quantas ofertas o filtro tem, **sem paginar** (não diminui com o `cursor`). Na ordem `atualizacao` o `total` **já desconta os itens dentro da folga de 60 s**, então pode diferir do `total` de outra ordem no mesmo instante.

### Campos da oferta

| Campo | Tipo | Significado |
|---|---|---|
| `id` | inteiro | Id do item no banco do Etiqueta. Para identificar a oferta, use a `chave`. |
| `chave` | texto | `<loja>:<item_id>`, por exemplo `amazon:B0G5NZ82TJ`. **Use para deduplicar**: é única por oferta e estável. |
| `loja` | texto | `amazon`, `ml` ou `shopee`. |
| `item_id` | texto | Código do produto na loja (ASIN, MLB..., `<shopId>.<itemId>`). |
| `categoria` | texto | Nome da aba do Etiqueta (por exemplo `Perfumes e Perfumaria`). |
| `busca` | texto | Termo de busca que trouxe o item. Pode ser vazio. |
| `titulo` | texto | Título, não vazio. |
| `link` | texto | **Link de afiliado da própria loja**, pronto para usar: Amazon `https://www.amazon.com.br/...?tag=desejodemen01-20`, ML `https://meli.la/...`, Shopee `https://s.shopee.com.br/...`. |
| `imagem` | texto ou `null` | URL da foto, só se for do CDN da loja do item (Amazon `m.media-amazon.com`, ML `http2.mlstatic.com`, Shopee `down-br.img.susercontent.com`); senão `null`. |
| `preco` | número | Preço em reais, maior que 0 (`"R$ 4.285,90"` vira `4285.9`). |
| `preco_antigo` | número ou `null` | Preço cheio. `null` se vazio ou se não for maior que `preco`. A Shopee não tem. |
| `desconto_pct` | inteiro | Desconto em %. Se o texto de desconto da coleta der 0 e houver `preco_antigo`, é `round((1 - preco / preco_antigo) * 100)`. `0` quando não há desconto. |
| `vendas` | inteiro | Vendas da coleta ("Mais de 1 mil compras" vale 1000). `0` quando não há. |
| `avaliacao` | número ou `null` | Nota (por exemplo `4.5`). `null` se não houver. |
| `num_avaliacoes` | inteiro | Quantidade de avaliações. `0` quando não há. |
| `frete_gratis` | booleano | `true` se o texto de frete da coleta contiver "grátis" (sem diferenciar maiúsculas e acentos). |
| `cupom` | texto | Texto do cupom, `""` quando não há. |
| `criado_em` | texto | Quando o item entrou no banco. |
| `atualizado_em` | texto | Última gravação do item (nova coleta, reclassificação). |

### Quando uma oferta NÃO sai

Item que falhar em **qualquer** condição fica fora da lista e do `total`:

- `tem_dados` diferente de 1, loja desconhecida, título vazio, ou preço que não seja um número maior que 0 (por exemplo "consulte"). Hoje há centenas de itens da Amazon sem preço.
- Horário `criado_em` ou `atualizado_em` fora do formato `AAAA-MM-DDTHH:MM:SS`.
- `link` que não seja de afiliado **e** da própria loja (ML sem `meli.la`, Amazon com tag de terceiro, link de outra loja).
- Título, cupom, categoria, busca (ou `item_id`, quando não for o próprio link) com algo que se pareça com um endereço de site. A detecção é a mesma e conservadora do disparo: títulos como `i.Phone` ou `55UN85CBPSA.BWZ` ficam de fora de propósito (algumas dezenas de itens no banco de hoje; 27 na contagem de 03/11/2026).

Não entram na v1: a mensagem pronta (o consumidor monta com o template dele), números de telefone, grupos, regras e histórico de envios do disparo.

## Paginação

**Ordem `atualizacao` (padrão):** por `(atualizado_em, id)` crescente. Há muitos itens com o mesmo `atualizado_em`, por isso o cursor tem os dois: `"<atualizado_em>~<id>"`.

- Só entram itens com `atualizado_em` de pelo menos 60 s atrás (**folga**): as coletas gravam em lotes e o cursor não pode passar por um lote ainda aberto. Item recém-gravado aparece na próxima leitura.
- `proximo` é o cursor da **última oferta da página** e só vem `null` quando a página sai **vazia**. Seguir `proximo` percorre todas as ofertas do filtro uma vez só, sem pular nenhuma; a última chamada, vazia, é a que confirma o fim.
- Item atualizado depois (nova coleta, mudança de aba) volta a aparecer depois do cursor. Deduplique pela `chave`.
- Para pegar **só as novidades**: guarde o último `proximo` **não nulo**; uma resposta vazia com `proximo: null` não apaga o cursor. Na próxima execução, chame com `cursor=<guardado>`; se vier vazia, não há novidade e o cursor guardado continua valendo.
- **Varredura do zero:** um item que passa a ser válido **sem mudar o `atualizado_em`** (por exemplo, mudança na regra de link ou `migrar_categorias.py --restaurar`) não aparece para quem já passou do cursor. Nesses casos, o consumidor faz uma varredura do zero (sem `cursor`) e deduplica pela `chave`.

**Demais ordens:** o resultado é o mesmo de `disparo.ordenar` (as ordens do disparo, com desempate pela ordem de coleta) e o cursor é um **deslocamento** (`"50"`, `"100"`...). `proximo` vem `null` quando não há mais ofertas depois da página.

| Ordem | O que faz |
|---|---|
| `atualizacao` | Mais antigas primeiro por `atualizado_em`, depois `id`. Serve para "novidades desde a última vez". |
| `relevancia` | Mais vendas, depois mais avaliações, depois a nota. |
| `desconto` | Maior desconto em % do texto da coleta primeiro (não usa o desconto calculado pelo preço antigo). |
| `menor_preco` / `maior_preco` | Preço crescente / decrescente. |
| `cupom` | Itens com cupom primeiro, depois o maior desconto. |
| `recentes` | Coletados há menos tempo primeiro (`criado_em`, depois `id`). |

Nas ordens por deslocamento, uma coleta entre duas páginas pode deslocar itens; deduplique pela `chave`.

## `GET /api/v1/categorias`

Não aceita parâmetros (qualquer um dá 400). Conta só as ofertas que passam nas condições acima, em ordem alfabética (sem diferenciar acentos).

```json
{"versao": 1,
 "categorias": [{"nome": "Casa e Decoração", "total": 1089,
                 "lojas": {"amazon": 533, "ml": 556, "shopee": 0}},
                {"nome": "Perfumes e Perfumaria", "total": 2764,
                 "lojas": {"amazon": 2228, "ml": 0, "shopee": 536}}],
 "total": 3853}
```

## Erros

Sempre `{"error": "<frase>"}`. A frase nunca traz o valor que o cliente mandou.

| Código | Quando | Exemplo de frase |
|---|---|---|
| 400 | Parâmetro inválido | `parâmetro desconhecido (use cat, loja, q, desconto_min, ordem, limite, cursor)`; `o parâmetro limite só pode aparecer uma vez`; `loja deve ser amazon, ml, shopee, sem repetir`; `categorias repetidas`; `cada termo de q (separados por vírgula) precisa ter texto`; `desconto_min deve ser um número inteiro de 0 a 99`; `limite deve ser um número inteiro de 1 a 200`; `a ordem aleatoria não existe na API: ela não pagina (use outra ordem)`; `cursor inválido: use o valor de "proximo" da página anterior, com a mesma ordem`; `parâmetros demais`; `a rota categorias não aceita parâmetros` |
| 401 | Token ausente ou errado (`WWW-Authenticate: Bearer`) | `token ausente ou inválido: envie Authorization: Bearer <token>` |
| 403 | `Host` não local; pedido de navegador (`Origin` ou `Sec-Fetch-Site`) | `host não permitido`; `a API v1 não aceita pedidos de navegador` |
| 404 | Rota v1 desconhecida (só depois da autenticação) | `rota não encontrada` |
| 405 | Método diferente de GET, depois da autenticação (`Allow: GET`) | `método não permitido: a API só aceita GET` |
| 500 | Falha inesperada | `erro interno na API v1` (o log do servidor traz só o tipo do erro, nunca a mensagem, que pode trazer dados) |
| 503 | API desligada (sem `api_token.txt` válido) | `a API v1 está desligada: veja o motivo no log do servidor` |

## Exemplos

`curl` (a segunda chamada pagina com o `proximo` da primeira; `-G --data-urlencode` cuida de espaços e acentos):

```
curl -s -H @api_cabecalho.txt "http://localhost:8765/api/v1/categorias"

curl -s -G -H @api_cabecalho.txt \
  --data-urlencode "cat=Perfumes e Perfumaria" -d limite=2 \
  "http://localhost:8765/api/v1/ofertas"

curl -s -G -H @api_cabecalho.txt \
  --data-urlencode "cat=Perfumes e Perfumaria" -d limite=2 \
  --data-urlencode "cursor=2026-11-03T12:36:48~5520" \
  "http://localhost:8765/api/v1/ofertas"

curl -s -G -H @api_cabecalho.txt \
  -d loja=shopee -d ordem=desconto -d desconto_min=30 -d limite=10 \
  "http://localhost:8765/api/v1/ofertas"
```

Node 22 (`fetch` nativo; sem dependência):

```js
const token = (await readFile('api_token.txt', 'utf8')).trim();   // import { readFile } from 'node:fs/promises'
const url = new URL('http://127.0.0.1:8765/api/v1/ofertas');
url.searchParams.append('cat', 'Perfumes e Perfumaria');
url.searchParams.set('limite', '50');
const r = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
const { ofertas, proximo, total } = await r.json();
```

## Limites

- **Sem limite de taxa.** Um consumidor local, com token. Se um dia a API sair do computador do dono (VPS), isso e o HTTPS passam a ser requisito.
- **O token não protege mais que hoje contra outro processo no mesmo computador:** `GET /api/items` (a API da interface) continua aberto a quem não manda `Origin`. O que a v1 ganha é barrar o navegador e ter o contrato pronto para o dia em que o consumidor estiver em outra máquina.
- **Item apagado some sem aviso:** a API só lista o que existe agora. O consumidor relê a lista a cada execução.
- **Reclassificar abas** (`migrar_categorias.py`, `classificar_lista.py`) regrava `atualizado_em` de muitos itens; eles reaparecem na ordem `atualizacao`. É esperado: a `chave` evita repetir o envio.
- Não existe `GET /api/v1/ofertas/<id>` (rota desconhecida dá 404).

## Guia de encaixe no Achadinho Turbo

Sugestão, sem código, para a sessão que cuida do Turbo. **Este repositório não edita o Turbo.** As linhas citadas são de `/home/ufla/Documentos/achadinhoturbo` em 2026-11-03 e podem mudar (outra sessão edita esses arquivos).

**Nome:** no Turbo, "etiqueta" quer dizer a etiqueta de afiliado do Mercado Livre. Chame a fonte nova de **`catalogo`** ("Catálogo do Etiqueta"), para não colidir.

**Fonte e conexão**
- Novo tipo de fonte `catalogo` em `candidatesFor` (`src/ml.js`, hoje `:298`) e na validação de tipos da regra (`src/server.js`, `tipo()`), ao lado de `afiliados`, `search` e `list`. A fonte chama `GET /api/v1/ofertas` com os filtros da regra (`cat`, `loja`, `q`, `desconto_min`, `ordem`, `limite`).
- Conexão nova com o endereço `http://127.0.0.1:8765` e o token como **segredo** (campo `segredo` em `PLATAFORMAS`, `src/lojas.js`, e `conexoes.segredos`, que o Turbo nunca devolve ao navegador). Trocar o token: troque o arquivo, reinicie o Etiqueta e atualize em Conexões.
- Só `fetch` em `127.0.0.1` com `Authorization`: sem `Origin`, passa na guarda.

**Mapeamento para o formato do `renderTemplate`** (`src/template.js:36-49`, `src/ml.js:228-238`)

| Turbo | Etiqueta (v1) |
|---|---|
| `key` | `chave` |
| `title` | `titulo` |
| `url` | `link` |
| `price` | `preco` |
| `oldPrice` | `preco_antigo` |
| `discountPct` | `desconto_pct` |
| `sold` | `vendas` |
| `freeShipping` | `frete_gratis` |
| `coupon` | `cupom` |
| `image` | `imagem` |

Mandar `desconto_pct` sempre preenchido evita que o Turbo apague o desconto em `discountPct ?? ...` (`src/template.js:37`).

**Deduplicação:** por `chave` em `sent_offers`, como o Turbo já faz (`src/scheduler.js:58-61,132`). Um candidato que já traz `title` e `price` não é resolvido de novo (`src/ml.js:254-256`).

**Dois modos de consumo**
- **Novidades desde a última execução** (ordem `atualizacao`): guarde o último `proximo` **não nulo** por regra (resposta vazia com `proximo: null` não apaga o cursor) e volte com `cursor`; veja "Paginação". Custa uma chamada extra, vazia, no fim. Depois de `--restaurar` ou de mudança na regra de link, faça uma varredura do zero com `limite=200`.
- **As melhores por execução** (`relevancia`, `desconto`, `menor_preco`, ...): pagine por `proximo` até achar `per_run` ofertas ainda não enviadas dentro do prazo de repetição; sem isso a fonte "seca" depois de 200 envios.

**Os três ajustes do lado do Turbo**
1. `src/scheduler.js:99`: a regra exige etiqueta do ML (`escolha uma etiqueta`). Em regra de catálogo só com Amazon e/ou Shopee, dispense a etiqueta; se a regra incluir o ML, ela continua precisando (veja o ajuste 2).
2. `src/scheduler.js:113`: o link é sempre gerado de novo pela extensão (`links.requestLink({ url: offer.url, tag: etq.name })`). Para a fonte `catalogo`:
   - **Amazon:** use o `link` como veio, **sem `requestLink`**. A tag `desejodemen01-20` é conferida pelo Etiqueta. Trocá-lo por um link comum quebra a regra do dono.
   - **Shopee:** use o `link` como veio, mas **revise antes de enviar** (ou envie só itens que você mesmo coletou). O link curto `https://s.shopee.com.br/<código>` não prova de quem é a conta; o Etiqueta só confere o formato, e um item plantado no banco com link de terceiro passaria.
   - **Mercado Livre: regere o link com a etiqueta do dono** (`requestLink` com a etiqueta `achadosmenicas`) ou revise os links antes de enviar. O Etiqueta só confere o **formato** (`https://meli.la/<código>`), não de quem é a etiqueta: um link de afiliado de terceiro plantado no banco passaria. Não use o `link` do ML às cegas.
3. `src/scheduler.js:121`: a foto só sai se for do CDN do ML (`IMAGEM_PERMITIDA`, `src/ml.js:31`). Libere também os CDNs da Amazon e da Shopee, que são os que a `imagem` da v1 pode trazer (o `src/lojas.js` já tem `IMAGEM_AMAZON` e `IMAGEM_SHOPEE`).

**Shopee:** as regras automáticas do Turbo hoje só enviam ML e Amazon. Os cerca de 540 itens da Shopee saem na API, mas só serão enviados quando o Turbo tiver suporte à Shopee. Até lá, filtre com `loja=amazon&loja=ml` na regra.

**Se o Turbo for para uma VPS:** o pull não alcança o `localhost` do dono. O caminho previsto é um script de saída que empurra o mesmo JSON para um endpoint HTTPS do Turbo, com token. O formato da oferta foi pensado para isso.
