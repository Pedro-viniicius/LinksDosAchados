# Plano técnico: API de ofertas para o Achadinho Turbo
- Brief: não há. Vale o pedido literal do dono, repassado pelo lead: "Agora quero que você faça uma API para eu alimentar meu outro serviço chamado achadinhos turbo".
- Data: 2026-11-03

## Objetivo e critérios de aceite
Expor, só para leitura, as ofertas do Etiqueta (sempre com link de afiliado) numa API versionada que o Achadinho Turbo (Node, porta 3737, mesmo computador) consulta. O entregável é o lado do Etiqueta mais um contrato escrito. O consumidor no Turbo fica para a outra sessão.

- CA1 — Com token válido, `GET /api/v1/ofertas` responde 200 com `{versao: 1, ofertas: [...], proximo, total}`. Cada oferta segue o formato de "Esquema e contratos", com os mesmos nomes e tipos.
- CA2 — Uma oferta só sai se cumprir todas as condições abaixo. Item que falhar em qualquer uma fica fora da lista e da contagem.
  - Tem `tem_dados=1`, título e preço numérico maior que 0.
  - `link` é de afiliado e da própria loja (`disparo.link_da_loja_ok`).
  - Título e cupom não têm nenhuma candidata a link (`disparo.urls_da_mensagem`).
  - Além disso, `imagem` só sai se for do CDN da loja; senão vai `null`. Nenhum outro URL aparece no corpo.
- CA3 — Os filtros `cat` (repetível), `loja` (repetível), `q` e `desconto_min` funcionam. `limite` vale 50 por padrão e 200 no máximo. Parâmetro desconhecido, repetido onde não pode ou com valor inválido dá 400 com mensagem em português.
- CA4 — Paginação:
  - Na ordem padrão `atualizacao` (por `atualizado_em, id`), seguir `proximo` até `null` percorre todas as ofertas do filtro uma vez só, sem pular nenhuma.
  - Item gravado há menos de 60 s fica para a próxima leitura (folga).
  - Item atualizado depois volta a aparecer depois do cursor.
  - As ordens `relevancia`, `desconto`, `menor_preco`, `maior_preco`, `cupom` e `recentes` dão o mesmo resultado de `disparo.ordenar` e paginam por deslocamento. `aleatoria` dá 400.
- CA5 — `GET /api/v1/categorias` responde `{versao: 1, categorias: [{nome, total, lojas: {amazon, ml, shopee}}], total}`, contando só as ofertas que passam no CA2.
- CA6 — Autenticação:
  - Sem arquivo de token, ou com token inválido (menos de 32 caracteres ou fora de `[A-Za-z0-9_-]`), toda rota `/api/v1/` responde 503 e o servidor sobe normalmente.
  - Sem `Authorization: Bearer <token>`, ou com o token errado, a resposta é 401 com `WWW-Authenticate: Bearer`.
  - A comparação usa `hmac.compare_digest`.
  - O token nunca aparece em log, resposta ou query string. `?token=` não autentica.
- CA7 — Navegador barrado:
  - Rota v1 com `Origin` (até a local) ou `Sec-Fetch-Site` dá 403.
  - Nenhuma resposta v1 leva `Access-Control-Allow-*`.
  - Método diferente de GET dá 405, só depois da autenticação.
  - O `Host` continua obrigatório: `localhost` ou `127.0.0.1` com a porta.
- CA8 — O cliente real passa: `fetch` do Node 22 com Bearer em `http://127.0.0.1:<porta>/api/v1/categorias` recebe 200.
- CA9 — Nada muda fora da v1:
  - As suítes existentes passam.
  - A v1 não grava no banco.
  - Não há migração.
  - A primeira linha do stdout do servidor continua igual (os testes dependem dela).
- CA10 — A documentação acompanha:
  - O contrato fica em `docs/produto/referencias/api-ofertas.md`, com rotas, campos, erros, cursor, token e o guia de encaixe no Turbo.
  - O `README.md` explica como criar o token e traz um exemplo com `curl`.
  - O `CLAUDE.md` passa a citar `api_ofertas.py`, a rota v1, o segredo `api_token.txt` e os novos comandos de teste.

