---
name: areas-sensiveis
description: Onde mora dado pessoal, entradas, guardas do servidor (Host/Origin/Sec-Fetch-Site, estático fechado) e invariantes do projeto achadinhos
metadata:
  type: project
---

Mapa de superfície (conferido em 2026-11-03, depois do plano blindar-servidor; confira no código antes de usar).

**Dado pessoal**
- `WhatsApp Chat - AmazonLinks/_chat.txt` (e o `.zip`): nome do dono. Fora do git. Desde o blindar-servidor NÃO é servido (estático só `/`, `/index.html`, `/testes/<nome>.test.html`). Não leia o conteúdo; cheque só status.
- `achadinhos.db`: produtos e links de afiliado. Desde o plano disparo-automatico, tabela `numeros` (nome, telefone, grupo_nome, grupo_id) em `disparo.py`: dado pessoal que também vai para todo backup em `backups/`. Testes usam `ACHADINHOS_DB`/`ACHADINHOS_PORTA` com banco temporário.

**Guardas do `servidor.py` (`bloquear()`)**
- Host exato `localhost:<PORTA>`/`127.0.0.1:<PORTA>` (anti rebinding), em todo método.
- `/api/`: Origin local passa; Origin do ML (`lista.` e `www.mercadolivre.com.br`) só GET/POST/PATCH em `ROTAS_ML`; sem Origin, `Sec-Fetch-Site` cross/same-site = 403.
- Caminho cru (sem decodificar) para roteamento; HTTP/1.0 (uma requisição por conexão).
- Corpo: 415 sem `application/json`, 400 JSON inválido; `loja` em `LOJAS`; PATCH `url` só afiliado (`eh_link_afiliado`).
- `/api/fetch`: allowlist https `www.amazon.com.br`, `amazon.com.br`, `amzn.to`, conferida em cada redirect (`RedirecionamentoAmazon`).

**`disparo.py` + rotas `/api/disparo/*` (etapas 1-4 do plano disparo-automatico, revisado em 2026-11-03)**
- Fora de `ROTAS_ML`: origens do ML, preflight, `Origin: null` e `Sec-Fetch-Site: cross-site` dão 403 (testado em servidor próprio). `despachar_disparo()` roda DEPOIS do `bloquear()`; 500 loga só `requestline` + tipo.
- Telefone/`grupo_id` só no corpo e em `numeros`; `GET numeros` devolve inteiro (só origem local); `envios` guarda só `numero_id`. Exceções de validação não repetem valor; `motivo_seguro()` limpa `ErroEnvio`; agendador loga contagens/tipos. Transporte falso (JSONL) só `grupo_nome`/`texto`/`imagem_url`; só por env.
- CA4: `link_da_loja_ok` (host da loja + afiliado) + `it['url'] in msg` + `mensagem_so_com_afiliado(msg, eh_afiliado, url_item)` (análise por token; toda candidata == link do item; `MAX_MENSAGEM` 4000). `processar_slot` roda `_escolher` (`montar_mensagem` com `LIMITE_MONTAGEM`, `MensagemGrande` vira recusado) dentro de `_LOCK` + `BEGIN IMMEDIATE`. Detecção: NFKC + pontos parecidos/ponto médio, Cf lidos como corte e como nada, Mn/Mc no rótulo, IP de 4 rótulos. Tetos de `data` no `conferir_tipos`: título 500, demais 200.
- `criar_banco()` (servidor e `coletar_amazon.py`) roda `disparo.migrar` → banco real vai a `user_version` 1 no próximo start (aditiva).
- Títulos no banco real têm no máximo 223 caracteres (2026-11-03); 14 de 5329 têm `x.yy` tipo "andro.id", "s.amsung".

