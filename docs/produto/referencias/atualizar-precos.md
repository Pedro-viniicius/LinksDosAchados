# Referência: atualização de preços (`atualizar_precos.py` e `ml_api.py`)

Contrato dos módulos, movido do `CLAUDE.md` em 17/11/2026 (plano `docs/produto/planos/endurecer-entrega2.md`, etapa 5). O `CLAUDE.md` guarda o mapa, as armadilhas que cruzam áreas e as regras de segredo, de LGPD e de afiliado, que valem aqui também. As rodadas do dono passam por `operacao/` (veja `docs/produto/referencias/operacao.md`).

## `atualizar_precos.py`

**Regra de negócio.** Plano `docs/produto/planos/atualizar-precos.md`, spec `docs/produto/specs/atualizar-precos.md`.

- Atualiza o preço dos itens que já existem, sem inserir e sem trocar link de afiliado (`servidor.upsert(..., inserir=False)`); `FONTES = {'amazon': fonte_amazon_busca, 'shopee': fonte_shopee_item, 'ml': fonte_ml_catalogo}` (ponto de troca para as APIs oficiais).
- Item sem preço legível não é gravado (mantém os dados).
- Progresso por dia em `atualizar_precos_feitos.txt` (`ACHADINHOS_FEITOS_ATUALIZAR`, no `.gitignore`).

### `amazon`

- `python3 atualizar_precos.py amazon [--cat ABA] [--produtos N]` (busca da Amazon, ~40 min; captcha, 503 ou 429 saem com 3 e retomam; 4 = trava por loja, outra rodada da mesma loja no ar, sem gravar nada).

### `shopee`

Plano `docs/produto/planos/atualizar-precos-shopee-por-item.md`.

- `shopee --cat ABA [--max-chamadas N]` (Open API, uma chamada `productOfferV2(shopId, itemId)` por item, do `preco_em` mais antigo para o mais novo, pausa de 1 a 3 s).
- `--max-chamadas` padrão 1000, máximo 5000; teto e limite da API (10030/429) saem com 3.
- Só `preco`, `preco_antigo` e `desconto` mudam, pela releitura `RELER` como no ML, com commit por item.
- Progresso `shopee|<dia>|item|<shopId>.<itemId>` (produto devolvido) e `shopee|<dia>|tentado|<shopId>.<itemId>` (resposta vazia, só outros produtos ou erro naquele item, gravado antes de seguir ou de parar); os dois pulam o item no dia; tentado desde o último `preco_em` vai para o fim da fila em qualquer dia e não conta para a parada.
- Sem nenhum casado, 5 respostas novas só com outros produtos ou 20 sem o produto pedido saem com 1 ("a API não filtrou pelo item").
- Erro do item marca e segue, erro geral marca e sai com 1.
- `proteger_processo()` antes de ler o Secret, aqui e no `ml`; credenciais só no ambiente do comando, como no `coletar_shopee.py`.
- Os ids vão nas variáveis `Int64` como texto de dígitos, porque número JSON dá 10010.

### `ml`

Plano `docs/produto/planos/api-oficial-ml-catalogo.md`.

- `ml [--cat ABA] [--vincular N] [--max-chamadas N]` (API oficial do ML pelo catálogo).
- `--vincular` padrão 300, máximo 1000; `--max-chamadas` padrão 3000, máximo 10000; pausa de 0,3 a 0,8 s; o vínculo para na metade do teto.
- Preço só da oferta do próprio anúncio.
- Na gravação `_gravar_relendo` relê a linha em `BEGIN IMMEDIATE` e troca só `preco`, `preco_antigo` e `desconto`, com commit por item.
- Teto e 429 saem com 3.
- Tokens do `ml_api.py`, Secret só se precisar renovar.
- Uma máquina por vez: dois `atualizar_precos.py` da mesma loja no mesmo banco não rodam juntos, o segundo sai com **4**, mas o `ml_catalogo.json` não tem trava própria.
- No ML, o console continua valendo para o que não está no catálogo: `ColetaML.atualizar({cat})`.

## `ml_api.py`

**Regra de negócio.** API oficial do Mercado Livre, só leitura, pelo terminal do dono (plano `docs/produto/planos/api-oficial-ml.md`).

- OAuth 2.0 Authorization Code com PKCE S256 (`CLIENT_ID` `3553760734310605`, `REDIRECT_URI` `https://desejodemenina.com/ml/callback`, página estática na Hostinger que só mostra o endereço para o dono colar).
- Tokens em `ml_tokens.json` (`ACHADINHOS_ML_TOKENS`; 0600, escrita atômica, `flock` na renovação, leitura recusa symlink, dono diferente, modo aberto e > 4 KB; `.lock` e `.ml_tokens.json.*.tmp` no `.gitignore`).
- Cliente HTTP só GET em `api.mercadolibre.com` com Bearer no header, sem redirect, teto de 2 MB, uma renovação por 401 por `Sessao`, backoff no 429.
- Subcomandos `autorizar` (cola invisível, via `getpass`), `conferir` (`/users/me`), `sondar` (F0–F6 do plano, só status/códigos/nomes de campo; com `--catalogo [--amostra N] [--semente S]`, F7–F15 do plano `docs/produto/planos/api-oficial-ml-catalogo.md`) e `sair`; saídas 0/1/2/3/130.
- Vínculo anúncio → produto de catálogo só com prova de pertença (`vincular`, `ofertas_do_produto`), em `ml_catalogo.json` (`ACHADINHOS_ML_CATALOGO`; só ids, 0600, escrita atômica, leitura estrita, negativo retentado depois de 7 dias; ele e `.ml_catalogo.json.*.tmp` no `.gitignore`; agentes não o leem nem o criam no projeto; em teste, pasta temporária).
- Não importa `servidor.py`; o servidor e o site nunca veem token.
- O `meli.la` continua vindo só do `ColetaML.afiliar()`.
- A coleta continua no console (`/items/*` e `/reviews` fechados; decisão do dono, P5).

## Histórico

- 06/11/2026: credencial da Shopee liberada; a busca por termo do `atualizar_precos.py shopee` saiu.
- 09/11/2026: o filtro por item foi confirmado no G1 (os ids vão nas variáveis `Int64` como texto de dígitos); na 1ª rodada, 535 de 540 itens voltaram e 378 foram gravados.