## Contexto atual
**Etiqueta**
- O servidor ouve só em `127.0.0.1` (`servidor.py:630`). O `bloquear()` (`servidor.py:373-400`) exige `Host` local. Na `/api/`, aceita Origin local, as origens do ML (só nas rotas da coleta) ou nenhuma Origin com `Sec-Fetch-Site` que não seja cross-site nem same-site. Ou seja, **um processo local sem Origin já lê `GET /api/items` sem token** (`servidor.py:497-501`). É o risco aceito R1 (`.claude/agent-memory/seguranca/riscos-aceitos.md:8`).
- `GET /api/items` devolve tudo, no formato `linha_para_item` (`servidor.py:87-90`): os textos crus da coleta, como "R$ 4.285", "Mais de 300 compras" e "Frete GRÁTIS".
- `eh_link_afiliado` está em `servidor.py:93-111`. O despacho do disparo, um módulo à parte importado sob demanda e sem importar `servidor`, está em `servidor.py:433-461`. **É o padrão a seguir.**
- `disparo.py` já tem o que a API precisa:
  - `link_da_loja_ok` (`disparo.py:640`), `imagem_permitida` (`:648`) e `urls_da_mensagem` (`:583`), que é conservadora e recusa os 14 títulos tipo `i.Phone`.
  - `pct` (`:665`), `preco_num` (`:671`), `contagem` (`:678`), `nota` (`:693`), `_sem_acento` (`:661`) e `ordenar` (`:754`).
  - O filtro `titulo!='' AND preco!=''` de `elegiveis` (`:731-733`).
  - `recentes` usa `criado_em` porque as migrações regravam `atualizado_em` (`:768-770`).
- No banco real, consultado só em leitura em 2026-11-03, há 8.380 itens, todos com link de afiliado da própria loja. 353 itens da Amazon estão sem preço. 5.329 itens têm o mesmo `atualizado_em` (2026-11-03T12:24:23), que é texto ISO local, sem fuso, com precisão de segundo. **Os empates são normais**, então o cursor precisa de `(atualizado_em, id)`. Há só os índices `ix_items_cat` e UNIQUE(loja, item_id).
- As coletas fazem commit por lote (`coletar_amazon.py:85-90`, `coletar_shopee.py:367-375`), em segundos.
- O `.gitignore` não tem regra para o arquivo de token.

**Achadinho Turbo** (lido em 2026-11-03; outra sessão está editando esses arquivos agora, então as linhas podem mudar)
- A oferta de uma regra é `{key, url, title, price (número), oldPrice, coupon, discountPct, sold (número), freeShipping (bool), image}` (`src/ml.js:228-238`, `src/template.js:36-49`). Quem consome isso é o `renderTemplate`.
- As fontes de uma regra vêm de `candidatesFor({type, config})`, com os tipos `afiliados`, `search` e `list` (`src/ml.js:298-315`, `src/server.js:425-443`), e são deduplicadas por `key` em `sent_offers` (`src/scheduler.js:58-61,132`). Um candidato com `title` e `price` não é resolvido de novo (`src/ml.js:254-256`).
- Três detalhes do agendador:
  - A regra exige etiqueta do ML (`src/scheduler.js:99`).
  - O link sempre é regerado pela extensão (`:113`).
  - A foto só sai do CDN do ML (`IMAGEM_PERMITIDA`, `src/ml.js:30`, usado em `src/scheduler.js:121`).
- O Turbo guarda credenciais de loja em `conexoes.segredos`, sem devolvê-las ao navegador (`src/conexoes.js:1-20`, `src/lojas.js:34-99`).
- **Colisão de nome:** no Turbo, "etiqueta" quer dizer a etiqueta de afiliado do ML.

## Abordagens consideradas
| Abordagem | Prós | Contras | Risco |
|---|---|---|---|
| **A. Turbo puxa** (`GET /api/v1/...` no Etiqueta) | O Etiqueta fica sem estado. Encaixa num novo tipo de fonte do `candidatesFor`. Os dados chegam frescos a cada execução da regra. Nada muda no Turbo agora. | O Etiqueta precisa estar no ar quando a regra roda. Se o Turbo um dia for para uma VPS, não alcança o `localhost` do dono. | Baixo |
| B. Etiqueta empurra (POST num endpoint do Turbo) | Funciona com o Turbo numa VPS, porque a saída atravessa NAT. | Exige estado no Etiqueta (o que já foi enviado), credencial do Turbo aqui e endpoint e tabela novos no Turbo, que está sendo editado por outra sessão. | Médio |
| C. Turbo lê o `achadinhos.db` direto | Não precisa de código de API. | Acopla ao esquema interno e pula a regra de afiliado e a detecção de links. O banco está em WAL, em outro processo. | Alto |