**Scripts que gravam no banco (desde 2026-11-03, plano eletronicos-e-coleta-ml)**
- `migrar_categorias.py`: só `UPDATE items SET cat, atualizado_em` por parâmetro, dentro de `BEGIN IMMEDIATE`; backup com API `backup` em `<dir do DB>/backups/achadinhos-AAAAMMDD-HHMMSS.db` (coberto por `*.db` no `.gitignore`; com umask 0002 sai 0664). Banco real exige `--sim` ou "sim" no tty (`eh_banco_real` por realpath). Texto do banco sai por `seguro()`; `--restaurar` testa `S.PORT` e, no banco real, também a 8765. `--restaurar` copia o banco INTEIRO (inclui `numeros`/`envios` do disparo).
- `classificar_lista.py` + `lista_whatsapp.json` (etapa 6 do plano disparo-automatico, revisado em 2026-11-03): importa `seguro`/backup/guarda do `migrar_categorias`; `UPDATE items SET cat, busca, atualizado_em WHERE id AND item_id AND cat='Lista WhatsApp'` por parâmetro, replaneja dentro do `BEGIN IMMEDIATE`, confere `rowcount`. JSON: 74 ids amazon (ASIN), só `item_id`/`cat`/`busca`, sem dado pessoal; validado com chave repetida, campos exatos, destino != origem, `item_id` único. `--desfazer` volta só ids do mapa que estão como o mapa deixou para `Lista WhatsApp`/`WhatsApp` (mesmas guardas); é a reversão impressa, `--restaurar` fica como alternativa.
- `coletar_amazon.py`: progresso por termo (`busca|{termo}`), arquivo trocável por `ACHADINHOS_FEITOS`; só grava link com `tag` (exceto ramo antigo do WhatsApp sem ASIN, que grava a URL do chat).
- Para testar: copie o banco com `mode=ro` + `backup` para o scratchpad e use `ACHADINHOS_DB`/`ACHADINHOS_PORTA` (porta livre, nunca 8765).

**`coletar_ml.js` (console do Chrome nas abas do ML; revisado em 2026-11-03)**
- `coletar()` só em `https://lista.`, `afiliar()` só em `https://www.mercadolivre.com.br`; `servidor` só `http://(localhost|127.0.0.1):<porta>`.
- `url` e `imagem` são MONTADAS pelo script (dígitos do MLB; id da foto `[A-Za-z0-9_-]+` em `http2.mlstatic.com`): nada de esquema/host do ML chega ao banco por ele. Texto livre só `titulo`.
- Busca no ML: `fetch('/'+slug)` com `credentials:'include'` (mesma origem); ao servidor: `credentials:'omit'`, sem DELETE.
- Gancho em `fetch`/`XMLHttpRequest.open`/`send` só para URL com `createLink` (lê o corpo do pedido só para a `tag`, que tem que ser `achadosmenicas`); os três são restaurados no `finally` de `afiliar()`. Chamadas ao servidor com `credentials:'omit'` e `referrerPolicy:'no-referrer'`. Mapeamento por MLB (não por ordem). PATCH só `{url}` com `^https://meli\.la/[A-Za-z0-9]+$`.
- `localStorage` da origem do ML: `__coletaML:<servidor>` (termos) e `__afiliarML:<servidor>` (id, mlb, motivo, codigo; só erros de elegibilidade e url sem MLB). Sem dado da conta.
- Testes `testes/coletar_ml.test.mjs`: integração com banco em mkdtemp + porta livre + proxies mortos; fixtures sintéticas.