Para a autenticação, comparei três opções:
- **Token Bearer num arquivo fora do git.** É a recomendada.
- Sem token, só barrando navegador. Hoje protege quase o mesmo (veja R1), mas o contrato teria de mudar quando a VPS vier.
- Token na tabela `config`. Descartada: `GET /api/config/<chave>` devolveria o token.

## Decisão
- **A (pull)**, numa rota nova e só de leitura: `/api/v1/ofertas` e `/api/v1/categorias`.
- A lógica fica num módulo novo, `api_ofertas.py`, que **não importa `servidor`** (mesmo padrão do `disparo.py`) e reaproveita as funções do `disparo.py` citadas acima.
- A guarda HTTP e o token ficam no `servidor.py`.
- O formato da oferta é versionado e independe do transporte. Se a VPS vier, o mesmo JSON pode ser empurrado (abordagem B) sem mudar o consumidor de dados.
- **A mensagem pronta não entra na v1.** O Turbo tem templates próprios (`{TITULO_COMPLETO}`, trechos `[...]`, título abreviado), e o `config/templates` do Etiqueta pode estar vazio. Por isso a API entrega campos normalizados em número, que é o que o `renderTemplate` do Turbo consome.
- **Sem estado de consumidor no Etiqueta.** O Turbo deduplica pela `chave` no `sent_offers`, como já faz. Quem quiser só novidades guarda o último `proximo`.
- **Excesso de engenharia, olhando o próprio plano:** se o dono só quiser "as melhores N por execução", dá para cortar a ordem `atualizacao` e o cursor composto (CA4, primeira parte). O contrário também vale. Mantive as duas ordens porque o lead pediu o cursor e porque o caso "por execução" precisa de paginação para não secar depois de 200 envios dentro do prazo de repetição.

## Esquema e contratos
Não há migração nem tabela nova. Nada é gravado.

**Token**
- O arquivo é `ACHADINHOS_API_TOKEN_ARQUIVO`. O padrão é `api_token.txt` ao lado do `servidor.py`, e ele entra no `.gitignore`.
- O servidor lê o arquivo uma vez no `__main__` e tira os espaços. Para trocar o token, troque o arquivo e reinicie o servidor.
- O servidor registra no stderr só "API v1 ligada" ou "API v1 desligada: <motivo>" com o caminho, **nunca o token**. Se o arquivo puder ser lido por grupo ou outros (`mode & 0o077`), ele só avisa.
- Para gerar: `python3 -c "import secrets;print(secrets.token_urlsafe(32))" > api_token.txt && chmod 600 api_token.txt`.

**`GET /api/v1/ofertas`**

| Parâmetro | Regra |
|---|---|
| `cat` | Repetível, até 20, cada um com até 200 caracteres. Nome exato da aba. |
| `loja` | Repetível. `amazon`, `ml` ou `shopee`. |
| `q` | Até 200 caracteres. Vírgula separa até 10 termos. Basta um termo aparecer no título, sem diferenciar caixa e acento (mesma semântica de `regra.palavras`). |
| `desconto_min` | De 0 a 99. |
| `ordem` | `atualizacao` (padrão), `relevancia`, `desconto`, `menor_preco`, `maior_preco`, `cupom` ou `recentes`. |
| `limite` | De 1 a 200. O padrão é 50. |
| `cursor` | O valor de `proximo` da página anterior. É opaco para o cliente. |

- Hoje o `proximo` é `"<atualizado_em>~<id>"` na ordem `atualizacao` e `"<deslocamento>"` nas demais. O servidor confere o cursor com regex ancorada e devolve 400 se não bater com a `ordem`.
- Na ordem `atualizacao`, entra só item com `atualizado_em <= agora - 60 s` e `(atualizado_em, id)` maior que o cursor.

Resposta: `{"versao": 1, "ofertas": [...], "proximo": "..." | null, "total": <quantas o filtro tem, sem paginar>}`. Cada oferta:
```json
{"id": 4211, "chave": "amazon:B0G5NZ82TJ", "loja": "amazon", "item_id": "B0G5NZ82TJ",
 "categoria": "Perfumes e Perfumaria", "busca": "perfume importado", "titulo": "…",
 "link": "https://www.amazon.com.br/dp/B0G5NZ82TJ?tag=desejodemen01-20",
 "imagem": "https://m.media-amazon.com/…" , "preco": 523.99, "preco_antigo": 929.0,
 "desconto_pct": 44, "vendas": 50, "avaliacao": 4.5, "num_avaliacoes": 7000,
 "frete_gratis": false, "cupom": "", "criado_em": "2026-11-03T12:24:23", "atualizado_em": "2026-11-03T12:24:23"}
```

| Campo | Como é calculado |
|---|---|
| `preco` | `preco_num`. Item com 0 fica fora. |
| `preco_antigo` | `null` se for vazio ou não for maior que `preco`. |
| `desconto_pct` | `pct(desconto)`. Se der 0 e houver `preco_antigo`, `round((1 - preco/preco_antigo)*100)`. O Turbo usa `discountPct ?? …` (`src/template.js:37`), e mandar 0 apagaria o desconto. |
| `vendas` | `contagem(vendas)`. |
| `avaliacao` | `nota()`. `null` se der 0. |
| `num_avaliacoes` | `contagem()`. |
| `frete_gratis` | Verdadeiro se o texto contiver "grátis", sem diferenciar caixa e acento. |
| `imagem` | `null` se não passar em `imagem_permitida(url, loja)`. |

Os horários são ISO local sem fuso. Trate como texto.

**`GET /api/v1/categorias`**: `{"versao": 1, "total": n, "categorias": [{"nome": "...", "total": n, "lojas": {"amazon": n, "ml": n, "shopee": n}}]}`, em ordem alfabética.

**Erros:** sempre `{"error": "<frase>"}`.

| Código | Quando |
|---|---|
| 400 | Parâmetro inválido |
| 401 | Token ausente ou errado |
| 403 | Host, Origin ou Sec-Fetch-Site |
| 404 | Rota v1 desconhecida |
| 405 | Método |
| 503 | API desligada |

**Assinaturas novas**
- `api_ofertas.py`:
  - `ErroApi(codigo, msg)`
  - `oferta(row, eh_afiliado) -> dict | None`
  - `filtros(pares) -> dict`, onde `pares` é a lista do `parse_qsl`, para poder detectar repetição
  - `listar(con, filtros, eh_afiliado, agora) -> dict`
  - `categorias(con, eh_afiliado) -> dict`
  - `rota(con, metodo, caminho, pares, eh_afiliado, agora=None) -> dict`
- `servidor.py`:
  - `API_TOKEN` (global, preenchido no `__main__`)
  - `carregar_token_api(caminho) -> (token | None, motivo)`
  - `Handler.bloquear_v1()`, chamado de dentro do `bloquear()` logo depois da checagem de Host
  - `Handler.despachar_v1()`, no `do_GET`