**Shopee (plano perfumaria-tres-lojas, E1/E2/E7 revisados em 2026-11-03)**
- `servidor.eh_link_shopee`: `re.fullmatch('https://s.shopee.com.br/[A-Za-z0-9]+')` no texto cru; `loja:'shopee'` exige isso no lote (400, lote inteiro) e no `upsert` (ValueError). Desde a rodada 2 (2026-11-03): POST amarra host à loja (`URL_DA_LOJA`), PATCH lê a loja do item (`eh_link_afiliado_da_loja`), `sql_link_preservado()` usa `GLOB` por loja. O `upsert` direto só confere host para shopee (amazon/ml confiam no script). Disparo barra por `HOSTS_LINK_LOJA`.
- `disparo.HOSTS_FOTO` ganhou `down-br.img.susercontent.com` (vale para qualquer loja); a prévia devolve `loja` (front precisa de `esc`).
- `coletar_shopee.py`: primeiro segredo do projeto (`ACHADINHOS_SHOPEE_SECRET`, só env, objeto `Segredo`); `URL_API` fixo; termo como variável GraphQL; `main` imprime só tipo/código; resposta até 2 MB; conferência do dono pelo `Location` (opener sem redirect) e `utm_source=an_<ID>`; `ID_AFILIADO_SHOPEE = '18328801339'` (não é segredo). API e conferência por openers sem redirect (`OPENER_API`, `OPENER_CONFERENCIA`); `credenciais()` faz `os.environ.pop` do Secret; README manda passar o Secret só no comando, sem `export`. Testes trocam `urlopen` e `OPENER_CONFERENCIA.open`; proxies mortos.

**17 abas por nicho (plano abas-nichadas-e-coleta, etapas 1-10 revisadas em 2026-11-04, rodada 1)**
- `servidor.sanear_precos` (`preco_antigo_plausivel`/`ler_preco`, Decimal, regex linear, medido 200k chars < 5 ms): o `upsert` e o PATCH com `data` zeram só `preco_antigo`/`desconto` (url intocada; rodada 2, 2026-11-04).
- `migrar_categorias.py`: ORIGENS = 3 abas antigas; `SUBTEMAS_LISTA`, `DESTINO_SEM_BUSCA`; UPDATE por id com `cat=? AND busca IS ?`; limpeza de preço por id com `preco IS ? AND preco_antigo IS ?`; conferência total/projeção antes do COMMIT; erro sqlite só pelo tipo.
- `coletar_shopee.py importar ARQUIVO`: sem `credenciais()`/env (teste com espião do `os.environ`); arquivo ≤ 2 MB, chaves exatas, 1-100 nós, cat/busca no `buscas.json`; `no_para_item` (eh_link_shopee, conferir_tipos); `conferir_dono` de cada `offerLink` distinto que passou no piso, com `pausa()` entre eles, antes de `criar_banco`/`gravar` (rodada 2, 2026-11-04; GET em `s.shopee.com.br`, sem redirect, sem credencial; `buscas` segue só no 1º, link da Open API); saída só contagens. `VENDAS_MINIMAS` 50.
- Piso nas coletas: `coletar_amazon.passa_piso/eh_usado`, `coletar_ml.js passaPiso/ehUsado` (não mudou url/fetch/afiliar).
- `backups/` inteiro está no `.gitignore` desde 2026-11-04.

**Saídas no front (`index.html`)**
- `innerHTML` com template string; `esc()` escapa `& < > "`. "Copiar imagem": `HOSTS_FOTO` na URL pedida e no `r.url` final.
- Botão "Abrir": só `https:` via `new URL`, com `noopener,noreferrer` (S1 corrigido em 2026-11-03). POST `/api/items` exige `eh_url_de_loja` (https, netloc == host, `HOSTS_LOJAS` + `*.mercadolivre.com.br`); PATCH segue com `eh_link_afiliado`. `coletar_amazon.py` grava por `S.upsert()` direto, sem essa validação (ramo do WhatsApp grava `https?://\S+` do chat).
- Banco em 2026-11-03: toda `url` é `https://meli.la/` (ml) ou `https://www.amazon.com.br/` (amazon); toda `imagem` em `http2.mlstatic.com`/`m.media-amazon.com`.