## Etapas
| # | Etapa | Arquivos | Verificação | Responsável | Grupo | Sensível | CAs |
|---|---|---|---|---|---|---|---|
| 1 | Criar o módulo `api_ofertas.py`: serialização da oferta (CA2, com conferência de link e imagem e campos numéricos), validação estrita dos parâmetros, as duas paginações com folga de 60 s, categorias e `rota`. Os testes unitários usam banco temporário (sqlite em `tempfile`, com o esquema de `servidor.criar_banco` e `ACHADINHOS_DB` definido antes do import). Casos obrigatórios: título `i.Phone` fora; ML com URL comum fora; Amazon com tag de terceiro fora; imagem de host estranho vira `null`; empate de `atualizado_em` sem pular nenhum item; item atualizado reaparece; cursor adulterado dá 400; `aleatoria` dá 400; paridade com `disparo.ordenar`. | `api_ofertas.py`, `testes/test_api_ofertas.py` | `python3 -m py_compile api_ofertas.py && python3 testes/test_api_ofertas.py -v` | dev | A | sim | CA1, CA2, CA3, CA4, CA5, CA9 |
| 2 | Ligar a v1 no servidor. No `servidor.py`: `carregar_token_api` no `__main__`, depois do `print` da primeira linha; `bloquear_v1`, com Origin ou Sec-Fetch-Site dando 403, API desligada dando 503, Bearer conferido com `compare_digest` dando 401 com `WWW-Authenticate`, e método diferente de GET dando 405; e `despachar_v1`, que delega a `api_ofertas.rota` com import sob demanda e devolve 500 genérico com só o tipo do erro no log. No `.gitignore`, a linha `api_token.txt`. Testes HTTP em subprocesso, no padrão de `ServidorDisparo` (`testes/test_disparo_servidor.py:47-70`): `setUpClass` e `env` próprios, `ACHADINHOS_API_TOKEN_ARQUIVO` num arquivo temporário e proxies mortos. Eles cobrem 503, 401 (sem token, token errado, `?token=`), 403 (Origin local, Origin do ML, Sec-Fetch-Site), 405, ausência de CORS e o token ausente do stderr. Teste Node no padrão de `testes/coletar_ml.test.mjs` com `fetch` real. | `servidor.py`, `.gitignore`, `testes/test_api_ofertas_servidor.py`, `testes/api_ofertas.test.mjs` | `python3 testes/test_api_ofertas_servidor.py -v && node --test testes/api_ofertas.test.mjs && python3 testes/test_servidor.py -v && python3 testes/test_disparo_servidor.py -v` | dev | B | sim | CA6, CA7, CA8, CA9 |
| 3 | Escrever a documentação. **Contrato:** `docs/produto/referencias/api-ofertas.md`, com rotas, tabela de campos, erros, cursor, token e rotação. **Guia de encaixe no Turbo** (seção do contrato, sem código):<br>- fonte nova `catalogo` ("Catálogo do Etiqueta"; não chame de "etiqueta") em `candidatesFor` e em `tipo()`;<br>- conexão com endereço `http://127.0.0.1:8765` e token como `segredo` em `PLATAFORMAS`;<br>- mapeamento `title←titulo`, `price←preco`, `oldPrice←preco_antigo`, `discountPct←desconto_pct`, `sold←vendas`, `freeShipping←frete_gratis`, `coupon←cupom`, `image←imagem`, `key←chave`;<br>- usar `link` como veio, sem `requestLink`;<br>- liberar a foto dos CDNs da Amazon e da Shopee;<br>- dispensar a etiqueta do ML em regra só de catálogo.<br>**README:** seção "API para o Achadinho Turbo" com geração do token, reinício e `curl -H "Authorization: Bearer $(cat api_token.txt)" "http://127.0.0.1:8765/api/v1/ofertas?cat=Perfumes%20e%20Perfumaria&limite=2"`. **CLAUDE.md:** camadas, segredos, lista do `py_compile` e testes. | `docs/produto/referencias/api-ofertas.md`, `README.md`, `CLAUDE.md` | Rodar o `curl` do README contra o servidor de teste (cópia do banco por `sqlite3` backup, `ACHADINHOS_PORTA=8766` e token temporário) e conferir que os campos batem com a tabela do contrato. `grep -n api_token.txt .gitignore CLAUDE.md README.md` | dev | C | não | CA10 |

- A ordem é A → B → C. A etapa 2 chama `api_ofertas.rota`, e a 3 documenta o comportamento final.
- Não há duas etapas no mesmo grupo.
- Os testes de QA (`testes/test_api_ofertas_qa.py`) ficam com o `qa` no fluxo padrão.

## Pontos para o seguranca
- **O token não protege mais que hoje contra processo local.** `GET /api/items` continua aberto a quem não manda Origin (R1). Na máquina local, o ganho real é barrar navegador na v1 e ter o contrato pronto para uma VPS. Confirme se R1 continua aceito.
- Conferir os pontos da autenticação:
  - token só no header;
  - `compare_digest` sobre bytes;
  - 401 antes de 405;
  - token fora de todo log, já que `log_message` registra a linha da requisição com a query;
  - arquivo com permissão 600, avisando se estiver mais aberto;
  - API desligada por padrão.
- A v1 recusa toda requisição com `Origin` ou `Sec-Fetch-Site`. **Não verificado:** se o `fetch` do Node 22 (undici) manda `Sec-Fetch-Mode`. Isso não importa, porque só o `Sec-Fetch-Site` barra. O CA8 prova o caminho real.
- Os parâmetros entram no SQL só como bind. A validação usa regex ancorada e linear. O custo por pedido é uma varredura de cerca de 8 mil linhas mais `urls_da_mensagem` por item: medir o tempo com o banco copiado e aceitar se ficar abaixo de 1 s. **Não há limite de taxa:** um consumidor local, com token. Isso vira requisito numa VPS.
- Nenhum dado pessoal sai: `numeros`, `regras` e `envios` ficam fora da v1.
- O link de afiliado sai em claro, como deve sair.