**API v1 de ofertas (`api_ofertas.py` + `bloquear_v1`/`despachar_v1` no `servidor.py`; plano api-achadinho-turbo, E1/E2 revisadas em 2026-11-03)**
- Primeiro segredo do servidor: token Bearer em `api_token.txt` (`ACHADINHOS_API_TOKEN_ARQUIVO`), no `.gitignore`, lido uma vez no `__main__` (arquivo regular, ≤ 4096 B, ASCII, `[A-Za-z0-9_-]{32,}`; permissão aberta só avisa). Sem token: 503. Estático é allowlist, então o arquivo não é servido.
- Ordem: Host → Origin/`Sec-Fetch-Site` (qualquer valor) 403 → 503 → 401 (`compare_digest` em bytes, um só `Authorization`) → 405. `eh_rota_v1` usa o caminho cru (`/api/v1` ou `/api/v1/...`); variantes (`/api//v1`, `%6F`, `V1`) caem no roteamento antigo e dão 404.
- Log: linha com `/api/v1` passa por `linha_v1_para_log` (query vira `?(omitida)`); 500 loga só o tipo. Conexão com `PRAGMA query_only=1`.
- Sai só `items` (nada de `numeros`/`regras`/`envios`); CA2 via `link_da_loja_ok`, `urls_da_mensagem` em titulo/cupom/cat/busca/item_id, `imagem_permitida(url, loja)`. Medido: ~0,5 s por pedido com 8.380 itens; sem limite de taxa.
- Consumidor: Achadinho Turbo (Node, 3737, outro repo; não acessar). Texto sai cru: o consumidor escapa (no contrato). `api_cabecalho.txt` (cabeçalho com o token, para `curl -H @`) também é segredo e está no `.gitignore`. Testes antigos apontam `ACHADINHOS_API_TOKEN_ARQUIVO` para caminho inexistente.
- Contrato: `docs/produto/referencias/api-ofertas.md` (guia do Turbo manda regerar o link do ML; Shopee segue "como veio").

**Público/gênero (plano genero-nas-categorias, E2-E5 e front revisados em 2026-11-03)**
- `genero.py` puro: gênero derivado na leitura (cat/busca/titulo), regex lineares (medido 500k chars < 0,1 s). Só a correção do dono persiste em `generos_manuais` (`user_version` 2, `CHECK` na lista; `ALTER TABLE regras ADD COLUMN generos`). Gênero de produto, não de pessoa: sem dado pessoal novo.
- `PUT /api/items/<id>/genero` (`ROTA_GENERO`, fora de `ROTAS_ML`; PUT nem está em `METODOS_ML`): testado 403 para ML, preflight, `null`, cross/same-site; corpo só `{"genero"}`; 400 fora da aba com gênero; grava só `generos_manuais` + `items.atualizado_em`. DELETE do item apaga a correção (ids AUTOINCREMENT, sem reuso).
- v1: `genero` calculado no `oferta()` só depois do CA2; filtro aplicado em `_casa`; `MAX_PARES` 32; `G.manuais` é só SELECT (compatível com `query_only`).
- `null` no PUT genero vale em qualquer aba (apaga a correção guardada); valor só na aba com gênero (decisão do lead, rodada 2).
- Etapa 4 (revisada em 2026-11-03): `regras.generos` validada em `validar_regra` (lista de 0 a 4 de `GENEROS`, sem repetir, normalizada; erro sem eco); `elegiveis` filtra só itens de `ABAS_COM_GENERO`, depois do `link_da_loja_ok` (só estreita).
- Front (`index.html`): `GENEROS`/`ABAS_COM_GENERO` espelhados (teste `test_front_constantes.py`); selo, campo e controle "Público" só com constantes + `esc()`; `copiarGenero` aceita só valor de `GENEROS`; `localStorage` `genero:<aba>` validado por `generoEscolhido`; `carregarJson`/estado de erro com texto fixo. `generosDoForm` devolve o `data-original` da regra sem filtrar (já validado pelo servidor, que revalida).
- Origem do ML muda o gênero automático indiretamente (título/busca por POST/PATCH): coberto por R1.

**Invariantes**
- Todo link gravado é de afiliado (Amazon `tag=desejodemen01-20`, ML `meli.la`).
- Servidor só em 127.0.0.1; toda resposta leva `X-Frame-Options: SAMEORIGIN` e `frame-ancestors 'self'` (o teste embute o index.html); sem outra CSP.
- O servidor em 8765 é o REAL: só GET nele.

Ver [[problemas-recorrentes]] e [[riscos-aceitos]].