## Riscos e como reverter
- **Bug na v1 afeta o servidor:** a v1 fica isolada no `bloquear_v1` e no `despachar_v1`, e o CA9 roda as suítes existentes. Para reverter, desfaça o commit. Para desligar sem reverter, apague `api_token.txt` e reinicie (a v1 passa a dar 503).
- **Item perdido no cursor por commit lento:** a folga de 60 s cobre os lotes das coletas, que levam segundos. Se aparecer perda, aumente a constante. Em último caso o consumidor se recupera, porque deduplica por `chave`.
- **Item apagado não é avisado:** ele some da API e pronto. O Turbo pega dados novos a cada execução, então o efeito é nenhum.
- **Reclassificação (`migrar_categorias.py`) regrava `atualizado_em` de milhares de itens:** eles voltam a aparecer na ordem `atualizacao`. Esse é o comportamento esperado (a `cat` mudou), e a `chave` evita repetição.
- **Turbo numa VPS (o dono adiou):** a abordagem A não alcança o computador do dono. O caminho é um script de saída que empurra o mesmo JSON para um endpoint HTTPS do Turbo com token (abordagem B). O formato da oferta foi pensado para isso.
- **Mudança no Turbo por outra sessão:** este plano não toca `/home/ufla/Documentos/achadinhoturbo`. As linhas citadas podem mudar, e o guia de encaixe é uma sugestão.
- **Migração:** não há.

## Decisões tomadas na implementação (03/11/2026)
- **P3 revista por recomendação do `seguranca`:** o guia de encaixe manda o Turbo **regerar o link do ML** com a etiqueta do dono (ou revisar antes de enviar) e **revisar os da Shopee** antes de enviar. Motivo: o Etiqueta confere só o formato (`meli.la`, `s.shopee.com.br`), não de quem é a conta; com o R1 (API local sem token para escrita), um link de terceiro plantado no banco chegaria aos grupos sem revisão. Amazon segue "como veio" (a tag é conferida).
- O dono pediu para seguir até o fim sem parar; as premissas P1, P2, P4 a P7 foram adotadas como estão.

## Perguntas em aberto e premissas adotadas
- **P1 (dono):** o Turbo busca no Etiqueta (pull)? *Premissa:* sim.
- **P2 (dono):** a v1 exige token em `api_token.txt` e fica desligada até você criar esse arquivo? *Premissa:* sim.
- **P3 (dono):** no Turbo, o link sai como está no Etiqueta (ML com a etiqueta `achadosmenicas`, Amazon com `desejodemen01-20`, Shopee curto) ou o Turbo gera de novo com as etiquetas dele? *Premissa:* sai como está. Isso só afeta o Turbo.
- **P4 (dono):** a mensagem pronta fica fora da v1, e o Turbo usa os templates dele? *Premissa:* sim.
- **P5 (dono):** os itens com algo parecido com link no título ou no cupom (14 hoje, como `i.Phone`) ficam fora da API, como no disparo? *Premissa:* sim.
- **P6 (dono):** precisa das duas formas de consumo, "novidades desde a última vez" e "as melhores por execução"? *Premissa:* sim. Se não precisar, corte uma delas (veja Decisão).
- **P7 (dono):** as regras automáticas do Turbo hoje só enviam ML e Amazon (README do Turbo, "Disparo manual com um link da Shopee"). Os 540 itens da Shopee vão sair na API, mas dependem de suporte no Turbo. Tudo bem?
- *Premissa:* não haverá `GET /api/v1/ofertas/<id>`. O Turbo relê a lista a cada execução. Fica para a v1.1 se aparecer necessidade.

## ADR
**ADR — API pública de leitura `/api/v1` com token Bearer em arquivo (2026-11-03)**
- **Contexto:** primeiro cliente que não é navegador nem página do Etiqueta: o Achadinho Turbo, local, em Node.
- **Decisão:**
  - O Turbo puxa.
  - A rota tem prefixo versionado `/api/v1/` e só aceita GET.
  - A autenticação é um token Bearer lido de `api_token.txt` (fora do git), comparado em tempo constante. Sem o token, a API fica desligada.
  - Navegador é barrado (Origin ou Sec-Fetch-Site dá 403) e não há CORS.
  - A oferta sai normalizada, com números, e só com link de afiliado da própria loja.
  - A lógica fica em `api_ofertas.py`, que não importa `servidor`.
- **Alternativas:** push, que fica para quando houver VPS; leitura direta do banco, descartada; sem token, descartada para não mudar o contrato depois.
- **Consequências:**
  - Mudança incompatível no formato exige `/api/v2/`.
  - Campo novo pode entrar na v1, e o consumidor deve ignorar campo desconhecido.
  - Para trocar o token: troque o arquivo, reinicie o servidor e atualize em Conexões no Turbo.
